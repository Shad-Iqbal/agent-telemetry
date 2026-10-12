"""Completed Codex checkpoints are metadata, never another usage source."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dashboard as D
import parser as P


class CodexCompactionTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix="codex-compactions-")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        patches = [patch.dict(D._state, {"files": {}, "version": D.CACHE_VERSION}),
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
                   patch.object(D, "_mcp_servers", return_value={})]
        for item in patches:
            item.start(); self.addCleanup(item.stop)

    def line(self, kind, payload, timestamp="2026-10-10T12:00:00Z", **extra):
        return json.dumps({"type": kind, "timestamp": timestamp, "payload": payload, **extra}) + "\n"

    def checkpoint(self, uid="compact-one", **values):
        return self.line("compacted", {"compaction_response_id": uid, "message": "PRIVATE SUMMARY",
            "replacement_history": [{"type": "function_call_output", "output": "PRIVATE TOOL OUTPUT"},
                                    {"type": "reasoning", "summary": []}], **values})

    def parse(self, lines):
        agg = P._blank_agg("codex", str(self.root / "session.jsonl"))
        P.parse_codex(agg, lines)
        P._finalize_session(agg, "codex", agg["path"])
        return agg

    def usage_lines(self):
        usage = {"input_tokens": 100, "cached_input_tokens": 30, "cache_write_input_tokens": 10,
                 "output_tokens": 12, "reasoning_output_tokens": 3}
        return [self.line("session_meta", {"id": "fixture-thread", "cwd": "/fixture/project"}),
                self.line("turn_context", {"model": "gpt-6.1-sol"}),
                self.line("event_msg", {"type": "user_message", "message": "Explain fixture"}),
                self.line("response_item", {"type": "function_call", "name": "exec_command",
                                           "arguments": '{"cmd":"ls"}'}),
                self.line("token_usage_record", {"response_id": "compact-one", "usage": usage}),
                self.checkpoint(latest_token_usage_record={"response_id": "compact-one", "usage": usage}),
                self.line("event_msg", {"type": "context_compacted"}),
                self.line("event_msg", {"type": "item_completed", "item": {"type": "ContextCompaction", "id": "notice"}}),
                self.line("event_msg", {"type": "token_count", "info": {"last_token_usage": usage}}),
                self.line("event_msg", {"type": "agent_message", "message": "Done"})]

    def test_checkpoint_with_copied_outputs_counts_once_and_never_imports_history(self):
        lines = self.usage_lines()
        agg = self.parse(lines)
        with patch.object(P, "_codex_compaction"):
            without_events = self.parse(lines)
        for key in set(agg) - {"compactions", "sessions"}:
            self.assertEqual(agg[key], without_events[key], key)
        self.assertEqual(agg["totals"], {**without_events["totals"]})
        self.assertEqual(agg["totals"]["req"], 1)
        self.assertEqual(agg["totals"]["in"], 60)
        self.assertEqual(len(agg["compactions"]), 1)
        event = agg["compactions"]["response:compact-one"]
        self.assertEqual(event["trigger"], "unknown")
        for field in ("before", "after", "duration_ms"): self.assertIsNone(event[field])
        self.assertNotIn("PRIVATE", json.dumps(agg["compactions"]))
        P.parse_codex(agg, [lines[5], lines[6], lines[7]])
        self.assertEqual(len(agg["compactions"]), 1)
        self.assertEqual(agg["totals"], without_events["totals"])

    def test_response_window_and_timestamp_keys_deduplicate_replays(self):
        window = self.checkpoint(None, window_id="window-one")
        plain = self.line("compacted", {"message": "old checkpoint"})
        same_time = self.line("compacted", {}, "2026-10-10T18:00:00+06:00")
        later = self.line("compacted", {}, "2026-10-11T12:00:00Z")
        agg = self.parse([self.checkpoint(), window, plain, same_time, later])
        self.assertEqual(len(agg["compactions"]), 4)
        replay = self.line("compacted", {"compaction_response_id": "compact-one"}, "2026-10-12T12:00:00Z")
        P.parse_codex(agg, [window, plain, replay])
        self.assertEqual(len(agg["compactions"]), 4)
        self.assertEqual(agg["compactions"]["response:compact-one"]["date"], P._buckets(P._from_iso("2026-10-10T12:00:00Z"))[0])

    def test_no_inferred_fields_or_failed_attempt_events(self):
        lines = [self.line("event_msg", {"type": "item_started", "item": {"type": "ContextCompaction"}}),
                 self.line("event_msg", {"type": "error", "message": "Compaction failed"}),
                 self.line("compacted", {}, "invalid timestamp"),
                 self.line("compacted", ["malformed payload"])]
        self.assertEqual(self.parse(lines)["compactions"], {})
        agg = self.parse([self.checkpoint(compaction_response_id=False, window_id=42, trigger="manual",
                                        preTokens=100, postTokens=20, durationMs=500)])
        event = next(iter(agg["compactions"].values()))
        self.assertTrue(event["id"].startswith("at:"))
        self.assertEqual(event["trigger"], "unknown")
        self.assertIsNone(event["before"])
        self.assertIsNone(event["after"])
        self.assertIsNone(event["duration_ms"])

    def test_nested_compacted_string_does_not_change_existing_skip_behavior(self):
        lines = [self.line("response_item", {"type": "function_call_output", "output": {"type": "compacted"}}),
                 self.line("token_usage_record", {"usage": {"input_tokens": 100},
                     "copied": [{"type": "function_call_output"}, {"type": "compacted"}]}),
                 json.dumps([{"type": "function_call_output"}, {"type": "compacted"}]) + "\n"]
        agg = self.parse(lines)
        self.assertEqual(agg["compactions"], {})
        self.assertEqual(agg["totals"]["in"], 0)

    def test_forked_history_is_excluded_and_child_records_its_own_checkpoint(self):
        lines = [self.line("session_meta", {"id": "child", "forked_from_id": "parent", "thread_source": "subagent"}),
                 self.line("compacted", {"compaction_response_id": "inherited"}, "2026-10-10T12:00:00.100Z"),
                 self.line("turn_context", {"model": "gpt-6.1-sol"}, "2026-10-10T12:00:00.200Z"),
                 self.line("compacted", {"window_id": "own-window"}, "2026-10-10T12:00:04Z")]
        agg = self.parse(lines)
        self.assertTrue(agg["subagent"])
        self.assertEqual(list(agg["compactions"]), ["window:own-window"])
        self.assertEqual(agg["totals"]["req"], 0)

    def test_formerly_skipped_checkpoint_cannot_extend_usage_replay_clock(self):
        lines = [self.line("session_meta", {"forked_from_id": "parent"}),
                 self.line("compacted", {"window_id": "inherited", "replacement_history": [
                    {"type": "function_call_output"}]}, "2026-10-10T12:00:00.900Z"),
                 self.line("turn_context", {"model": "gpt-6.1-sol"}, "2026-10-10T12:00:01.500Z"),
                 self.line("token_usage_record", {"usage": {"input_tokens": 100}}, "2026-10-10T12:00:01.600Z")]
        agg = self.parse(lines)
        self.assertEqual(agg["totals"]["in"], 100)
        self.assertEqual(agg["compactions"], {})

    def test_incremental_restart_partial_line_and_replay_match_full_parse(self):
        path = self.root / "session.jsonl"
        path.write_text("".join(self.usage_lines()))
        initial = P.update_file(None, "codex", str(path), None, {})
        line = self.checkpoint("compact-two")
        with path.open("a") as f: f.write(line[:-1])
        partial = P.update_file(copy.deepcopy(initial), "codex", str(path), None, {})
        self.assertEqual(partial["compactions"], initial["compactions"])
        with path.open("a") as f: f.write("\n")
        resumed = P.update_file(json.loads(json.dumps(partial)), "codex", str(path), None, {})
        full = P.update_file(None, "codex", str(path), None, {})
        self.assertEqual(resumed, full)
        with path.open("a") as f: f.write(line)
        replay = P.update_file(resumed, "codex", str(path), None, {})
        self.assertEqual(len(replay["compactions"]), 2)
        self.assertEqual(replay["totals"], initial["totals"])

    def test_failed_append_rolls_back_metadata_and_retries_once(self):
        path = self.root / "session.jsonl"; path.write_text(self.checkpoint())
        previous = P.update_file(None, "codex", str(path), None, {})
        original = copy.deepcopy(previous)
        with path.open("a") as f: f.write(self.checkpoint("two"))
        def fail(agg, lines):
            P._codex_compaction(agg, {"window_id": "partial"}, P._from_iso("2026-10-10T12:00:00Z"))
            raise ValueError("fixture failure")
        with patch.object(P, "parse_codex", side_effect=fail):
            with self.assertRaises(ValueError): P.update_file(previous, "codex", str(path), None, {})
        self.assertEqual(previous, original)
        updated = P.update_file(previous, "codex", str(path), None, {})
        self.assertEqual(len(updated["compactions"]), 2)
        self.assertNotIn("window:partial", updated["compactions"])

    def test_v53_v54_backfill_preserves_all_entries_and_retries_unchanged_source(self):
        path = self.root / "session.jsonl"; path.write_text("".join(self.usage_lines()))
        old = P.update_file(None, "codex", str(path), None, {})
        old.pop("compactions"); old["sessions"][0].pop("compactions")
        archived = copy.deepcopy(old); archived["archived"] = True
        claude = P._blank_agg("claude", "existing-claude"); claude["archived"] = True
        for version in (53, 54):
            with self.subTest(version=version):
                files = {str(path): old, "gone": archived, "claude": claude}
                Path(D.CACHE_PATH).write_text(json.dumps({"version": version, "files": files}))
                with contextlib.redirect_stderr(io.StringIO()): D.load_cache()
                self.assertEqual(D._state["files"], files)
                with patch.object(P, "discover", return_value=[("codex", str(path), None)]):
                    with patch.object(P, "parse_codex", side_effect=ValueError("fixture failure")), contextlib.redirect_stderr(io.StringIO()): D.refresh()
                    self.assertEqual(D._state["files"], files)
                    D.refresh()
                updated = D._state["files"][str(path)]
                self.assertEqual(updated["totals"], old["totals"])
                self.assertEqual(len(updated["compactions"]), 1)
                self.assertEqual(D._state["files"]["gone"], archived)
                self.assertEqual(D._state["files"]["claude"], claude)

    def test_compaction_only_payload_export_archival_and_device_isolation(self):
        agg = self.parse([self.checkpoint()])
        remote = copy.deepcopy(agg); remote["_device"] = "other-device"
        D._state["files"] = {"local": agg}
        with patch.object(D, "_peer_items", return_value=[("remote", remote)]):
            sessions = D.build_payload()["sessions"]
        self.assertEqual(len(sessions), 2)
        self.assertEqual({s["device"] for s in sessions}, {"fixture-device", "other-device"})
        self.assertTrue(all(len(s["compactions"]) == 1 for s in sessions))
        self.assertEqual(D._export_agg(agg)["compactions"], agg["compactions"])
        agg["archived"] = True
        Path(D.CACHE_PATH).write_text(json.dumps({"version": 52, "files": {"gone": agg}}))
        with contextlib.redirect_stderr(io.StringIO()): D.load_cache()
        self.assertEqual(D._state["files"]["gone"], agg)


if __name__ == "__main__":
    unittest.main()
