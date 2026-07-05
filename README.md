# Studio Agent Alpha — Deployment Handoff

## Deployment objective
Deploy Studio Agent Alpha as a Docker-backed Render web service with append-only provenance, a `/verify` heartbeat, a one-time setup path for the DeepSeek key, and a minimal money-gate admin surface for proposal approval/decline events.

## Verified bundle contents
- `Dockerfile`
- `requirements.txt`
- `orchestrator.py`
- `render.yaml`

## Critical deployment constraints
- Keep the GitHub repository private.
- Do not commit secrets.
- Do not enable automatic spending during acceptance testing.
- Set Render runtime from `render.yaml`; this bundle uses `runtime: docker`.
- Keep `plan: free` for initial verification unless Marcos explicitly approves a paid instance.

## Required Render environment variables
- `PORT=8080`
- `MONEY_GATE_ENABLED=true`
- `DEEPSEEK_API_KEY` — secret, sync false
- `SETUP_TOKEN` — secret, sync false
- `ADMIN_TOKEN` — secret, sync false

## Acceptance test path
1. Deploy the private repo to Render from `render.yaml`.
2. Open `/` and confirm the active service message.
3. POST to `/setup` with header `X-Setup-Token: <SETUP_TOKEN>` and body `{"deepseek_key":"<DEEPSEEK_API_KEY>"}`.
4. POST to `/trigger-scout` with header `X-Admin-Token: <ADMIN_TOKEN>`.
5. GET `/verify` and confirm `last_entry.action == "HEARTBEAT_SCOUT"`.
6. Open `/admin`, enter the admin token, create a dry-run proposal, then approve or decline it via endpoint.
7. Confirm provenance contains `MONEY_GATE_PROPOSED` and either `MONEY_GATE_APPROVED` or `MONEY_GATE_DECLINED`.

## Pause / revoke
- Pause service in Render dashboard to stop runtime execution.
- Remove `DEEPSEEK_API_KEY`, `SETUP_TOKEN`, and `ADMIN_TOKEN` from Render env vars and redeploy to revoke runtime secret access.
