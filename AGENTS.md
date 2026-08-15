# AGENTS.md

## Cursor Cloud specific instructions

### Overview

Python monorepo ("Supervendedor Core / ED NET PRO 3.0") — an AI WhatsApp/voice sales
platform. Two runnable services plus CLI scripts. See `CLAUDE.md` and `readme.md` for
the architecture; standard run/test commands live in `CLAUDE.md`, `readme.md` and
`scripts/run_tests.ps1`.

- **FastAPI core** (`app/main.py`) — the product backend. Dev: `python3 -m uvicorn app.main:app --reload --port 8000`. Docs at `/docs`, health at `/health`.
- **Streamlit dashboard** (`admin_panel/dashboard.py`) — "Centro de Comando". Dev: `python3 -m streamlit run admin_panel/dashboard.py --server.port 8501`.

### Non-obvious caveats

- Use `python3`, not `python` (there is no `python` alias on this VM). `pip install`
  places console scripts (`uvicorn`, `streamlit`, `pytest`) under `~/.local/bin`, which
  is not on `PATH` by default — invoke via `python3 -m <tool>` to avoid PATH issues.
- The app reads config from `.env` (no space) via `python-dotenv` / pydantic-settings.
  A committed file named `. env` (WITH a space) exists but is NOT loaded by the app —
  do not confuse the two. `.env` is git-ignored.
- For offline local dev, run with a `.env` that sets `FOLLOWUP_SCHEDULER_ENABLED=false`
  and leaves `POCKETBASE_URL` / `POCKETBASE_EMAIL` / `POCKETBASE_PASSWORD` empty.
  Otherwise startup enables a background scheduler that reaches out to the remote
  PocketBase VPS (`http://178.105.48.103:8090` is the default when `POCKETBASE_URL` is
  unset). With PocketBase empty the app degrades gracefully: CRM writes log warnings and
  return local fallback ids, but catalog/ZOPA/metrics/webhook routing all still work.
- The Streamlit dashboard's "Canales en vivo" panel pulls live data from the FastAPI
  core (`/health`, `/api/v1/metrics/overview`). Start the FastAPI service first so those
  cards show ONLINE; the dashboard still loads (in demo mode) if the API is down.
- All AI/channel API keys (OpenAI, Anthropic, Gemini, Evolution/WhatsApp, Vapi, Meta,
  ElevenLabs, Replicate, Google Maps) are feature-gated: missing keys just disable that
  module with a warning — they are not required to boot either service.

### Tests / lint / build

- Tests: `FOLLOWUP_SCHEDULER_ENABLED=false python3 -m pytest tests/test_smoke.py -v`
  (root also has ad-hoc `test_*.py` scripts that need live API keys).
- Known pre-existing test failures (code bugs, NOT environment issues): the two
  `whatsapp_webhook` tests fail because `app/orchestrator.py` imports `get_client_context`
  from `app.main`, which no longer exists after the core refactor; `test_ads_run_cycle_mocked`
  fails because it monkeypatches `app.routers.ads_router.run_ads_cycle`, which is not exported
  there. The other 8 smoke tests pass.
- No linter/formatter is configured (no ruff/flake8/pyproject). For a quick syntax check:
  `python3 -m compileall -q app admin_panel`.
- No build step (interpreted Python). Deployment is Railway/Nixpacks (`railway.json`).
