# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Restricted SSH deploy receiver, installed root-owned on the VPS once.

Only the target fixed in authorized_keys and a 40-character commit are accepted.
Application code is built by Actions; production never executes uploaded scripts.
"""

import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/caio")
STATE = ROOT / "plane-deploy"
TARGETS = {
    "app": ("plane", "preview", ROOT / "plane", "docker-compose.yaml"),
    "mcp": ("plane-mcp-server", "main", ROOT / "plane-mcp-oauth", "compose.yaml"),
}
COMPONENTS = {
    "api": "backend",
    "worker": "backend",
    "beat-worker": "backend",
    "migrator": "backend",
    "web": "frontend",
    "admin": "admin",
    "space": "space",
    "live": "live",
    "proxy": "proxy",
}
READERS = ["api", "web", "admin", "space", "live"]
WRITERS = ["worker", "beat-worker"]


def parse_command(command):
    match = re.fullmatch(r"deploy ([0-9a-f]{40})", command)
    if not match:
        raise ValueError("Only deploy followed by a full commit SHA is allowed")
    return match[1]


def run(args, *, capture=False, **kwargs):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE if capture else None, **kwargs)


def pinned_image(info, repository, sha):
    labels = info.get("Config", {}).get("Labels") or {}
    if labels.get("org.opencontainers.image.revision") != sha:
        raise ValueError("Image revision does not match requested commit")
    for digest in info.get("RepoDigests") or []:
        if re.fullmatch(re.escape(repository) + r"@sha256:[0-9a-f]{64}", digest):
            return digest
    raise ValueError("No verified registry digest found")


def write_json(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n")
    tmp.chmod(0o600)
    tmp.replace(path)


class Deployment:
    def __init__(self, target, sha, token, docker_config):
        self.target, self.sha, self.token = target, sha, token
        self.repo, self.branch, self.root, self.compose_file = TARGETS[target]
        self.env = dict(os.environ, DOCKER_CONFIG=docker_config)
        self.active = self.root / "release.compose.json"
        self.old = self.active.read_bytes() if self.active.exists() else None
        self.candidate = self.root / "release.candidate.json"
        self.migration_started = False
        self.traffic_open = False
        self.stopped = False
        self.backup = None

    def compose(self, *args, candidate=False, **kwargs):
        command = ["docker", "compose", "--project-directory", str(self.root)]
        if self.target == "app":
            command += ["--env-file", str(self.root / "plane.env")]
        command += ["-f", str(self.root / self.compose_file)]
        overlay = self.candidate if candidate else self.active
        if overlay.exists():
            command += ["-f", str(overlay)]
        return run(command + list(args), env=self.env, **kwargs)

    def is_current(self):
        request = urllib.request.Request(
            f"https://api.github.com/repos/caioarotolo/{self.repo}/commits/{self.branch}",
            headers={"Authorization": "Bearer " + self.token, "User-Agent": "OpenMarkets-deploy"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)["sha"] == self.sha

    def prepare(self):
        if shutil.disk_usage(self.root).free < 5 * 1024**3:
            raise RuntimeError("Less than 5 GiB free; existing deployment left unchanged")
        run(
            ["docker", "login", "ghcr.io", "-u", "caioarotolo", "--password-stdin"],
            input=(self.token + "\n").encode(),
            env=self.env,
            capture=True,
        )
        components = set(COMPONENTS.values()) if self.target == "app" else {"mcp-server"}
        images = {}
        for component in sorted(components):
            repository = "ghcr.io/caioarotolo/plane-" + component
            tagged = repository + ":sha-" + self.sha
            run(["docker", "pull", "--quiet", tagged], env=self.env)
            info = json.loads(run(["docker", "image", "inspect", tagged], capture=True).stdout)[0]
            images[component] = pinned_image(info, repository, self.sha)
        services = (
            {name: {"image": images[component]} for name, component in COMPONENTS.items()}
            if self.target == "app"
            else {"http": {"image": images["mcp-server"]}}
        )
        write_json(self.candidate, {"services": services})
        if self.target == "app":
            self.compose("run", "--rm", "--no-deps", "api", "python", "manage.py", "check", candidate=True)
            self.compose(
                "run",
                "--rm",
                "--no-deps",
                "proxy",
                "caddy",
                "validate",
                "--config",
                "/etc/caddy/Caddyfile",
                "--adapter",
                "caddyfile",
                candidate=True,
            )

    def database_backup(self):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.backup = STATE / "backups" / (stamp + "-" + self.sha[:12])
        self.backup.mkdir(parents=True, mode=0o700)
        config = json.loads(self.compose("config", "--format", "json", capture=True).stdout)
        write_json(
            self.backup / "images.json",
            {"services": {name: {"image": config["services"][name]["image"]} for name in COMPONENTS}},
        )
        with (self.backup / "database.dump").open("wb") as archive:
            subprocess.run(
                [
                    "docker",
                    "exec",
                    "plane-plane-db-1",
                    "sh",
                    "-c",
                    'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc',
                ],
                stdout=archive,
                check=True,
            )
        with (self.backup / "database.dump").open("rb") as archive:
            run(["docker", "exec", "-i", "plane-plane-db-1", "pg_restore", "--list"], stdin=archive, capture=True)

    def restore_before_traffic(self):
        # This can restore data only while public traffic and task workers are stopped.
        # Once traffic reopens, automatic database restoration is forbidden.
        if self.traffic_open:
            raise RuntimeError("Traffic already reopened; inspect health and backup before manual recovery")
        if self.target == "app" and self.stopped:
            self.compose("stop", "proxy", *READERS, *WRITERS)
            if self.migration_started:
                run(
                    [
                        "docker",
                        "exec",
                        "plane-plane-db-1",
                        "sh",
                        "-c",
                        'dropdb --force -U "$POSTGRES_USER" "$POSTGRES_DB" && '
                        'createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" "$POSTGRES_DB"',
                    ]
                )
                with (self.backup / "database.dump").open("rb") as archive:
                    run(
                        [
                            "docker",
                            "exec",
                            "-i",
                            "plane-plane-db-1",
                            "sh",
                            "-c",
                            "exec pg_restore --exit-on-error --no-owner --no-privileges "
                            '-U "$POSTGRES_USER" -d "$POSTGRES_DB"',
                        ],
                        stdin=archive,
                    )
        if self.old is None:
            self.active.unlink(missing_ok=True)
        else:
            self.active.write_bytes(self.old)
        if self.target == "app" and self.stopped:
            self.compose("up", "-d", "--no-deps", "--wait", "--wait-timeout", "240", *READERS, *WRITERS)
            self.compose("up", "-d", "--no-deps", "proxy")
        elif self.target == "mcp":
            self.compose("up", "-d", "--no-deps", "--wait", "--wait-timeout", "180", "http")

    def activate(self):
        try:
            if self.target == "app":
                self.stopped = True
                self.compose("stop", "proxy", *READERS, *WRITERS)
                self.database_backup()
            self.candidate.replace(self.active)
            if self.target == "app":
                self.migration_started = True
                self.compose("run", "--rm", "--no-deps", "migrator")
                self.compose("up", "-d", "--no-deps", "--wait", "--wait-timeout", "240", *READERS)
                # App health succeeded. Never restore the DB automatically after this point.
                self.traffic_open = True
                self.compose("up", "-d", "--no-deps", "--wait", "--wait-timeout", "120", "proxy", *WRITERS)
            else:
                self.compose("up", "-d", "--no-deps", "--wait", "--wait-timeout", "180", "http")
            write_json(
                STATE / (self.target + "-last-success.json"),
                {
                    "commit": self.sha,
                    "deployed_at": datetime.now(timezone.utc).isoformat(),
                    "backup": str(self.backup) if self.backup else None,
                },
            )
        except Exception:
            if not self.traffic_open:
                self.restore_before_traffic()
            raise
        finally:
            self.candidate.unlink(missing_ok=True)


def main():
    os.umask(0o077)
    if len(sys.argv) != 2 or sys.argv[1] not in TARGETS:
        raise ValueError("Unknown deployment target")
    sha = parse_command(os.environ.get("SSH_ORIGINAL_COMMAND", ""))
    token = sys.stdin.readline(4097).strip()
    if not token or len(token) > 4096 or not re.fullmatch(r"[A-Za-z0-9_.-]+", token):
        raise ValueError("Missing or invalid registry credential")
    STATE.mkdir(mode=0o700, exist_ok=True)
    with (STATE / "deployment.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # Serializes app and MCP deployments on this VPS.
        with tempfile.TemporaryDirectory(prefix="plane-ghcr-") as config:
            deployment = Deployment(sys.argv[1], sha, token, config)
            if not deployment.is_current():
                print("Skipped: a newer commit is already on the production branch.")
                return
            deployment.prepare()
            if not deployment.is_current():
                deployment.candidate.unlink(missing_ok=True)
                print("Skipped: a newer commit arrived during image preparation.")
                return
            deployment.activate()
            print(f"Deployed {deployment.target} commit {sha}.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Do not print inputs, environment, registry credentials or HTTP bodies.
        print(f"Deployment failed ({type(error).__name__}): {error}", file=sys.stderr)
        sys.exit(1)
