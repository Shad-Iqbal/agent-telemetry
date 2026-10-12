"""Source renames require a reviewed warning and preserve billed/event history."""
import contextlib
from contextlib import closing
import copy
import http.client
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dashboard as D
import native as N
import parser as P
import session_names as SN


class SessionNameTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="telemetry-names-")
        self.addCleanup(temp.cleanup); self.root = Path(temp.name)
        self.sid = str(uuid.uuid4()); self.path = self.root / (self.sid + ".jsonl")
        lines = [{"type": "custom-title", "sessionId": self.sid, "customTitle": "Original fixture"},
                 {"type": "user", "uuid": "fixture-user", "timestamp": "2026-10-12T12:00:00Z", "message": {"content": "Fixture request"}},
                 {"type": "assistant", "uuid": "fixture-assistant", "requestId": "fixture-request",
                  "timestamp": "2026-10-12T12:00:01Z", "message": {"id": "fixture-message", "model": "claude-sonnet-5-5",
                  "content": [{"type": "tool_use", "name": "Bash", "id": "fixture-tool", "input": {"command": "echo fixture"}}],
                  "usage": {"input_tokens": 100, "output_tokens": 10, "cache_creation_input_tokens": 20, "cache_read_input_tokens": 50}}},
                 {"type": "system", "subtype": "compact_boundary", "uuid": "fixture-compact", "timestamp": "2026-10-12T12:00:02Z",
                  "compactMetadata": {"trigger": "manual", "preTokens": 200, "postTokens": 100}}]
        self.path.write_text("".join(json.dumps(line) + "\n" for line in lines))
        self.agg = P.update_file(None, "claude", str(self.path), None, {})
        for item in [patch.object(N, "support_dir", return_value=self.root / "preferences"),
                     patch.dict(SN._plans, {}, clear=True),
                     patch.dict(D._state, {"files": {str(self.path): self.agg}, "version": D.CACHE_VERSION}),
                     patch.dict(D._dirty, {"v": False}), patch.dict(D._gen, D._gen.copy()),
                     patch.object(D, "CACHE_PATH", str(self.root / "ledger.json")),
                     patch.object(D, "_sync_manual", 0),
                     patch.object(P, "discover", return_value=[("claude", str(self.path), None)]),
                     patch.object(D, "_peer_items", return_value=[]),
                     patch.object(D, "_local_id", return_value="fixture-device"),
                     patch.object(D, "_devices_meta", return_value=[]),
                     patch.object(D, "_context_files", return_value=[]),
                     patch.object(D, "_installed", return_value=[]),
                     patch.object(D, "_mcp_servers", return_value={})]:
            item.start(); self.addCleanup(item.stop)
        self.body = {"device": "fixture-device", "source": "claude", "id": self.sid}

    def preview(self, name="New fixture"):
        return D.set_session_name({**self.body, "action": "preview", "name": name})

    def commit(self, preview, **extra):
        return D.set_session_name({**self.body, "action": "rename", "ticket": preview["ticket"], "confirmed": True, **extra})

    def test_preview_cancel_and_missing_confirmation_do_not_write_source_or_ledger(self):
        before, raw = copy.deepcopy(self.agg), self.path.read_bytes()
        preview = self.preview()
        self.assertEqual(preview["current_name"], "Original fixture")
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertEqual(self.agg, before)
        with self.assertRaises(ValueError): self.commit(preview, confirmed=False)
        with self.assertRaises(ValueError): self.commit({"ticket": "invented"})
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertFalse((N.support_dir() / "session-title-backups").exists())

    def test_claude_appends_native_title_only_preserving_all_usage_activity_and_compactions(self):
        before, raw = copy.deepcopy(self.agg), self.path.read_bytes()
        result = self.commit(self.preview("My <fixture> session"))
        self.assertEqual(self.path.read_bytes()[:len(raw)], raw)
        line = json.loads(self.path.read_bytes()[len(raw):])
        self.assertEqual(line, {"type": "custom-title", "customTitle": "My <fixture> session", "sessionId": self.sid})
        updated = D._state["files"][str(self.path)]
        for key in ("totals", "records", "hourly", "tools", "skills", "compactions", "ctx"):
            self.assertEqual(updated[key], before[key], key)
        self.assertEqual(P.activity_of(updated), P.activity_of(before))
        self.assertEqual(updated["sessions"][0]["title"], result["name"])
        backup = Path(result["backup"])
        self.assertEqual(json.loads(backup.read_text())["snapshot"]["title"], "Original fixture")
        if sys.platform != "win32": self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError): self.commit({"ticket": next(iter(SN._plans), "consumed")})

    def test_changed_or_incomplete_transcript_and_backup_failure_refuse_writes(self):
        preview = self.preview()
        with self.path.open("a") as file: file.write(json.dumps({"type": "custom-title", "customTitle": "Changed elsewhere", "sessionId": self.sid}) + "\n")
        current = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "changed"): self.commit(preview)
        self.assertEqual(self.path.read_bytes(), current)
        with self.path.open("a") as file: file.write('{"unfinished":')
        with self.assertRaisesRegex(ValueError, "still being written"): self.preview()
        self.path.write_bytes(current)
        preview = self.preview()
        with patch.object(SN, "_backup", side_effect=OSError("fixture disk full")):
            with self.assertRaises(OSError): self.commit(preview)
        self.assertEqual(self.path.read_bytes(), current)

    def test_unknown_remote_imported_and_invalid_names_cannot_edit_a_source(self):
        raw = self.path.read_bytes()
        for name in ("", "  ", "a\nb", "x" * 91, "\ud800", True, 42, []):
            with self.subTest(name=repr(name)), self.assertRaises(ValueError): self.preview(name)
        for identity in ({"id": "unknown"}, {"device": "peer"}, {"source": "unknown"}):
            with self.assertRaises(ValueError): D.set_session_name({**self.body, **identity, "action": "preview", "name": "Wrong"})
        with patch.object(P, "discover", return_value=[]):
            with self.assertRaises(ValueError): self.preview()
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertFalse(SN.availability("claude", str(self.path), remote=True)[0])
        self.assertFalse(SN.availability("cursor", str(self.path))[0])

    def test_partial_append_preserves_existing_and_concurrently_appended_records(self):
        raw = self.path.read_bytes()
        original_write = SN.os.write
        appended = b'{"type":"user","uuid":"later-user","timestamp":"2026-10-12T12:00:03Z","message":{"content":"Later fixture request"}}\n'
        for concurrent in (False, True):
            with self.subTest(concurrent=concurrent):
                self.path.write_bytes(raw)
                preview = self.preview()
                first = [True]
                def short_write(fd, data):
                    if not first[0]: return original_write(fd, data)
                    first[0] = False
                    count = original_write(fd, data[:12])
                    if concurrent:
                        with self.path.open("ab") as file: file.write(appended)
                    return count
                with patch.object(SN.os, "write", side_effect=short_write):
                    with self.assertRaisesRegex(OSError, "incomplete"): self.commit(preview)
                after = self.path.read_bytes()
                self.assertEqual(after[:len(raw)], raw)
                if concurrent:
                    self.assertTrue(after.endswith(appended))
                    updated = P.update_file(None, "claude", str(self.path), None, {})
                    self.assertEqual(updated["totals"]["user"], 2)
                else: self.assertFalse(after[len(raw):].strip())

    def test_visible_id_collision_cannot_rename_the_wrong_conversation(self):
        second_id = self.sid[:8] + str(uuid.uuid4())[8:]
        second_path = self.root / (second_id + ".jsonl")
        second_path.write_text(self.path.read_text().replace(self.sid, second_id))
        second = P.update_file(None, "claude", str(second_path), None, {})
        self.assertEqual(second["sessions"][0]["id"], self.agg["sessions"][0]["id"])
        D._state["files"][str(second_path)] = second
        with patch.object(P, "discover", return_value=[("claude", str(self.path), None), ("claude", str(second_path), None)]):
            with self.assertRaises(ValueError):
                D.set_session_name({**self.body, "id": self.sid[:8], "action": "preview", "name": "Wrong"})
            body = {**self.body, "id": second_id}
            preview = D.set_session_name({**body, "action": "preview", "name": "Second only"})
            D.set_session_name({**body, "action": "rename", "ticket": preview["ticket"], "confirmed": True})
        self.assertEqual(self.agg["sessions"][0]["title"], "Original fixture")
        self.assertEqual(D._state["files"][str(second_path)]["sessions"][0]["title"], "Second only")

    def database(self):
        path = self.root / "opencode.db"
        with closing(sqlite3.connect(path)) as c, c:
            for table in ("session", "session_v2"):
                c.execute("CREATE TABLE " + table + " (id TEXT PRIMARY KEY,title TEXT,tokens INTEGER,time_updated INTEGER)")
                c.execute("INSERT INTO " + table + " VALUES (?,?,123,456)", (self.sid, "Original database title"))
            c.execute("CREATE TABLE message (id TEXT PRIMARY KEY,data TEXT)")
            c.execute("INSERT INTO message VALUES ('fixture','immutable usage')")
        return path

    def test_opencode_transaction_changes_only_titles_in_both_schemas(self):
        path = self.database()
        preview = SN.prepare("fixture-device", "opencode", str(path), self.sid, "Renamed", "Original database title")
        SN.commit(preview["ticket"], "fixture-device", "opencode", str(path), self.sid, True)
        with closing(sqlite3.connect(path)) as c, c:
            for table in ("session", "session_v2"):
                self.assertEqual(c.execute("SELECT title,tokens,time_updated FROM " + table).fetchone(), ("Renamed", 123, 456))
            self.assertEqual(c.execute("SELECT * FROM message").fetchall(), [("fixture", "immutable usage")])
        preview = SN.prepare("fixture-device", "opencode", str(path), self.sid, "Again", "Renamed")
        with closing(sqlite3.connect(path)) as c, c: c.execute("UPDATE session_v2 SET title='Someone else'")
        with self.assertRaisesRegex(ValueError, "changed"):
            SN.commit(preview["ticket"], "fixture-device", "opencode", str(path), self.sid, True)
        with closing(sqlite3.connect(path)) as c, c:
            self.assertEqual(c.execute("SELECT title FROM session").fetchone()[0], "Renamed")
            c.execute("CREATE TRIGGER unexpected AFTER UPDATE ON session BEGIN DELETE FROM message; END")
        with self.assertRaisesRegex(ValueError, "triggers"):
            SN.prepare("fixture-device", "opencode", str(path), self.sid, "Wrong", "Renamed")

    def test_codex_uses_only_read_and_name_api_without_starting_a_thread_or_turn(self):
        path = self.root / "codex-profile" / "sessions" / "codex.jsonl"
        path.parent.mkdir(parents=True); path.write_text('original rollout\n')
        calls = []
        def rpc(method, params, **kwargs):
            calls.append((method, params))
            self.assertEqual(kwargs["home"], str(path.parent.parent.resolve()))
            return {"thread": {"name": "Original Codex"}} if method == "thread/read" else {}
        with patch.object(SN.shutil, "which", return_value="fixture-codex"), patch.object(SN, "_codex_rpc", side_effect=rpc):
            preview = SN.prepare("fixture-device", "codex", str(path), self.sid, "New Codex", "Original Codex")
            SN.commit(preview["ticket"], "fixture-device", "codex", str(path), self.sid, True)
        self.assertEqual([m for m, _ in calls], ["thread/read", "thread/read", "thread/name/set"])
        self.assertTrue(all(not p.get("includeTurns") for m, p in calls if m == "thread/read"))
        self.assertEqual(path.read_text(), 'original rollout\n')

    @unittest.skipUnless(SN.shutil.which("codex"), "Optional native Codex CLI is not installed")
    def test_actual_codex_api_isolated_profile_updates_native_index_without_rewriting_rollout(self):
        home = self.root / "isolated-codex"
        folder = home / "sessions" / "2026" / "10" / "12"; folder.mkdir(parents=True)
        sid = str(uuid.uuid4()); stamp = "2026-10-12T12:00:00Z"
        path = folder / ("rollout-2026-10-12T12-00-00-" + sid + ".jsonl")
        path.write_text(json.dumps({"timestamp": stamp, "type": "session_meta", "payload": {
            "id": sid, "timestamp": stamp, "cwd": str(self.root), "originator": "codex_cli_rs",
            "cli_version": "0.151.0", "source": "cli", "model_provider": "openai"}}) + "\n")
        original = path.read_bytes()
        wrong_home = self.root / "wrong-profile"
        with patch.dict(SN.os.environ, {"CODEX_HOME": str(wrong_home)}):
            preview = SN.prepare("fixture-device", "codex", str(path), sid, "Native fixture rename", "Fixture")
            SN.commit(preview["ticket"], "fixture-device", "codex", str(path), sid, True)
            actual = SN._codex_rpc("thread/read", {"threadId": sid, "includeTurns": False}, home=str(home))
        self.assertEqual(actual["thread"]["name"], "Native fixture rename")
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(wrong_home.exists())
        record = json.loads((home / "session_index.jsonl").read_text().splitlines()[-1])
        self.assertEqual((record["id"], record["thread_name"]), (sid, "Native fixture rename"))

    def test_http_warning_gate_requires_json_same_origin_and_one_use_ticket(self):
        server = D.Server(("127.0.0.1", 0), D.Handler); self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start(); self.addCleanup(server.shutdown)
        origin = "http://127.0.0.1:" + str(server.server_port)
        def post(body, headers):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            connection.request("POST", "/api/session-name", json.dumps(body), headers)
            response = connection.getresponse(); status = response.status; data = json.loads(response.read()); connection.close()
            return status, data
        body = {**self.body, "action": "preview", "name": "HTTP title"}; raw = self.path.read_bytes()
        with patch.dict(D.BIND, {"host": "127.0.0.1", "port": server.server_port}):
            self.assertEqual(post(body, {"Content-Type": "text/plain"})[0], 403)
            self.assertEqual(post(body, {"Content-Type": "application/json", "Origin": "https://example.invalid"})[0], 403)
            headers = {"Content-Type": "application/json", "Origin": origin}
            status, preview = post(body, headers); self.assertEqual(status, 200)
            commit = {**self.body, "action": "rename", "ticket": preview["ticket"]}
            self.assertEqual(post(commit, headers)[0], 400)
            self.assertEqual(self.path.read_bytes(), raw)
            self.assertEqual(post({**commit, "confirmed": True}, headers)[0], 200)
            self.assertEqual(post({**commit, "confirmed": True}, headers)[0], 400)


if __name__ == "__main__": unittest.main()
