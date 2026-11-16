# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("receiver", Path(__file__).parents[1] / "receiver.py")
receiver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receiver)


class DeploymentBoundaries(unittest.TestCase):
    def test_remote_key_cannot_request_shell_or_arbitrary_image(self):
        for command in [
            "",
            "sh",
            "deploy latest",
            "deploy " + "a" * 40 + "; id",
            "deploy " + "a" * 40 + "\n",
            "deploy ghcr.io/other/image",
        ]:
            with self.subTest(command=command), self.assertRaises(ValueError):
                receiver.parse_command(command)
        self.assertEqual(receiver.parse_command("deploy " + "a" * 40), "a" * 40)

    def test_wrong_revision_or_registry_is_rejected(self):
        repository, sha = "ghcr.io/caioarotolo/plane-backend", "a" * 40
        info = {
            "Config": {"Labels": {"org.opencontainers.image.revision": sha}},
            "RepoDigests": [repository + "@sha256:" + "b" * 64],
        }
        self.assertEqual(receiver.pinned_image(info, repository, sha), info["RepoDigests"][0])
        with self.assertRaises(ValueError):
            receiver.pinned_image(info, repository, "c" * 40)
        with self.assertRaises(ValueError):
            receiver.pinned_image(info, "ghcr.io/other/backend", sha)

    def test_database_restore_is_forbidden_after_public_traffic_returns(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(receiver.TARGETS, {"app": ("plane", "preview", Path(directory), "compose.yaml")}),
            patch.object(receiver, "run") as execute,
        ):
            deployment = receiver.Deployment("app", "a" * 40, "test-token", directory)
            deployment.traffic_open = True
            deployment.migration_started = True
            with self.assertRaises(RuntimeError):
                deployment.restore_before_traffic()
            execute.assert_not_called()

    def test_mcp_health_failure_restores_previous_image_without_database_operations(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(receiver.TARGETS, {"mcp": ("plane-mcp-server", "main", Path(directory), "compose.yaml")}),
            patch.object(receiver, "run") as execute,
        ):
            root = Path(directory)
            (root / "release.compose.json").write_text('{"old":true}')
            deployment = receiver.Deployment("mcp", "a" * 40, "test-token", directory)
            deployment.candidate.write_text('{"new":true}')
            deployment.compose = Mock(side_effect=[RuntimeError("unhealthy"), None])
            with self.assertRaises(RuntimeError):
                deployment.activate()
            self.assertEqual(deployment.active.read_text(), '{"old":true}')
            self.assertEqual(deployment.compose.call_count, 2)
            execute.assert_not_called()

    def test_migration_failure_restores_snapshot_before_old_services_restart(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(receiver.TARGETS, {"app": ("plane", "preview", Path(directory), "compose.yaml")}),
            patch.object(receiver, "run") as execute,
        ):
            root = Path(directory)
            (root / "release.compose.json").write_text('{"old":true}')
            (root / "database.dump").write_bytes(b"test archive")
            deployment = receiver.Deployment("app", "a" * 40, "test-token", directory)
            deployment.backup = root
            deployment.database_backup = Mock()
            deployment.candidate.write_text('{"new":true}')
            deployment.compose = Mock(side_effect=[None, RuntimeError("migration failed"), None, None, None])
            with self.assertRaises(RuntimeError):
                deployment.activate()
            self.assertEqual(deployment.active.read_text(), '{"old":true}')
            self.assertFalse(deployment.traffic_open)
            self.assertEqual(execute.call_count, 2)
            self.assertIn("dropdb --force", execute.call_args_list[0].args[0][-1])
            self.assertIn("pg_restore --exit-on-error", execute.call_args_list[1].args[0][-1])
            self.assertEqual(deployment.compose.call_args_list[-1].args, ("up", "-d", "--no-deps", "proxy"))

    def test_failed_backup_never_migrates_or_restores_database(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(receiver.TARGETS, {"app": ("plane", "preview", Path(directory), "compose.yaml")}),
            patch.object(receiver, "run") as execute,
        ):
            root = Path(directory)
            (root / "release.compose.json").write_text('{"old":true}')
            deployment = receiver.Deployment("app", "a" * 40, "test-token", directory)
            deployment.candidate.write_text('{"new":true}')
            deployment.database_backup = Mock(side_effect=RuntimeError("backup failed"))
            deployment.compose = Mock()
            with self.assertRaisesRegex(RuntimeError, "backup failed"):
                deployment.activate()
            self.assertFalse(deployment.migration_started)
            self.assertEqual(deployment.active.read_text(), '{"old":true}')
            self.assertFalse(deployment.candidate.exists())
            self.assertFalse(any("migrator" in call.args for call in deployment.compose.call_args_list))
            execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
