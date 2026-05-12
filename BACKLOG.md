# Backlog

Deferred fixes from the project review. Update or remove entries as they get done.

---

## Security

### Plaintext credential storage (deferred from review fix #8)

**Current state.** Garmin Connect passwords are stored as plaintext JSON in `users/<name>/data/garmin_credentials.json`. The owner's credentials can alternatively live in `.env` as `GARMIN_EMAIL` / `GARMIN_PASSWORD` (also plaintext, gitignored). Strava refresh tokens are plaintext at `users/<name>/data/strava_token.json`.

**Risk.** Any local user, app, or malware with read access to the Windows user profile can lift the credentials. During onboarding, the password also passes through Telegram (third-party server) and the LLM (logged by Anthropic) — see `.claude/skills/telegram-onboarding/SKILL.md` Phase 2.

**Plan when this gets prioritized.**

1. Add `keyring` to `requirements.txt`. On Windows it wraps DPAPI: per-user encryption tied to the Windows login.
2. Replace `garmin_auth.save_garmin_credentials` to call `keyring.set_password("runcoach-garmin", user, password)` instead of writing JSON.
3. Replace `garmin_auth.get_garmin_credentials` to call `keyring.get_password(...)`, with the existing JSON file as a one-time-migration fallback. Migrate-then-delete on first read.
4. Same pattern for Strava refresh tokens — these are less sensitive (already short-lived bearer tokens) and can ship in a second pass.
5. Update `.claude/skills/telegram-onboarding/SKILL.md` Phase 2 to acknowledge that the credential still passes through Telegram + the LLM at onboarding time. The keyring fix only protects at-rest storage. A more thorough fix would direct the user to a local web form instead of pasting passwords into the bot.

**Open design questions.**
- Whether to use `keyring` (adds a runtime dependency) versus rolling our own DPAPI wrapper via `pywin32`.
- Whether the bridge process can read the keyring (it can today — Startup Folder runs as the same Windows user — but if we ever switch to running under SYSTEM via a service, DPAPI won't unlock).

---

## Refactor

### Tools/ package layout (deferred from review fix #6)

**Current state.** `tools/` is a flat directory of 21 scripts. Each one re-imports `load_dotenv`, redefines `PROJECT_ROOT`, redefines `_data_dir`, and uses `sys.path.insert` hacks to import siblings (e.g. `telegram_bridge.py` reaches into `tools/` to import `sheets_read`).

**Risk.** Low (works today), but every new tool inherits the boilerplate, the `sys.path` tricks are fragile to cwd changes, and the duplicated `_data_dir` / `append_to_log` definitions drift apart (already happened once — `analyze_fit` and `strava_pull` had subtly different dedup logic).

**Plan when this gets prioritized.**

1. Create `runcoach/` package (top-level next to `tools/`): `runcoach/{paths,auth,sheets,fit,run_log,telegram_format}.py`.
2. Move shared helpers there (`_data_dir`, `load_allowlist`, `append_to_log`, FIT helpers, `smart_split` / tag-balancing).
3. Convert `tools/*.py` into thin CLI wrappers that import from `runcoach.*`. Same external behavior, no boilerplate.
4. Drop every `sys.path.insert` in the project.

**Why not now.** Touches every tool in the project. Best done in a dedicated session with thorough regression testing.

---

## Operations

### OS keyring vs config flag for credentials (linked to security fix above)

Decide whether the `keyring`-backed credential store should be opt-in (env flag `RUNCOACH_USE_KEYRING=1`) or always-on after migration. Opt-in keeps the migration reversible; always-on is simpler.
