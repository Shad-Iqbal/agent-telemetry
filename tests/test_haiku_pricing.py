"""Haiku request tiers are pricing subsets, never additional usage."""
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

MODEL = "Claude Haiku 5.5"
LOW = (.1, .5, .125, .2, .01)
HIGH = (.5, 2.5, .625, 1., .05)


class HaikuPricingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="telemetry-haiku-")
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "session.jsonl"
        for item in [patch.dict(D._state, {"files": {}, "version": D.CACHE_VERSION}),
                     patch.dict(D._meta, D._meta.copy()), patch.dict(D._dirty, {"v": False}),
                     patch.dict(D._grew, {"v": False, "saved": 0}),
                     patch.dict(D._gen, D._gen.copy()), patch.dict(D._cache_error, {"v": None}),
                     patch.object(D, "CACHE_PATH", str(self.path.parent / "cache.json")),
                     patch.object(P, "_copilot_project_map", return_value={}),
                     patch.object(D, "_peer_items", return_value=[]),
                     patch.object(D, "_local_id", return_value="fixture-device"),
                     patch.object(D, "_devices_meta", return_value=[]),
                     patch.object(D, "_context_files", return_value=[]),
                     patch.object(D, "_installed", return_value=[]),
                     patch.object(D, "_mcp_servers", return_value={})]:
            item.start(); self.addCleanup(item.stop)

    def line(self, ident, date="2026-10-12T12:00:00Z", **fields):
        return json.dumps({"uuid": str(ident), "timestamp": date, **fields}) + "\n"

    def user(self, ident, **fields):
        return self.line(ident, type="user", message={"content": "Fix this fixture"}, **fields)

    def assistant(self, ident, request, values, date="2026-10-12T12:00:01Z", **fields):
        inp, out, cc5, cc1, cr = values
        usage = {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": cr,
                 "cache_creation_input_tokens": cc5 + cc1,
                 "cache_creation": {"ephemeral_5m_input_tokens": cc5, "ephemeral_1h_input_tokens": cc1},
                 "output_tokens_details": {"thinking_tokens": out // 2}}
        usage.update(fields.pop("usage", {}))
        content = fields.pop("content", [{"type": "text", "text": "Fixture reply"}])
        return self.line(ident, date, type="assistant", requestId=request,
                         message={"id": request, "model": "claude-haiku-5-5",
                                  "content": content, "usage": usage}, **fields)

    def parse(self, lines):
        self.path.write_text("".join(lines))
        return P.update_file(None, "claude", str(self.path), None, {})

    def row(self, agg):
        return next(v for k, v in agg["records"].items() if k.endswith("\t" + MODEL))

    def cost(self, row, model=MODEL):
        return D._cost("claude", model, row["in"], row["out"], row["cr"],
                       row["cc5"], row["cc1"], long_context=P._long_values(row))

    def expected(self, values, high=False, us=False):
        return sum(n * p for n, p in zip(values, HIGH if high else LOW)) / 1e6 * (1.1 if us else 1)

    def test_threshold_includes_both_cache_tiers_and_is_strict(self):
        for prompt, high in [(100000, False), (100001, True)]:
            with self.subTest(prompt=prompt):
                values = (1, 200, 20, 30, prompt - 51)
                agg = self.parse([self.user(1), self.assistant(2, "r", values)])
                self.assertAlmostEqual(self.cost(self.row(agg)), self.expected(values, high))
                self.assertEqual(self.row(agg)["lc_asst"], int(high))
                self.assertEqual(agg["totals"]["asst"], 1)
                self.assertEqual(agg["totals"]["reason"], 100)
        # Some upstream records report zero flat cache creation but real tier counts.
        agg = self.parse([self.assistant(3, "r", (1, 10, 100000, 0, 0),
                                        usage={"cache_creation_input_tokens": 0})])
        self.assertAlmostEqual(self.cost(self.row(agg)), self.expected((1, 10, 100000, 0, 0), True))
        self.assertEqual(agg["totals"]["cc"], 0)

    def test_many_short_requests_and_mixed_tiers_are_not_daily_thresholds(self):
        short, long = (10, 100, 1000, 500, 48000), (10, 200, 3000, 500, 99000)
        agg = self.parse([self.user(1)] + [self.assistant(i + 2, str(i), short) for i in range(3)])
        self.assertAlmostEqual(self.cost(self.row(agg)), 3 * self.expected(short))
        P.parse_claude(agg, [self.assistant(9, "long", long)])
        self.assertAlmostEqual(self.cost(self.row(agg)), 3 * self.expected(short) + self.expected(long, True))
        self.assertEqual(agg["totals"]["asst"], 4)
        self.assertEqual(self.row(agg)["lc_asst"], 1)

    def test_streamed_output_growth_and_resume_do_not_double_count(self):
        a, b = (1, 1, 200, 300, 100000), (1, 400, 200, 300, 100000)
        lines = [self.user(1), self.assistant(2, "r", a), self.assistant(3, "r", b)]
        agg = self.parse(lines)
        original = copy.deepcopy(agg)
        P.parse_claude(agg, lines)
        self.assertEqual(agg["records"], original["records"])
        self.assertEqual(agg["totals"], original["totals"])
        self.assertAlmostEqual(self.cost(self.row(agg)), self.expected(b, True))
        self.assertEqual((agg["totals"]["user"], agg["totals"]["asst"]), (1, 1))

    def test_growing_input_reprices_original_day_closed_retry_turn_and_skill(self):
        edit = [{"type": "tool_use", "id": "edit", "name": "Edit", "input": {"file_path": "fixture.py"}}]
        check = [{"type": "tool_use", "id": "check", "name": "Bash", "input": {"command": "pytest"}}]
        a, b = (1, 10, 200, 300, 99000), (1, 30, 200, 300, 100000)
        lines = [self.user(1, date="2026-10-11T12:00:00Z"),
                 self.assistant(2, "r", a, date="2026-10-11T12:00:01Z", content=edit, attributionSkill="fixture"),
                 self.assistant(3, "r", a, date="2026-10-11T12:00:02Z", content=check, attributionSkill="fixture"),
                 self.assistant(4, "r", a, date="2026-10-11T12:00:03Z", content=edit, attributionSkill="fixture"),
                 self.user(5), self.assistant(6, "r", b, attributionSkill="fixture")]
        agg = self.parse(lines)
        rows = [v for k, v in agg["records"].items() if k.endswith("\t" + MODEL)]
        self.assertAlmostEqual(sum(self.cost(r) for r in rows), self.expected(b, True))
        previous = agg["records"]["2026-10-11\t" + MODEL]
        self.assertAlmostEqual(self.cost(previous), self.expected(a, True))
        activity = P.activity_of(agg)
        old = next(v for k, v in activity.items() if k.startswith("2026-10-11\t"))
        self.assertEqual(old["retries"], 1)
        self.assertEqual(P._long_values(old), P._long_values(old, "e"))
        self.assertEqual(P._long_values(old), P._long_values(old, "r"))
        D._state["files"] = {str(self.path): agg}
        payload = D.build_payload()
        expected = self.expected(b, True)
        self.assertAlmostEqual(sum(r["cost"] for r in payload["records"]), expected)
        self.assertAlmostEqual(sum(r["cost"] for r in payload["skills"]), expected)
        self.assertAlmostEqual(sum(self.cost(r) for r in activity.values()), expected)
        # Activity payloads already round estimates to four decimal places.
        self.assertAlmostEqual(sum(r["cost"] for r in payload["activity"]), expected, places=4)
        self.assertAlmostEqual(payload["sessions"][0]["cost"], expected)
        self.assertAlmostEqual(payload["sessions"][0]["model_days"][MODEL]["2026-10-11"][0], self.expected(a, True), places=4)
        self.assertEqual(D._export_agg(agg)["records"], agg["records"])

    def test_restart_append_matches_full_parse_and_request_state_stays_bounded(self):
        values = (1, 2, 3, 4, 100000)
        lines = [self.user(1)] + [self.assistant(i + 2, str(i), values) for i in range(20)]
        agg = self.parse(lines[:5])
        with self.path.open("a") as f: f.write("".join(lines[5:]))
        incremental = P.update_file(json.loads(json.dumps(agg)), "claude", str(self.path), None, {})
        full = P.update_file(None, "claude", str(self.path), None, {})
        self.assertEqual(incremental, full)
        self.assertEqual(len(full["state"]["haiku_context"]), 8)
        self.assertEqual(set(full["state"]["haiku_context"]), set(full["state"]["resp"]))

    def test_today_summary_and_payload_share_cost_without_counting_pricing_subsets(self):
        short, long = (1, 2, 3, 4, 5), (1000, 2000, 3000, 4000, 1000000)
        agg = self.parse([self.user(1), self.assistant(2, "short", short), self.assistant(3, "long", long)])
        D._state["files"] = {str(self.path): agg}
        with patch.object(D.time, "strftime", return_value="2026-10-12"):
            summary = D.build_today_summary()
        payload = D.build_payload()
        self.assertEqual(summary["tokens"], sum(short) + sum(long))
        expected = self.expected(short) + self.expected(long, True)
        self.assertEqual(summary["spend"], round(expected, 2))
        self.assertAlmostEqual(sum(r["cost"] for r in payload["records"]), expected)
        self.assertEqual(payload["pricing_long_context"][MODEL], list(HIGH))

    def test_us_multiplier_and_unpublished_fast_rate(self):
        values = (1, 2, 3, 4, 100000)
        agg = self.parse([self.assistant(1, "r", values, usage={"inference_geo": "us"})])
        row = next(iter(agg["records"].values()))
        self.assertAlmostEqual(self.cost(row, MODEL + P.US_SUFFIX), self.expected(values, True, True))
        self.assertEqual(P.price_of(MODEL + P.FAST_SUFFIX, long_context=True), (0, 0, 0, 0, 0))
        self.assertEqual(P.price_of("Claude Haiku 4.5"), (1, 5, 1.25, 2, .1))
        self.assertAlmostEqual(self.cost({"in": 1, "out": 2, "cc5": 3, "cc1": 4, "cr": 5}),
                               self.expected((1, 2, 3, 4, 5)))

    def test_v55_targeted_backfill_preserves_archives_and_failed_parse_retries(self):
        agg = self.parse([self.user(1), self.assistant(2, "r", (1, 2, 3, 4, 100000))])
        agg.pop("haiku_pricing")
        for row in agg["records"].values():
            for field in list(row):
                if field.startswith("lc_"): del row[field]
        archived = copy.deepcopy(agg); archived["archived"] = True
        files = {str(self.path): agg, "archived": archived}
        Path(D.CACHE_PATH).write_text(json.dumps({"version": 55, "files": files}))
        with contextlib.redirect_stderr(io.StringIO()): D.load_cache()
        self.assertEqual(D._state["files"], files)
        original = copy.deepcopy(D._state["files"][str(self.path)])
        with patch.object(P, "discover", return_value=[("claude", str(self.path), None)]):
            with patch.object(P, "parse_claude", side_effect=ValueError("fixture failure")), \
                    contextlib.redirect_stderr(io.StringIO()): D.refresh()
            self.assertEqual(D._state["files"][str(self.path)], original)
            D.refresh()
        updated = D._state["files"][str(self.path)]
        self.assertEqual(updated["totals"], original["totals"])
        self.assertEqual(updated["haiku_pricing"], 1)
        self.assertEqual(D._state["files"]["archived"], archived)


if __name__ == "__main__":
    unittest.main()
