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

### pyproject.toml so `runcoach` is importable without sys.path hacks

**Current state.** Step 1 of the package refactor is done — `runcoach/paths.py` exists and every tool now imports `PROJECT_ROOT` / `data_dir` / `load_allowlist` from there. But tools still bootstrap by `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` before importing runcoach. That's because tools are invoked as `python tools/foo.py` and Python doesn't auto-add the script's parent to `sys.path`.

**Plan.**
1. Add a minimal `pyproject.toml` with `[project] name = "runcoach"` and `[tool.setuptools.packages.find]`.
2. Run `pip install -e .` once on the host.
3. Delete the `sys.path.insert` lines at the top of every migrated tool.
4. Replace `import runcoach.paths  # noqa: F401` (currently used just to trigger `load_dotenv`) with explicit imports from `runcoach.paths`.

**Why not now.** Adds a deployment step (`pip install -e .`) the user has to run once on the home PC. The current bootstrap is ugly but consistent and works without that step.

### Negative-split sub-second precision (deferred from review review)

`runcoach.fit.parse_fit` and `tools/strava_pull.py` both detect negative-split by averaging lap paces — currently via `pace_to_sec(pace_from_speed(...))`, a round-trip through `"M:SS"` strings that loses sub-second precision. For two halves that differ by < 1 sec/km the comparison can flip. Fix: keep lap speed/time as floats, compute mean speed per half, compare in float space. Pinned in `tests/test_metrics.py::test_roundtrip_loses_subsecond_precision`.

---

## Operations

### OS keyring vs config flag for credentials (linked to security fix above)

Decide whether the `keyring`-backed credential store should be opt-in (env flag `RUNCOACH_USE_KEYRING=1`) or always-on after migration. Opt-in keeps the migration reversible; always-on is simpler.
