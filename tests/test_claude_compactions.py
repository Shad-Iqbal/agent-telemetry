"""Compaction metadata must never become fabricated model usage."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dashboard as D
import parser as P


class ClaudeCompactionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="telemetry-compactions-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
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
            item.start()
            self.addCleanup(item.stop)

    def line(self, number, **values):
        return json.dumps({"uuid": str(uuid.uuid5(uuid.NAMESPACE_OID, str(number))),
                           "timestamp": "2026-10-10T12:00:00Z", **values}) + "\n"

    def boundary(self, number, trigger="manual", **values):
        return self.line(number, type="system", subtype="compact_boundary",
                         compactMetadata={"trigger": trigger, "preTokens": 558980,
                                          "postTokens": 16124, "durationMs": 93029}, **values)

    def parse(self, lines):
        agg = P._blank_agg("claude", str(self.root / "session.jsonl"))
        P.parse_claude(agg, lines)
        P._finalize_session(agg, "claude", agg["path"])
        return agg

    def usage_lines(self):
        def assistant(number, msgid, output, **values):
            return self.line(number, type="assistant", requestId="req-" + msgid,
                message={"id": msgid, "model": "claude-sonnet-5-5", "content": [
                    {"type": "tool_use", "id": "tool-" + str(number), "name": "Skill",
                     "input": {"skill": "fixture-skill"}}],
                    "usage": {"input_tokens": 11, "output_tokens": output,
                              "cache_read_input_tokens": 100, "cache_creation_input_tokens": 20,
                              "cache_creation": {"ephemeral_5m_input_tokens": 12,
                                                 "ephemeral_1h_input_tokens": 8},
                              "output_tokens_details": {"thinking_tokens": 2}}},
                attributionSkill="fixture-skill", **values)
        return [self.line(1, type="user", message={"content": "Explain this fixture"}),
                assistant(2, "a", 3), assistant(3, "a", 9), self.boundary(4),
                self.line(5, type="user", isCompactSummary=True,
                          message={"content": "PRIVATE SUMMARY MUST NOT ENTER EVENT METADATA"}),
                self.line(6, type="user", message={"content": "<command-name>/compact</command-name>"}),
                self.line(7, type="attachment", attachment={"type": "queued_command",
                    "commandMode": "prompt", "prompt": "A real steering prompt"}),
                assistant(8, "b", 4), self.boundary(9, "auto"),
                self.line(10, type="cost-state", totalCostUSD=999, modelUsage={}),
                self.line(11, type="assistant", message={"model": "<synthetic>", "usage": {}})]

    def test_manual_auto_replays_and_summaries_count_completions_once(self):
        lines = [self.boundary(1), self.boundary(2, "auto")]
        agg = self.parse(lines)
        agg["state"]["rd"] = {"new-read": [1]}
        P.parse_claude(agg, lines)
        self.assertEqual(len(agg["compactions"]), 2)
        self.assertIn("new-read", agg["state"]["rd"])
        self.assertEqual([e["trigger"] for e in agg["compactions"].values()], ["manual", "auto"])
        self.assertEqual(agg["records"], {})
        self.assertFalse(any(agg["totals"].values()))
        summary = self.line(3, type="user", isCompactSummary=True, message={"content": "private"})
        P.parse_claude(agg, [summary])
        self.assertEqual(len(agg["compactions"]), 2)
        self.assertEqual(agg["totals"]["user"], 0)

    def test_normal_usage_and_all_existing_aggregates_are_identical(self):
        lines = self.usage_lines()
        with patch.object(P, "_claude_compaction"):
            before = self.parse(lines)
        after = self.parse(lines)
        for field in ("records", "totals", "tools", "skills", "ctx", "hourly", "reads",
                      "used_ext", "state", "activity", "first_ts", "last_ts", "_active_last"):
            self.assertEqual(before.get(field), after.get(field), field)
        self.assertEqual(after["totals"]["in"], 22)
        self.assertEqual(after["totals"]["out"], 13)
        self.assertEqual(after["totals"]["cr"], 200)
        self.assertEqual(after["totals"]["cc"], 40)
        self.assertEqual(after["totals"]["asst"], 2)
        self.assertEqual(after["totals"]["user"], 2)
        self.assertEqual(after["totals"]["tools"], 3)
        self.assertNotIn("PRIVATE SUMMARY", json.dumps(after["compactions"]))
        D._state["files"] = {"fixture": before}
        old_payload, old_summary = D.build_payload(), D.build_today_summary()
        D._state["files"] = {"fixture": after}
        new_payload = D.build_payload()
        for field in ("records", "tools", "hourly", "activity", "ctx", "skills", "reads"):
            self.assertEqual(old_payload[field], new_payload[field], field)
        self.assertEqual(old_summary, D.build_today_summary())

    def test_unknown_metadata_and_zero_are_not_guessed(self):
        line = self.line(1, type="system", subtype="compact_boundary", compactMetadata={
            "trigger": [], "preTokens": True, "postTokens": "16", "durationMs": -1})
        agg = self.parse([line])
        e = next(iter(agg["compactions"].values()))
        self.assertEqual(e["trigger"], "unknown")
        self.assertIsNone(e["before"])
        self.assertIsNone(e["after"])
        self.assertIsNone(e["duration_ms"])
        zero = self.line(2, type="system", subtype="compact_boundary",
                         compactMetadata={"preTokens": 0, "postTokens": 0, "durationMs": 0})
        P.parse_claude(agg, [zero])
        e = list(agg["compactions"].values())[-1]
        self.assertEqual((e["before"], e["after"], e["duration_ms"]), (0, 0, 0))

    def test_idless_boundary_has_stable_identity_and_failed_command_is_not_completion(self):
        obj = json.loads(self.boundary(1)); obj.pop("uuid")
        agg = self.parse([json.dumps(obj)] * 2)
        self.assertEqual(len(agg["compactions"]), 1)
        failed = self.line(2, type="system", subtype="local_command", content="API error")
        command = self.line(3, type="attachment", attachment={"type": "queued_command",
                          "commandMode": "prompt", "prompt": "/compact"})
        P.parse_claude(agg, [failed, command])
        self.assertEqual(len(agg["compactions"]), 1)
        self.assertEqual(agg["totals"]["user"], 0)

    def test_inline_sidechain_is_not_parent_event_but_child_records_its_own(self):
        line = self.boundary(1, isSidechain=True)
        self.assertEqual(self.parse([line])["compactions"], {})
        path = self.root / "parent" / "subagents" / "agent-fixture.jsonl"
        path.parent.mkdir(parents=True); path.write_text(line)
        child = P.update_file(None, "claude", str(path), None, {})
        self.assertTrue(child["sessions"][0]["subagent"])
        self.assertEqual(len(child["compactions"]), 1)

    def test_incremental_partial_line_and_restart_match_full_parse(self):
        path = self.root / "session.jsonl"
        lines = self.usage_lines()
        path.write_text("".join(lines[:3]) + lines[3][:-1])
        agg = P.update_file(None, "claude", str(path), None, {})
        self.assertEqual(agg["compactions"], {})
        with path.open("a") as f: f.write("\n" + "".join(lines[4:]))
        agg = P.update_file(json.loads(json.dumps(agg)), "claude", str(path), None, {})
        full = P.update_file(None, "claude", str(path), None, {})
        self.assertEqual(agg, full)
        with path.open("a") as f: f.write("".join(lines))
        replayed = P.update_file(json.loads(json.dumps(agg)), "claude", str(path), None, {})
        self.assertEqual(replayed["records"], full["records"])
        self.assertEqual(replayed["compactions"], full["compactions"])

    def test_compaction_only_session_survives_payload_export_and_archival(self):
        agg = self.parse([self.boundary(1)])
        D._state["files"] = {"fixture": agg}
        payload = D.build_payload()
        self.assertEqual(payload["records"], [])
        self.assertEqual(payload["hourly"], [])
        self.assertEqual(len(payload["sessions"]), 1)
        session = payload["sessions"][0]
        self.assertEqual(session["days"], {})
        self.assertEqual((session["in"], session["out"], session["cost"]), (0, 0, 0))
        self.assertEqual(session["start"], session["compactions"][0]["timestamp"])
        exported = D._export_agg(agg)
        self.assertEqual(exported["compactions"], agg["compactions"])
        self.assertEqual(exported["sessions"][0]["compactions"], session["compactions"])
        agg["archived"] = True
        self.assertTrue(D.save_cache())
        D._state["files"] = {}
        D.load_cache()
        self.assertEqual(D._state["files"]["fixture"], agg)

    def test_failed_append_rolls_back_event_and_usage_and_retries_once(self):
        path = self.root / "session.jsonl"
        base = "".join(self.usage_lines()[:3]); path.write_text(base)
        previous = P.update_file(None, "claude", str(path), None, {})
        D._state["files"] = {str(path): previous}
        original = copy.deepcopy(previous)
        broken = self.line(99, type="assistant", message={"model": "claude-sonnet-5-5",
                                                        "usage": {"input_tokens": "bad"}})
        path.write_text(base + self.boundary(4) + broken)
        with patch.object(P, "discover", return_value=[("claude", str(path), None)]):
            with contextlib.redirect_stderr(io.StringIO()):
                D.refresh(); D.refresh()
            self.assertEqual(previous, original)
            path.write_text(base + self.boundary(4))
            D.refresh(); D.refresh()
        self.assertEqual(previous["totals"], original["totals"])
        self.assertEqual(len(previous["compactions"]), 1)
        self.assertEqual(previous["offset"], path.stat().st_size)

    def test_v53_backfill_failure_keeps_previous_usage_then_retries(self):
        path = self.root / "session.jsonl"; path.write_text("".join(self.usage_lines()))
        legacy = P.update_file(None, "claude", str(path), None, {})
        legacy.pop("compactions"); legacy["sessions"][0].pop("compactions")
        archived = copy.deepcopy(legacy); archived["archived"] = True
        other = P._blank_agg("codex", "gone-codex.jsonl"); other["archived"] = True
        files = {str(path): legacy, "archived": archived, "gone-codex.jsonl": other}
        Path(D.CACHE_PATH).write_text(json.dumps({"version": 53, "files": files}))
        with contextlib.redirect_stderr(io.StringIO()): D.load_cache()
        self.assertEqual(D._state["files"], files)
        previous = copy.deepcopy(D._state["files"][str(path)])
        with patch.object(P, "discover", return_value=[("claude", str(path), None)]):
            with patch.object(P, "parse_claude", side_effect=ValueError("fixture failure")), \
                    contextlib.redirect_stderr(io.StringIO()):
                D.refresh()
            self.assertEqual(D._state["files"][str(path)], previous)
            D.refresh()
        updated = D._state["files"][str(path)]
        self.assertEqual(updated["totals"], previous["totals"])
        self.assertEqual(len(updated["compactions"]), 2)
        self.assertEqual(D._state["files"]["archived"], archived)
        self.assertEqual(D._state["files"]["gone-codex.jsonl"], other)
        old_session = next(s for s in D.build_payload()["sessions"] if s.get("archived"))
        self.assertNotIn("compactions", old_session)

    def test_previous_peers_are_compatible_and_device_events_stay_separate(self):
        for version in (52, 53, 54, D.CACHE_VERSION): self.assertTrue(D._peer_cache_ok(version))
        for version in (True, "54", 51, D.CACHE_VERSION + 1): self.assertFalse(D._peer_cache_ok(version))
        agg = self.parse([self.boundary(1)])
        remote = copy.deepcopy(agg); remote["_device"] = "other-device"
        D._state["files"] = {"local": agg}
        with patch.object(D, "_peer_items", return_value=[("remote", remote)]):
            sessions = D.build_payload()["sessions"]
        self.assertEqual(len(sessions), 2)
        self.assertEqual({s["device"] for s in sessions}, {"fixture-device", "other-device"})
        self.assertTrue(all(len(s["compactions"]) == 1 for s in sessions))


if __name__ == "__main__":
    unittest.main()
