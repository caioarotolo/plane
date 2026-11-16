# Agent Development Guide

## OpenMarkets fork policy

- Work in `caioarotolo/plane`: `origin` is the user's fork and `upstream` is `makeplane/plane`. Open PRs against `preview`. A push, merge or upstream sync into `preview` automatically builds and deploys production at `https://planner.openmarkets.com.br`.
- **Keep CI tests and validation jobs disabled.** GitHub Actions is for production image builds, publishing and deployment only. Do not add or re-enable remote test suites, lint, formatting, type checks, CodeQL, React Doctor or other validation workflows unless the user explicitly requests it. PRs must not launch builds or test runners.
- Upstream validation workflows are restricted to the upstream repository and disabled in this fork's Actions settings where registered. Preserve those restrictions when syncing upstream; inspect any newly introduced workflows before merging.
- Before a production push/merge, agents may run the same checks on the user's local machine. Choose checks relevant to the change, reuse still-valid results, and report what passed, failed or was not run. Use the full suites for broad application changes or substantial upstream updates; documentation/workflow-only changes need targeted configuration validation, not a full application test run. Do not move local checks back into Actions to work around missing local dependencies.
- Keep the test source and local tooling available. Automatic database backups, migrations, container health checks, public availability checks and deployment recovery remain enabled; these are operational deployment safeguards.
- Keep changes direct and small. Never commit production credentials, modify production data to run local tests, or push to upstream. Preserve the existing Compose volumes and OAuth proxy routes. See `deployments/openmarkets/README.md` for deployment/recovery.
- Use skills or plugin-provided tools only when explicitly requested by the user; ordinary workspace, shell and web tools remain available.

## Local validation before deployment

Use Node from `.node-version` and pnpm from `package.json` via Corepack. The former CI commands remain available locally; run the applicable subset rather than every command for every edit:

```sh
corepack enable pnpm
pnpm install --frozen-lockfile
pnpm turbo run check:lint check:types --concurrency=2
pnpm turbo run test --concurrency=1 -- --maxWorkers=2
pnpm check:format
python3 -m unittest discover -s deployments/openmarkets/tests -v
```

For backend changes, configure the **local test** environment as described below, without overwriting an existing `.env`, then use the isolated Docker test stack:

```sh
docker compose -f docker-compose-test.yml run --build --rm api-tests \
  sh -c 'uv run --no-sync ruff check . && pytest -q -o addopts="--strict-markers --nomigrations"'
docker compose -f docker-compose-test.yml down -v
```

Run migration drift/lockfile checks, translation synchronization and copyright checks locally when those files change. Their original commands remain documented in the upstream workflow files, whose jobs do not run in this fork. Never use the production Compose project for test teardown.

## Commands

- `pnpm dev` - Start all dev servers (web:3000, admin:3001, space:3002, live:3100); the API runs in Docker via `docker-compose-local.yml` on :8000
- `pnpm build` - Build all packages and apps
- `pnpm check` - Run all checks (format, lint, types)
- `pnpm check:lint` - OxLint across all packages
- `pnpm check:types` - TypeScript type checking
- `pnpm fix` - Auto-fix format and lint issues
- `pnpm turbo run <command> --filter=<package>` - Target specific package/app

## Code Style

- **Imports**: Use `workspace:*` for internal packages, `catalog:` for external deps
- **TypeScript**: Strict mode enabled, all files must be typed
- **Formatting**: oxfmt, run `pnpm fix:format`
- **Linting**: OxLint with shared `.oxlintrc.json` config
- **Naming**: camelCase for variables/functions, PascalCase for components/types
- **Error Handling**: Use try-catch with proper error types, log errors appropriately
- **State Management**: MobX stores live in each app's `store/` folder (`apps/web/store`, `apps/space/store`, `apps/admin/store`); stores shared across apps go in `packages/shared-state`
- **Testing**: All features require unit tests, use existing test framework per package
- **Components**: Primitives come from the published `@makeplane/propel` npm package (`@makeplane/propel/components/*`, `elements/*`, `icons`); composite/Plane-specific components live in `@plane/blocks` (`packages/blocks`, subpath imports only, e.g. `@plane/blocks/toast`)

## Backend dependencies (uv)

`apps/api` dependencies are managed with [uv](https://docs.astral.sh/uv/): declared in `apps/api/pyproject.toml`, pinned in `apps/api/uv.lock` (commit both). Groups: `dev` and `test` (installed by default; they use `psycopg-binary`), `production` (gunicorn + the source-built `psycopg-c`; production image and migration-check only). Lint config lives in `apps/api/ruff.toml`.

- uv must be exactly the `required-version` in `apps/api/pyproject.toml` (`uv self update <version>`); bump it together with the uv image in both Dockerfiles
- Set up a local env: `cd apps/api && uv sync`
- Inside the dev/test containers, always pass `--inexact` (`uv sync --inexact`): uv targets the image's system Python there, and an exact sync would uninstall pip
- Add/upgrade a dependency: `uv add <pkg>==<version>` (or `--group test`/`--group dev`), or edit `pyproject.toml` and run `uv lock`
- Run tools: `uv run python manage.py ...`, `uv run ruff check .`

## Migrations

- Generate migrations with `uv run python manage.py makemigrations <app> -n <name>`. The command also rewrites `apps/api/migrations_lockfile.txt`; commit it with the migration and never edit it by hand
- A merge conflict in the lockfile means another PR added a migration to the same app first: merge `preview`, delete your migration, and run `makemigrations` again
- The upstream `migration-check.yml` documents migration graph/lockfile validation. Run the relevant checks locally in this fork; its CI job is disabled.

## Backend tests (Docker)

The Django/pytest suite for `apps/api` runs in an isolated stack defined by `docker-compose-test.yml` at the repo root.

Prereq (once): `./setup.sh` — generates `apps/api/.env` from `.env.example`.

- Full suite: `docker compose -f docker-compose-test.yml up --build --abort-on-container-exit --exit-code-from api-tests`
- Subset: `docker compose -f docker-compose-test.yml run --rm --build api-tests pytest -m unit`
- Teardown: `docker compose -f docker-compose-test.yml down -v`

See `apps/api/tests/RUNNING_TESTS.md` for the full walkthrough and troubleshooting; see `apps/api/plane/tests/TESTING_GUIDE.md` for test conventions and fixtures.

## Translations

Strings live in `packages/i18n/src/locales/<lang>/<namespace>.json`; `en` is the source of truth and every locale must have the same keys. Run `pnpm --filter=@plane/i18n sync:check` locally when changing locale files. Use a translation skill only if the user explicitly invokes it.

## Pull requests

Open PRs against the fork's `preview`. New `.py`, `.ts` and `.tsx` files need the `COPYRIGHT.txt` header (verify locally; see `COPYRIGHT_CHECK.md`).
