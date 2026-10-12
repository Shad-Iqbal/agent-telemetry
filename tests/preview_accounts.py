"""Local web visual fixture. Invented accounts/figures; no real logs or network.

Run: python tests/preview_accounts.py --port 8878
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import accounts as A
import dashboard as D
import native as N
import parser as P


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--port", type=int, default=8878)
    args = cli.parse_args()
    with tempfile.TemporaryDirectory(prefix="telemetry-quota-preview-") as directory, ExitStack() as stack:
        root = Path(directory)
        now = time.time(); stamp = datetime.fromtimestamp(now, timezone.utc).isoformat()
        path = root / "fixture-profile" / "sessions" / "rollout-fixture.jsonl"
        path.parent.mkdir(parents=True)
        quota = {"limit_id": "codex", "plan_type": "plus", "primary": {"used_percent": 11,
            "window_minutes": 300, "resets_at": now + 13620}, "secondary": {"used_percent": 11,
            "window_minutes": 10080, "resets_at": now + 471600}}
        lines = [("session_meta", {"id": "fixture-thread", "creator_account_id": "fixture-creator", "cwd": str(root / "demo-project")}),
                 ("turn_context", {"model": "gpt-6.1-sol"}),
                 ("token_usage_record", {"usage": {"input_tokens": 50000, "output_tokens": 8000}}),
                 ("event_msg", {"type": "token_count", "rate_limits": quota})]
        path.write_text("".join(json.dumps({"type": kind, "payload": payload, "timestamp": stamp}) + "\n" for kind, payload in lines))
        aggregate = P.update_file(None, "codex", str(path), None, {})
        for item in [patch.object(N, "support_dir", return_value=root / "private"),
                     patch.object(D, "_local_id", return_value="fixture-device"),
                     patch.object(D, "DEVICE", {"name": "Quota preview", "os": "Fixture", "host": "fixture"}),
                     patch.object(D, "_devices_meta", return_value=[{"id": "fixture-device", "name": "Quota preview", "os": "Fixture"}]),
                     patch.object(D, "_context_files", return_value=[]), patch.object(D, "_installed", return_value=[]),
                     patch.object(D, "_mcp_servers", return_value={}), patch.object(D, "_codex_config", return_value={"effort": None}),
                     patch.object(D, "_peer_items", return_value=[]), patch.object(P, "discover", return_value=[]),
                     patch.object(D, "VERSION", {"git": False, "describe": "Mock quota preview"}),
                     patch.object(A, "_profile", side_effect=lambda s: "Fixture " + s + " CLI profile"),
                     patch.object(A, "_auth_signature", return_value=("fixture-signature",)),
                     patch.object(A, "_codex_read", return_value=({"type": "chatgpt", "email": "demo@example.invalid", "planType": "plus"},
                         {"rateLimits": {"limitId": "codex", "primary": {"usedPercent": 11, "windowDurationMins": 300, "resetsAt": now + 13620},
                             "secondary": {"usedPercent": 11, "windowDurationMins": 10080, "resetsAt": now + 471600}}})),
                     patch.object(A, "_claude_read", return_value={"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "max", "email": "claude@example.invalid"})]:
            stack.enter_context(item)
        D._state["files"] = {str(path): aggregate}
        D._meta.update(files=1, last_refresh=now, building=False)
        A._live.clear()
        A.refresh_account("codex", True)
        A.refresh_account("claude", True)
        A.capture_claude({"rate_limits": {"five_hour": {"used_percentage": 25, "resets_at": now + 5000},
                                        "seven_day": {"used_percentage": 70, "resets_at": now + 86400}}})
        server = D.Server(("127.0.0.1", args.port), D.Handler)
        D.BIND.update(host="127.0.0.1", port=server.server_port)
        print(f"Mock preview: http://127.0.0.1:{server.server_port}/?theme=dark", flush=True)
        try: server.serve_forever()
        finally: server.server_close()


if __name__ == "__main__": main()
