"""V1, V2 and mixed opencode stores must keep one copy of recorded usage."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dashboard as D
import parser as P

STAMP = 1791789401130
SESSION_COLUMNS = "id TEXT PRIMARY KEY, directory TEXT, title TEXT, agent TEXT, model TEXT, version TEXT, parent_id TEXT, time_created INTEGER, time_updated INTEGER"


class OpencodeV2Tests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="opencode-v2-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / "opencode.db"
        for item in [patch.dict(D._state, {"files": {}, "version": D.CACHE_VERSION}),
                     patch.dict(D._meta, D._meta.copy()), patch.dict(D._dirty, {"v": False}),
                     patch.dict(D._grew, {"v": False, "saved": 0}),
                     patch.dict(D._gen, D._gen.copy()), patch.dict(D._cache_error, {"v": None}),
                     patch.object(D, "CACHE_PATH", str(self.root / "cache.json")),
                     patch.object(P, "_copilot_project_map", return_value={}),
                     patch.object(D, "_peer_items", return_value=[]),
                     patch.object(D, "_local_id", return_value="fixture-device"),
                     patch.object(D, "_devices_meta", return_value=[]),
                     patch.object(D, "_context_files", return_value=[]),
                     patch.object(D, "_installed", return_value=[]),
                     patch.object(D, "_mcp_servers", return_value={})]:
            item.start(); self.addCleanup(item.stop)

    def store(self, legacy=False, v2=True, wal=False):
        c = sqlite3.connect(self.path)
        self.addCleanup(c.close)
        if wal:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA wal_autocheckpoint=0")
        if legacy:
            c.execute("CREATE TABLE session (" + SESSION_COLUMNS + ")")
            c.execute("CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT)")
            c.execute("CREATE TABLE part (message_id TEXT, data TEXT)")
        if v2:
            c.execute("CREATE TABLE session_v2 (" + SESSION_COLUMNS + ", fork_session_id TEXT)")
            c.execute("CREATE TABLE session_message (id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT, type TEXT, seq INTEGER)")
        return c

    def session(self, c, sid="same-session", v2=True, title="V2 fixture", fork=None, created=STAMP):
        table = "session_v2" if v2 else "session"
        values = [sid, "/mock/project", title, "build", '{"id":"glm-5.3","providerID":"fixture"}',
                  "fixture", None, created, created + 60000]
        if v2: values.append(fork)
        c.execute("INSERT INTO " + table + " VALUES (" + ",".join("?" for _ in values) + ")", values)

    def message(self, c, number, role, sid="same-session", v2=True, created=None, **extra):
        created = created if created is not None else STAMP + number * 1000
        d = {"time": {"created": created}}
        if role == "user":
            d["text"] = "Fixture prompt"
        elif role == "assistant":
            d.update({"model": {"id": "glm-5.3", "providerID": "fixture"}, "cost": .1,
                      "tokens": {"input": 10, "output": 5, "reasoning": 2, "cache": {"read": 100, "write": 20}},
                      "content": [{"type": "tool", "name": "bash", "state": {"status": "completed"}}]})
        d.update(extra)
        mid = "msg-" + sid + "-" + str(number)
        if v2:
            c.execute("INSERT INTO session_message VALUES (?,?,?,?,?,?)", (mid, sid, created, json.dumps(d), role, number))
        else:
            d["role"] = role
            if role == "assistant":
                model = d.pop("model")
                d.update(modelID=model["id"], providerID=model["providerID"])
                c.execute("INSERT INTO part VALUES (?,?)", (mid, '{"type":"tool","tool":"bash"}'))
            c.execute("INSERT INTO message VALUES (?,?,?,?)", (mid, sid, created, json.dumps(d)))
        return mid

    def parse(self, previous=None):
        return P.update_file(previous, "opencode", str(self.path), "opencode", {})

    def test_v2_only_counts_all_prompts_usage_and_embedded_tools(self):
        c = self.store(); self.session(c)
        for n in range(11): self.message(c, n, "user")
        self.message(c, 11, "assistant"); self.message(c, 12, "assistant")
        self.message(c, 13, "idle"); self.message(c, 14, "system"); self.message(c, 15, "synthetic")
        c.commit()
        a = self.parse(); s = a["sessions"][0]
        self.assertEqual(s["user"], 11); self.assertEqual(s["asst"], 2)
        self.assertEqual((s["in"], s["out"], s["cr"], s["cc"]), (20, 10, 200, 40))
        self.assertEqual(a["totals"]["reason"], 4)
        self.assertEqual(s["tools"], 2); self.assertAlmostEqual(s["cost"], .2)
        self.assertEqual(s["model"], "GLM 5.3")
        D._state["files"] = {str(self.path): a}
        payload = D.build_payload()
        self.assertEqual(payload["sessions"][0]["user"], 11)
        self.assertAlmostEqual(payload["sessions"][0]["cost"], .2)
        self.assertEqual(sum(r["user"] for r in payload["records"]), 11)
        self.assertEqual(sum(r["in"] + r["out"] + r["cr"] + r["cc"] for r in payload["records"]), 270)
        self.assertEqual(sum(t["count"] for t in payload["tools"]), 2)
        self.assertEqual(len(D._export_agg(a)["opencode_ids"]), 2)

    def test_mixed_store_uses_v2_copy_and_keeps_v1_only_sessions(self):
        c = self.store(legacy=True)
        self.session(c, v2=False, title="Stale V1 copy"); self.session(c)
        for v2 in (False, True):
            self.message(c, 1, "user", v2=v2); self.message(c, 2, "assistant", v2=v2)
        self.message(c, 3, "user"); self.message(c, 4, "assistant")
        self.session(c, sid="legacy-only", v2=False, title="Legacy only")
        self.message(c, 1, "user", sid="legacy-only", v2=False)
        self.message(c, 2, "assistant", sid="legacy-only", v2=False)
        c.commit(); a = self.parse()
        by_title = {s["title"]: s for s in a["sessions"]}
        self.assertEqual(set(by_title), {"V2 fixture", "Legacy only"})
        self.assertEqual(by_title["V2 fixture"]["user"], 2)
        self.assertEqual(by_title["V2 fixture"]["asst"], 2)
        self.assertEqual(by_title["Legacy only"]["user"], 1)
        self.assertEqual(a["totals"]["user"], 3); self.assertEqual(a["totals"]["asst"], 3)
        self.assertEqual(a["totals"]["tools"], 3)

    def test_message_dates_and_models_are_retained_for_range_filters(self):
        c = self.store(); self.session(c)
        self.message(c, 1, "user", created=STAMP - 86400000)
        self.message(c, 2, "assistant", created=STAMP - 86400000 + 1000)
        self.message(c, 3, "user")
        self.message(c, 4, "assistant", model={"id": "gemini-4-argon", "providerID": "google"})
        c.commit(); a = self.parse()
        s = a["sessions"][0]
        models = {k.split("\t")[1] for k in s["records"]}
        dates = {k.split("\t")[0] for k in s["records"]}
        self.assertEqual(models, {"(user)", "GLM 5.3", "Gemini 4 Argon"})
        self.assertEqual(len(dates), 2)

    def test_legacy_only_schema_retains_original_accounting(self):
        c = self.store(legacy=True, v2=False); self.session(c, v2=False)
        self.message(c, 1, "user", v2=False); self.message(c, 2, "assistant", v2=False)
        c.commit(); a = self.parse()
        self.assertEqual(a["opencode_schema"], 1)
        self.assertEqual((a["totals"]["user"], a["totals"]["asst"], a["totals"]["in"], a["totals"]["cr"]), (1, 1, 10, 100))
        self.assertEqual(a["totals"]["tools"], 1)
        self.assertIs(self.parse(a), a)

    def test_empty_v2_migration_stub_does_not_discard_legacy_history(self):
        c = self.store(legacy=True); self.session(c, v2=False); self.session(c)
        self.message(c, 1, "user", v2=False); self.message(c, 2, "assistant", v2=False)
        self.message(c, 3, "system")
        c.commit(); a = self.parse()
        self.assertEqual(a["totals"]["user"], 1); self.assertEqual(a["totals"]["asst"], 1)

    def test_invalid_v2_row_preserves_previous_ledger_on_failed_refresh(self):
        c = self.store(); self.session(c); self.message(c, 1, "user"); c.commit()
        previous = self.parse(); original = copy.deepcopy(previous)
        c.execute("UPDATE session_message SET data='invalid json'"); c.commit()
        D._state["files"] = {str(self.path): previous}
        with patch.object(P, "discover", return_value=[("opencode", str(self.path), "opencode")]), contextlib.redirect_stderr(io.StringIO()):
            D.refresh(); D.refresh()
        self.assertEqual(previous, original)
        c.execute("UPDATE session_message SET data=?", (json.dumps({"text": "fixture", "time": {"created": STAMP}}),)); c.commit()
        with patch.object(P, "discover", return_value=[("opencode", str(self.path), "opencode")]): D.refresh()
        self.assertEqual(D._state["files"][str(self.path)]["totals"]["user"], 1)

    def test_fork_copy_is_excluded_even_without_its_parent(self):
        c = self.store(); self.session(c, fork="deleted-parent", created=STAMP + 10000)
        self.message(c, 1, "user", created=STAMP); self.message(c, 2, "assistant", created=STAMP + 1000)
        self.message(c, 3, "user", created=STAMP + 10000); self.message(c, 4, "assistant", created=STAMP + 11000)
        c.commit(); a = self.parse()
        self.assertEqual(a["totals"]["user"], 1); self.assertEqual(a["totals"]["asst"], 1)
        self.assertEqual(a["totals"]["in"], 10)
        self.assertEqual(len(a["opencode_ids"]), 1)

    def test_wal_refresh_reads_new_messages_without_checkpoint(self):
        c = self.store(wal=True); self.session(c); self.message(c, 1, "user"); c.commit()
        a = self.parse()
        self.message(c, 2, "assistant"); c.commit()
        updated = self.parse(a)
        self.assertEqual(updated["totals"]["asst"], 1)
        self.assertEqual(updated["totals"]["user"], 1)
        self.assertIs(self.parse(updated), updated)

    def test_unchanged_old_cache_reparses_once_and_failure_preserves_it(self):
        c = self.store(); self.session(c); self.message(c, 1, "user"); c.commit()
        a = self.parse(); a.pop("opencode_schema"); original = copy.deepcopy(a)
        with patch.object(P, "parse_opencode_db", side_effect=ValueError("fixture failure")):
            with self.assertRaises(ValueError): self.parse(a)
        self.assertEqual(a, original)
        updated = self.parse(a)
        self.assertEqual(updated["opencode_schema"], 2)
        self.assertEqual(updated["totals"], original["totals"])
        self.assertIs(self.parse(updated), updated)

    def test_existing_legacy_json_copy_is_not_added_to_migrated_db_usage(self):
        c = self.store(); self.session(c); mid = self.message(c, 2, "assistant"); c.commit()
        a = self.parse()
        legacy = P._blank_agg("opencode", "legacy-directory")
        legacy["opencode_messages"] = [{"id": ["same-session", mid], "usage": {"in": 10}}]
        self.assertEqual(D._one_per_conversation([(str(self.path), a), ("legacy", legacy)]), [a])


if __name__ == "__main__":
    unittest.main()
