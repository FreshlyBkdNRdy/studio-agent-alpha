import json
import os
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

try:
    from apscheduler.schedulers.background import BackgroundScheduler
except ModuleNotFoundError:  # Allows local smoke tests before dependencies are installed.
    BackgroundScheduler = None
from flask import Flask, jsonify, request

app = Flask(__name__)

PROVENANCE_LOG = Path(os.getenv("PROVENANCE_LOG", "provenance.jsonl"))
PROPOSALS_LOG = Path(os.getenv("PROPOSALS_LOG", "proposals.jsonl"))

CONFIG = {
    "secrets": {"deepseek": os.getenv("DEEPSEEK_API_KEY", "")},
    "money_gate": os.getenv("MONEY_GATE_ENABLED", "true").lower() == "true",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, entry: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True) if path.parent != Path(".") else None
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")
    return entry


def append_provenance(action: str, status: str, details: dict | None = None) -> dict:
    entry = {
        "ts": utc_now(),
        "action_id": f"act_{uuid.uuid4().hex[:12]}",
        "action": action,
        "status": status,
        "details": details or {},
        "vision": "Full Autonomous Studio",
    }
    return append_jsonl(PROVENANCE_LOG, entry)


def read_last_jsonl(path: Path) -> dict | None:
    if not path.exists():
        return None
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return None
    return json.loads(lines[-1])


def read_all_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def require_header_token(env_name: str, header_name: str):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            expected = os.getenv(env_name, "")
            provided = request.headers.get(header_name, "")
            if not expected:
                return jsonify({
                    "status": "Blocked",
                    "reason": f"{env_name} is not configured. Set it in Render environment variables before using this endpoint.",
                }), 503
            if provided != expected:
                return jsonify({"status": "Unauthorized"}), 401
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def scout_loop() -> None:
    if not CONFIG["secrets"].get("deepseek"):
        append_provenance("HEARTBEAT_IDLE", "WAITING_FOR_SECRET", {"missing": "DEEPSEEK_API_KEY"})
        return

    append_provenance("HEARTBEAT_SCOUT", "SUCCESS", {
        "mode": "dry_run",
        "external_call": False,
        "money_gate": CONFIG["money_gate"],
    })


@app.route("/")
def home():
    return "Studio Agent Alpha: Active. /verify to check heartbeat. /admin for gated approvals."


@app.route("/verify")
def verify():
    last_entry = read_last_jsonl(PROVENANCE_LOG)
    if not last_entry:
        return jsonify({"status": "Idle", "msg": "No provenance entries yet."})
    status = "Heartbeat OK" if last_entry.get("action") == "HEARTBEAT_SCOUT" else "Idle"
    return jsonify({"status": status, "last_entry": last_entry})


@app.route("/setup", methods=["POST"])
@require_header_token("SETUP_TOKEN", "X-Setup-Token")
def setup():
    data = request.get_json(silent=True) or {}
    deepseek_key = data.get("deepseek_key", "")
    if not isinstance(deepseek_key, str) or not deepseek_key.strip():
        return jsonify({"status": "Error", "reason": "JSON body must include non-empty deepseek_key."}), 400

    CONFIG["secrets"]["deepseek"] = deepseek_key.strip()
    append_provenance("SECRET_UPDATED", "SUCCESS", {"secret": "deepseek", "stored_in_memory_only": True})
    return jsonify({"status": "Secret Updated"})


@app.route("/trigger-scout", methods=["POST"])
@require_header_token("ADMIN_TOKEN", "X-Admin-Token")
def trigger_scout():
    scout_loop()
    return jsonify({"status": "Triggered", "last_entry": read_last_jsonl(PROVENANCE_LOG)})


@app.route("/proposals", methods=["GET"])
@require_header_token("ADMIN_TOKEN", "X-Admin-Token")
def proposals():
    return jsonify({"status": "OK", "proposals": read_all_jsonl(PROPOSALS_LOG)})


@app.route("/propose", methods=["POST"])
@require_header_token("ADMIN_TOKEN", "X-Admin-Token")
def propose():
    if not CONFIG["money_gate"]:
        return jsonify({"status": "Blocked", "reason": "Money gate is disabled."}), 403

    data = request.get_json(silent=True) or {}
    proposal = {
        "proposal_id": f"prop_{uuid.uuid4().hex[:12]}",
        "ts": utc_now(),
        "summary": data.get("summary", "Manual approval proposal"),
        "estimated_cost": data.get("estimated_cost", "0.00"),
        "risk": data.get("risk", "low"),
        "dry_run_summary": data.get("dry_run_summary", "No external spend executed."),
        "state": "PENDING_APPROVAL",
    }
    append_jsonl(PROPOSALS_LOG, proposal)
    append_provenance("MONEY_GATE_PROPOSED", "PENDING_APPROVAL", {"proposal_id": proposal["proposal_id"]})
    return jsonify({"status": "Proposal Created", "proposal": proposal})


@app.route("/approve/<proposal_id>", methods=["POST"])
@require_header_token("ADMIN_TOKEN", "X-Admin-Token")
def approve(proposal_id: str):
    entry = append_provenance("MONEY_GATE_APPROVED", "APPROVED", {
        "proposal_id": proposal_id,
        "external_spend_executed": False,
    })
    return jsonify({"status": "Approved", "provenance": entry})


@app.route("/decline/<proposal_id>", methods=["POST"])
@require_header_token("ADMIN_TOKEN", "X-Admin-Token")
def decline(proposal_id: str):
    entry = append_provenance("MONEY_GATE_DECLINED", "DECLINED", {"proposal_id": proposal_id})
    return jsonify({"status": "Declined", "provenance": entry})


@app.route("/admin")
def admin():
    return """
<!doctype html>
<html>
<head><title>Studio Agent Alpha Admin</title></head>
<body>
  <h1>Studio Agent Alpha Admin</h1>
  <p>Money-gate only. No external spend executes from this page.</p>
  <label>Admin token <input id="token" type="password" /></label>
  <h2>Create Proposal</h2>
  <textarea id="summary" rows="4" cols="80">Dry-run approval test. No charge will execute.</textarea><br />
  <button onclick="createProposal()">Create Proposal</button>
  <button onclick="loadProposals()">Refresh Proposals</button>
  <pre id="out"></pre>
<script>
async function api(path, method='GET', body=null) {
  const headers = {'X-Admin-Token': document.getElementById('token').value};
  if (body) headers['Content-Type'] = 'application/json';
  const res = await fetch(path, {method, headers, body: body ? JSON.stringify(body) : null});
  const json = await res.json();
  document.getElementById('out').textContent = JSON.stringify(json, null, 2);
  return json;
}
async function createProposal() {
  await api('/propose', 'POST', {
    summary: document.getElementById('summary').value,
    estimated_cost: '0.00',
    risk: 'low',
    dry_run_summary: 'Acceptance-test proposal only. No external spend executed.'
  });
}
async function loadProposals() { await api('/proposals'); }
</script>
</body>
</html>
"""


scheduler = None
if BackgroundScheduler is not None:
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(func=scout_loop, trigger="interval", minutes=30, id="scout_loop", replace_existing=True)
    scheduler.start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
