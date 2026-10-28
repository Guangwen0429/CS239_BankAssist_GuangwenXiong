"""Tests for the trace / episode generator (run_scenarios) and the Tracer itself.

run_scenarios.main() is always pointed at a temporary directory with
--root, so running the tests never touches the committed traces/ folder.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

try:
    from . import _path, _helpers as H
except ImportError:
    import _path
    import _helpers as H

from bankassist import run_scenarios
from bankassist.scenarios import SCENARIOS
from bankassist.trace import EVENT_KINDS, Tracer, redact

N = len(SCENARIOS)


class GeneratedTracesTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="bankassist-traces-")
        cls.root = Path(cls._tmp.name)
        cls.stdout = io.StringIO()
        with _path.rules_only_env(), contextlib.redirect_stdout(cls.stdout):
            run_scenarios.main(["--root", str(cls.root)])
        cls.trace_dir = cls.root / "traces" / "phase1"
        cls.ep_dir = cls.root / "BankAssist" / "episodes"
        cls.traces = {p.stem: json.loads(p.read_text(encoding="utf-8"))
                      for p in sorted(cls.trace_dir.glob("*.json"))}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    # ---------------------------------------------------------------- files
    def test_course_requirement_at_least_three_traces(self):
        self.assertGreaterEqual(len(self.traces), 3)

    def test_one_json_and_one_md_per_scenario(self):
        self.assertEqual(N, 6)
        ids = sorted(sc["id"] for sc in SCENARIOS)
        self.assertEqual(sorted(p.stem for p in self.trace_dir.glob("*.json")), ids)
        self.assertEqual(sorted(p.stem for p in self.trace_dir.glob("*.md")), ids)

    def test_readme_written(self):
        readme = (self.root / "traces" / "README.md").read_text(encoding="utf-8")
        self.assertTrue(readme.startswith("# Traces"))
        for sc in SCENARIOS:
            self.assertIn(f"phase1/{sc['id']}.json", readme)
            self.assertIn(sc["title"], readme)

    def test_episodes_written(self):
        names = sorted(p.name for p in self.ep_dir.glob("*.md"))
        self.assertEqual(names, [f"example{i}.md" for i in range(1, N + 1)])
        for i, sc in enumerate(SCENARIOS, 1):
            text = (self.ep_dir / f"example{i}.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith(f"# Example {i}: {sc['title']}"))
            for section in ("## Initial Inputs", "## Trajectory", "## Policy Connection",
                            "## Expected Outcome", "## Actual Phase 1 Outcome"):
                self.assertIn(section, text, f"example{i}.md")

    def test_output_layout(self):
        written = {p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file()}
        expected = ({f"traces/phase1/{sc['id']}.{ext}" for sc in SCENARIOS for ext in ("json", "md")}
                    | {"traces/README.md", "traces/viewer.html"}
                    | {f"BankAssist/episodes/example{i}.md" for i in range(1, N + 1)})
        self.assertLessEqual(expected, written)
        for w in written:
            self.assertTrue(w.startswith(("traces/", "BankAssist/episodes/")), w)

    def test_viewer_html_written(self):
        html = (self.root / "traces" / "viewer.html").read_text(encoding="utf-8")
        self.assertTrue(html.lower().startswith("<!doctype html>"))
        for sc in SCENARIOS:
            self.assertIn(sc["id"], html)
        pins = H.SEED_PINS | {c["pin"] for sc in SCENARIOS for c in sc["conversations"]}
        self.assertNotRegex(html, r'"pin":\s*"(?!\*\*\*\*)')
        for pin in pins:
            self.assertNotIn(f'"pin": "{pin}"', html)

    def test_progress_printed(self):
        out = self.stdout.getvalue()
        self.assertIn(f"Wrote {N} traces", out)
        self.assertEqual(out.count("[VIOLATION"), sum(sc["violation"] for sc in SCENARIOS))

    # --------------------------------------------------------------- content
    def test_json_structure(self):
        for sid, data in self.traces.items():
            with self.subTest(trace=sid):
                self.assertEqual(data["scenario_id"], sid)
                self.assertEqual(set(data), {"scenario_id", "title", "description", "started_at",
                                             "meta", "events"})
                self.assertEqual([e["step"] for e in data["events"]],
                                 list(range(1, len(data["events"]) + 1)))
                for e in data["events"]:
                    self.assertIn(e["kind"], EVENT_KINDS)
                self.assertIn("audit_log", data["meta"])
                self.assertEqual(data["meta"]["concierge_mode"], "rules")

    def test_all_six_event_kinds_across_the_set(self):
        kinds = {e["kind"] for data in self.traces.values() for e in data["events"]}
        self.assertEqual(kinds, set(EVENT_KINDS))

    def test_all_six_event_kinds_in_every_trace(self):
        for sid, data in self.traces.items():
            with self.subTest(trace=sid):
                self.assertEqual({e["kind"] for e in data["events"]}, set(EVENT_KINDS))

    def test_every_trace_has_inter_agent_messages(self):
        for sid, data in self.traces.items():
            with self.subTest(trace=sid):
                msgs = [e for e in data["events"] if e["kind"] == "message"]
                self.assertGreaterEqual(len(msgs), 2)  # at least one request + its reply
                for m in msgs:
                    self.assertNotEqual(m["agent"], m["to"])
                    self.assertNotEqual(m["to"], "User")

    def test_no_pin_in_any_written_file(self):  # P2
        pins = H.SEED_PINS | {c["pin"] for sc in SCENARIOS for c in sc["conversations"]}
        for sid, data in self.traces.items():
            with self.subTest(trace=sid):
                self.assertEqual(H.find_pin_leaks(data, pins), [])
        for path in list(self.root.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                self.assertNotRegex(text, r'"pin":\s*"(?!\*\*\*\*)')

    def test_markdown_trace_has_one_row_per_event(self):
        for sid, data in self.traces.items():
            with self.subTest(trace=sid):
                md = (self.trace_dir / f"{sid}.md").read_text(encoding="utf-8")
                self.assertTrue(md.startswith(f"# Trace `{sid}`"))
                for e in data["events"]:
                    self.assertIn(f"| {e['step']} | {e['agent']} | {e['kind']} |", md)
                self.assertIn("## Audit log at end of run", md)

    def test_committed_traces_present_in_repo(self):
        # read-only check of the folder submitted with the project
        committed = list(Path(_path.REPO_ROOT, "traces", "phase1").glob("*.json"))
        self.assertGreaterEqual(len(committed), 3)


class TracerUnitTest(unittest.TestCase):
    def test_redact_masks_pin_recursively(self):
        data = {"pin": "1234", "nested": [{"pin": "5678", "x": 1}], "other": "1234"}
        self.assertEqual(redact(data), {"pin": "****", "nested": [{"pin": "****", "x": 1}],
                                        "other": "1234"})
        self.assertEqual(data["pin"], "1234")  # original untouched

    def test_events_are_redacted_when_recorded(self):
        t = Tracer("x")
        t.message("ConciergeAgent", "AuthAgent", "authenticate", {"customer_id": "C001", "pin": "1234"})
        t.action("AuthAgent", "verify_identity", {"customer_id": "C001", "pin": "1234"})
        self.assertEqual(t.events[0]["payload"]["pin"], "****")
        self.assertEqual(t.events[1]["args"]["pin"], "****")

    def test_unknown_kind_rejected(self):
        with self.assertRaises(AssertionError):
            Tracer("x")._add("telepathy", "Agent")

    def test_save_json_and_markdown(self):
        t = Tracer("unit", "Unit", "desc")
        t.user_input("hi | there", to="ConciergeAgent")
        t.response("ConciergeAgent", "hello")
        with tempfile.TemporaryDirectory() as d:
            t.save_json(os.path.join(d, "t.json"))
            t.save_markdown(os.path.join(d, "t.md"))
            saved = json.loads(Path(d, "t.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["scenario_id"], "unit")
            md = Path(d, "t.md").read_text(encoding="utf-8")
        self.assertIn("hi \\| there", md)  # pipes escaped inside table cells


if __name__ == "__main__":
    unittest.main()
