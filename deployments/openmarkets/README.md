# OpenMarkets continuous deployment

Only the user's forks deploy:

- `caioarotolo/plane`, branch `preview`: API tests/lint, frontend lint/types/tests,
  six Docker builds, then production deployment.
- `caioarotolo/plane-mcp-server`, branch `main`: upstream + OAuth tests, lint,
  formatting, Docker build, then production deployment.

A merge, direct push or upstream synchronization onto these branches runs the
pipeline automatically. PRs validate without deployment credentials. Manual
`workflow_dispatch` can retry the production branch. The app deliberately follows
upstream development (`preview`), not only stable releases.

## Build and deployment

GitHub-hosted runners build `linux/amd64` images and publish to GHCR with full
commit tags and source/revision labels. The VPS checks the branch is still at
that commit, pulls the images, verifies their revision and pins actual registry
digests in `release.compose.json`. A superseded build is skipped. GitHub
concurrency plus a VPS lock serializes deployments, including app/MCP overlap.

The existing Compose configuration, environment files, Caddy routes, certificates
and data volumes remain on the VPS. Database, object storage and queue/cache
images are managed separately from application releases. No `down -v` is used in
production. `plane.sh` and `mcp.sh` include the release overlay for manual work.

The app briefly stops public traffic and application processes. It creates and
verifies a PostgreSQL dump, runs migrations, and waits for the new app containers
to be healthy before reopening traffic and starting task workers. Failure before
reopening restores the database snapshot and previous images. After traffic
reopens, automatic database restoration is forbidden to avoid losing new writes;
the failed workflow identifies the need for investigation. MCP health failure
restores its previous image without changing Redis or credentials.

Database maintenance commands run inside the PostgreSQL container over its local
Unix socket. They override the shared `PGHOST` setting so application TCP
connection settings cannot redirect backups/restores or require an extra secret.

Backups and the previous image map are in
`/home/caio/plane-deploy/backups/<timestamp>-<commit>/`. The latest successful
commit is recorded in `app-last-success.json` / `mcp-last-success.json` in the same
state directory. Backups contain private data and are mode 0600 in private
directories. They are not uploaded to GitHub. The receiver refuses to start an
update with less than 5 GiB available; archive old backups/images as needed.

## Credentials and bootstrap

Production environments only allow their repository's production branch.
Each repository has its own environment secret `DEPLOY_SSH_KEY`. Public repository
variables are `DEPLOY_HOST`, `DEPLOY_PORT` and `DEPLOY_KNOWN_HOSTS`.

The existing administrative SSH access remains on Tailscale. A separate sshd on
TCP 2222 accepts only the two CI public keys, each forced to its fixed receiver
target. Passwords, root login, PTYs, forwarding, user rc and arbitrary commands
are disabled. The host key is obtained through the existing trusted SSH session
and pinned in Actions. The receiver accepts only `deploy <40 lowercase hex>`.

The job passes a short-lived, repository-scoped `GITHUB_TOKEN` for private GHCR
pulls through SSH standard input. It is never placed in command arguments or
persisted as a server credential. Temporary Docker authentication is deleted
after the deploy. No production app/database secret is copied to GitHub.

`receiver.py` is installed root-owned at
`/usr/local/lib/plane-deploy/receiver.py`. Updating deployment infrastructure
requires installing this file over the administrative SSH connection; the CI key
cannot replace its own receiver or run arbitrary scripts. CI deploys application
code through images, not by uploading executable shell scripts.

The upstream `Branch Build CE` publisher is guarded by its original repository
name because it publishes to upstream-owned registries. This one-line guard
prevents it running in the fork; our separate workflow owns fork deployment.

## Recovery

An unsuccessful build/test does not touch production. A failure during a
deployment is visible in GitHub Actions; inspect its log and the receiver's last
success record. For MCP, use the previous image overlay with `mcp.sh up -d`.
For the app, inspect migrations before reverting images; never restore a database
while users/workers can write. Use the private pre-deploy dump and `images.json`
only during a maintenance window. Keep the upload volume and encryption keys.

Run receiver boundary tests with:

```sh
python3 -m unittest discover -s deployments/openmarkets/tests -v
```
