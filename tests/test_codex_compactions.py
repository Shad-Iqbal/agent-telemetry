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

    def timing_lines(self, start=1791806400000, end=1791806402000, **completion):
        at = "2026-10-12T12:00:01Z"
        return [self.line("session_meta", {"id": "fixture-thread"}, at),
                self.line("turn_context", {"model": "gpt-6.1-sol"}, at),
                self.line("token_usage_record", {"response_id": "timed-response", "thread_id": "fixture-thread",
                    "turn_id": "fixture-turn", "usage": {"input_tokens": 100, "output_tokens": 10}}, at),
                self.line("compacted", {"compaction_response_id": "timed-response",
                    "replacement_history": [{"type": "function_call_output", "output": "PRIVATE HISTORY"}]}, at),
                self.line("event_msg", {"type": "item_completed", "thread_id": "fixture-thread", "turn_id": "fixture-turn",
                    "item": {"type": "ContextCompaction", "id": "fixture-item"},
                    "started_at_ms": start, "completed_at_ms": end, **completion}, "2026-10-12T12:00:02Z")]

    def test_explicit_completion_duration_enriches_checkpoint_without_usage_or_extra_event(self):
        lines = self.timing_lines()
        agg = self.parse(lines)
        with patch.object(P, "_codex_timing_completion"):
            untimed = self.parse(lines)
        event = next(iter(agg["compactions"].values()))
        self.assertEqual(event["duration_ms"], 2000)
        self.assertEqual(event["trigger"], "unknown")
        self.assertIsNone(event["before"]); self.assertIsNone(event["after"])
        for key in ("records", "totals", "hourly", "tools", "activity", "_active_last", "first_ts", "last_ts"):
            self.assertEqual(agg.get(key), untimed.get(key), key)
        self.assertEqual(len(agg["compactions"]), 1)
        self.assertNotIn("PRIVATE", json.dumps(agg))
        D._state["files"] = {"fixture": agg}
        self.assertEqual(D.build_payload()["sessions"][0]["compactions"][0]["duration_ms"], 2000)
        self.assertEqual(D._export_agg(agg)["compactions"], agg["compactions"])
        self.assertNotIn("compaction_timing", D._export_agg(agg)["state"])

    def test_missing_invalid_timing_or_mismatched_identity_is_not_inferred(self):
        for start, end in ((None, 1791806402000), (True, 1791806402000), (-1, 1791806402000),
                           ("1791806400000", 1791806402000), (1791806400000., 1791806402000),
                           (1791806402000, 1791806400000), (1791806400000, 10**1000)):
            with self.subTest(start=start, end=end):
                self.assertIsNone(next(iter(self.parse(self.timing_lines(start, end))["compactions"].values()))["duration_ms"])
        for change in ({"thread_id": "other-thread"}, {"turn_id": "other-turn"},
                       {"type": "item_started"}, {"item": {"type": "CommandExecution", "id": "fixture-item"}},
                       {"item": {"type": "ContextCompaction"}}):
            with self.subTest(change=change):
                self.assertIsNone(next(iter(self.parse(self.timing_lines(**change))["compactions"].values()))["duration_ms"])
        lines = self.timing_lines()
        for selected in (lines[:2] + lines[3:], lines[:3] + lines[4:]):
            agg = self.parse(selected)
            self.assertTrue(all(e["duration_ms"] is None for e in agg["compactions"].values()))
        # A copied resume snapshot is not the explicit top-level identity chain.
        checkpoint = self.line("compacted", {"compaction_response_id": "timed-response",
            "latest_token_usage_record": {"response_id": "timed-response", "thread_id": "fixture-thread", "turn_id": "fixture-turn"}}, "2026-10-12T12:00:01Z")
        self.assertIsNone(next(iter(self.parse(lines[:2] + [checkpoint, lines[-1]])["compactions"].values()))["duration_ms"])

    def test_zero_duration_and_out_of_order_metadata_are_supported(self):
        lines = self.timing_lines(start=1791806401000, end=1791806401000)
        self.assertEqual(next(iter(self.parse(lines)["compactions"].values()))["duration_ms"], 0)
        reordered = lines[:3] + [lines[4], lines[3]]
        self.assertEqual(next(iter(self.parse(reordered)["compactions"].values()))["duration_ms"], 0)

    def test_overlapping_candidates_are_ambiguous_and_clear_prior_duration(self):
        lines = self.timing_lines()
        agg = self.parse(lines)
        self.assertEqual(next(iter(agg["compactions"].values()))["duration_ms"], 2000)
        second = json.loads(lines[-1]); second["payload"]["item"]["id"] = "another-item"
        P.parse_codex(agg, [json.dumps(second)])
        self.assertIsNone(next(iter(agg["compactions"].values()))["duration_ms"])
        request = json.loads(lines[2]); request["payload"]["response_id"] = "another-response"
        checkpoint = json.loads(lines[3]); checkpoint["payload"]["compaction_response_id"] = "another-response"
        agg = self.parse(lines[:4] + [json.dumps(request), json.dumps(checkpoint), lines[-1]])
        self.assertEqual(len(agg["compactions"]), 2)
        self.assertTrue(all(e["duration_ms"] is None for e in agg["compactions"].values()))
        agg = self.parse(lines)
        # Even a checkpoint without a response/turn identity makes the interval
        # ambiguous; never ignore it when assigning a nearby completion.
        P.parse_codex(agg, [self.line("compacted", {"window_id": "unlinked"}, "2026-10-12T12:00:01.500Z")])
        self.assertTrue(all(e["duration_ms"] is None for e in agg["compactions"].values()))

    def test_replayed_checkpoint_completion_and_conflicting_item_identity(self):
        lines = self.timing_lines()
        agg = self.parse(lines)
        replay = json.loads(lines[3]); replay["timestamp"] = "2026-10-13T12:00:01Z"
        P.parse_codex(agg, [json.dumps(replay), lines[-1]])
        self.assertEqual(len(agg["compactions"]), 1)
        self.assertEqual(next(iter(agg["compactions"].values()))["duration_ms"], 2000)
        conflict = json.loads(lines[-1]); conflict["payload"]["started_at_ms"] += 500
        P.parse_codex(agg, [json.dumps(conflict)])
        self.assertIsNone(next(iter(agg["compactions"].values()))["duration_ms"])

    def test_timing_state_roundtrips_incrementally_and_failed_append_rolls_back(self):
        lines = self.timing_lines(); path = self.root / "timed.jsonl"
        path.write_text("".join(lines[:-1]))
        original = P.update_file(None, "codex", str(path), None, {})
        before = copy.deepcopy(original)
        with path.open("a") as f:
            f.write(lines[-1]); f.write(self.line("token_usage_record", {"usage": {"input_tokens": "bad"}}))
        with self.assertRaises(ValueError): P.update_file(original, "codex", str(path), None, {})
        self.assertEqual(original, before)
        path.write_text("".join(lines))
        resumed = P.update_file(json.loads(json.dumps(original)), "codex", str(path), None, {})
        self.assertEqual(resumed, P.update_file(None, "codex", str(path), None, {}))
        self.assertEqual(next(iter(resumed["compactions"].values()))["duration_ms"], 2000)

    def test_unchanged_live_log_backfills_timing_once_and_archive_stays_unchanged(self):
        lines = self.timing_lines(); path = self.root / "backfill.jsonl"
        path.write_text("".join(lines)); original = P.update_file(None, "codex", str(path), None, {})
        original["state"].pop("compaction_timing")
        for e in original["compactions"].values(): e["duration_ms"] = None
        before = copy.deepcopy(original)
        with patch.object(P, "parse_codex", side_effect=ValueError("backfill failure")):
            with self.assertRaises(ValueError): P.update_file(original, "codex", str(path), None, {})
        self.assertEqual(original, before)
        updated = P.update_file(original, "codex", str(path), None, {})
        self.assertEqual(updated["totals"], original["totals"])
        self.assertEqual(next(iter(updated["compactions"].values()))["duration_ms"], 2000)
        with patch.object(P, "parse_codex") as parse:
            self.assertIs(P.update_file(updated, "codex", str(path), None, {}), updated)
            parse.assert_not_called()
        original["archived"] = True
        self.assertIs(P.update_file(original, "codex", str(self.root / "gone"), None, {}), original)
        self.assertIsNone(next(iter(original["compactions"].values()))["duration_ms"])

    def test_forked_and_cross_thread_timing_never_enrich_child_history(self):
        lines = self.timing_lines()
        meta = self.line("session_meta", {"id": "child", "forked_from_id": "parent"}, "2026-10-12T12:00:01Z")
        agg = self.parse([meta] + lines[1:])
        self.assertEqual(agg["compactions"], {})
        foreign = self.parse([self.line("session_meta", {"id": "different-thread"})] + lines[1:])
        self.assertTrue(all(e["duration_ms"] is None for e in foreign["compactions"].values()))

    def test_empty_logs_do_not_repeat_backfill_and_correlation_state_is_bounded(self):
        path = self.root / "empty.jsonl"; path.write_text("")
        agg = P.update_file(None, "codex", str(path), None, {})
        self.assertIs(P.update_file(agg, "codex", str(path), None, {}), agg)
        agg = self.parse(self.timing_lines())
        for i in range(40):
            P.parse_codex(agg, [self.line("token_usage_record", {"response_id": f"response-{i}", "thread_id": "fixture-thread", "turn_id": "fixture-turn", "usage": {}})])
        self.assertEqual(len(agg["state"]["compaction_timing"]["requests"]), 32)
        self.assertEqual(next(iter(agg["compactions"].values()))["duration_ms"], 2000)

    def test_completion_eviction_cannot_make_an_ambiguous_duration_known(self):
        lines = self.timing_lines(); agg = self.parse(lines)
        overlap = json.loads(lines[-1]); overlap["payload"]["item"]["id"] = "overlap"
        overlap["payload"]["started_at_ms"] -= 100
        P.parse_codex(agg, [json.dumps(overlap)])
        self.assertIsNone(agg["compactions"]["response:timed-response"]["duration_ms"])
        # Evict the first completion while the second still covers this event.
        for i in range(31):
            completion = json.loads(lines[-1]); p = completion["payload"]
            p["item"]["id"] = f"later-{i}"; p["started_at_ms"] += 10000; p["completed_at_ms"] += 10000
            P.parse_codex(agg, [json.dumps(completion)])
        self.assertEqual(len(agg["state"]["compaction_timing"]["completions"]), 32)
        self.assertIsNone(agg["compactions"]["response:timed-response"]["duration_ms"],
                          "Eviction forgot the conflicting completion")

    def test_evicted_checkpoint_replay_cannot_forget_its_ambiguity(self):
        lines = self.timing_lines(); agg = self.parse(lines)
        overlap = json.loads(lines[-1]); overlap["payload"]["item"]["id"] = "overlap"
        P.parse_codex(agg, [json.dumps(overlap)])
        for i in range(33):
            request = json.loads(lines[2]); request["payload"]["response_id"] = f"later-{i}"
            checkpoint = json.loads(lines[3]); checkpoint["payload"]["compaction_response_id"] = f"later-{i}"
            checkpoint["timestamp"] = "2026-10-12T12:01:00Z"
            completion = json.loads(lines[-1]); p = completion["payload"]
            p["item"]["id"] = f"later-{i}"; p["started_at_ms"] += 10000; p["completed_at_ms"] += 10000
            P.parse_codex(agg, [json.dumps(request), json.dumps(checkpoint), json.dumps(completion)])
        # A replay of an old event after its correlation state was evicted must
        # not manufacture a unique match from only the replayed records.
        P.parse_codex(agg, lines[2:])
        self.assertIsNone(agg["compactions"]["response:timed-response"]["duration_ms"])

    def test_unlinked_checkpoint_clears_duration_even_after_correlation_eviction(self):
        lines = self.timing_lines(); agg = self.parse(lines)
        for i in range(33):
            request = json.loads(lines[2]); request["payload"]["response_id"] = f"later-{i}"
            checkpoint = json.loads(lines[3]); checkpoint["payload"]["compaction_response_id"] = f"later-{i}"
            checkpoint["timestamp"] = "2026-10-12T12:01:00Z"
            P.parse_codex(agg, [json.dumps(request), json.dumps(checkpoint)])
        self.assertEqual(agg["compactions"]["response:timed-response"]["duration_ms"], 2000)
        P.parse_codex(agg, [self.line("compacted", {"window_id": "unlinked"}, "2026-10-12T12:00:01.500Z")])
        self.assertIsNone(agg["compactions"]["response:timed-response"]["duration_ms"],
                          "Evicted checkpoint retained a now-ambiguous duration")

    def test_conflicting_completion_stays_ambiguous_after_item_eviction(self):
        lines = self.timing_lines(); agg = self.parse(lines)
        conflict = json.loads(lines[-1]); conflict["payload"]["started_at_ms"] += 100
        P.parse_codex(agg, [json.dumps(conflict)])
        for i in range(33):
            completion = json.loads(lines[-1]); p = completion["payload"]
            p["item"]["id"] = f"later-{i}"; p["started_at_ms"] += 10000; p["completed_at_ms"] += 10000
            P.parse_codex(agg, [json.dumps(completion)])
        P.parse_codex(agg, [lines[-1]])
        self.assertIsNone(agg["compactions"]["response:timed-response"]["duration_ms"])

    def test_request_identity_conflict_is_detected_after_request_eviction(self):
        lines = self.timing_lines(); agg = self.parse(lines)
        for i in range(33):
            request = json.loads(lines[2]); request["payload"]["response_id"] = f"later-{i}"
            request["payload"]["usage"] = {}
            P.parse_codex(agg, [json.dumps(request)])
        conflict = json.loads(lines[2]); conflict["payload"]["turn_id"] = "other-turn"
        P.parse_codex(agg, [json.dumps(conflict)])
        self.assertIsNone(agg["compactions"]["response:timed-response"]["duration_ms"])


if __name__ == "__main__":
    unittest.main()
