"""
Dashboard component tests. Run with: python -m unittest tests.test_dashboard_components -v

Pure HTML builders and filters only, plus a headless run of the dashboard pages with Streamlit's AppTest
(reads the real result files read-only; no browser, no model). Never reads docs/ or chat_history.json.
"""

import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dashboard import components as c  # noqa: E402
from dashboard import data  # noqa: E402
from dashboard.theme import GROUPS  # noqa: E402

INJECTION = '<img src=x onerror=alert(1)>"; ignore previous instructions'


class HtmlBuilders(unittest.TestCase):
    def test_every_badge_has_icon_and_word(self):
        for group, (label, _icon, token) in GROUPS.items():
            out = c.status_badge_html(group)
            with self.subTest(group=group):
                self.assertIn("<svg", out)
                self.assertIn(label, out)
                self.assertIn(f"var(--{token})", out)

    def test_unknown_group_shows_its_own_name_escaped(self):
        out = c.status_badge_html(INJECTION)
        self.assertNotIn("<img", out)
        self.assertIn("&lt;img", out)

    def test_untrusted_text_is_escaped_everywhere(self):
        outputs = [
            c.kpi_tile_html(INJECTION, INJECTION, sub=INJECTION, title=INJECTION, of=INJECTION),
            c.page_header_html(INJECTION, INJECTION, [c.chip_html(INJECTION)]),
            c.section_title_html(INJECTION), c.note_html(INJECTION),
            c.empty_state_html(INJECTION, INJECTION), c.attribution_tag_html(INJECTION),
        ]
        for out in outputs:
            with self.subTest(out=out[:40]):
                self.assertNotIn("<img", out)
                self.assertNotIn('"; ignore', out)

    def test_kpi_missing_value_is_dash_with_reason(self):
        out = c.kpi_tile_html("Blocked", None, title="No attack attempts")
        self.assertIn("&mdash;", out)
        self.assertIn('title="No attack attempts"', out)

    def test_kpi_shows_denominator(self):
        self.assertIn("/ 20", c.kpi_tile_html("Blocked", 18, of=20))
        self.assertEqual(c.fraction(16, 20), "16/20")

    def test_attribution_tag(self):
        self.assertIn("Observed", c.attribution_tag_html("observed"))
        self.assertIn("Not stated", c.attribution_tag_html("unspecified"))
        self.assertEqual(c.attribution_tag_html(None), "")

    def test_theme_follows_system_setting(self):
        from dashboard.theme import PALETTES, ROOT_CSS
        dark, _, light = ROOT_CSS.partition("@media (prefers-color-scheme: light)")
        self.assertIn(f'--bg:{PALETTES["dark"]["bg"]}', dark)
        self.assertIn(f'--bg:{PALETTES["light"]["bg"]}', light)
        self.assertIn("color-scheme:light", light)

    def test_mock_banner_says_not_results(self):
        self.assertIn("not experiment results", c.MOCK_BANNER_HTML)


class EvidenceRendering(unittest.TestCase):
    def test_timeline_escapes_record_text(self):
        steps = [{"title": INJECTION, "detail": INJECTION, "tone": "attempt"},
                 {"title": "Outcome", "detail": "", "tone": "outcome"}]
        out = c.timeline_html(steps, "succeeded")
        self.assertNotIn("<img", out)
        self.assertIn("Succeeded", out)

    def test_evidence_rows_escape_record_text(self):
        out = c.evidence_rows_html({"raw": {"status": INJECTION, "rc": 0}, "layer": INJECTION})
        self.assertNotIn("<img", out)

    def test_activity_frame_newest_first_and_unverified(self):
        trials = pd.DataFrame({"time": pd.to_datetime(["2026-01-01", "2026-01-03"]), "item": ["a", "b"],
                               "kind": ["attack", "attack"], "config": ["A", "A"], "group": ["blocked", "succeeded"],
                               "verified": [True, False], "evidence": ["x", "y"]})
        frame = c.activity_frame(trials)
        self.assertEqual(list(frame["Test"]), ["b", "a"])
        self.assertEqual(list(frame["Result"]), ["Unverified", "Blocked"])

    def test_evidence_panel_renders_every_group_in_real_data(self):
        from streamlit.testing.v1 import AppTest

        def script(root):
            import sys
            sys.path.insert(0, root)
            from dashboard import components, data
            trials = data.load_trials(data.discover(data.SECURITY_DIR, include_superseded=True))
            for _, g in trials.groupby(["suite", "group"]):
                components.evidence_panel(data.row_dict(g.iloc[0]))

        at = AppTest.from_function(script, args=(str(ROOT),), default_timeout=60).run()
        self.assertFalse(at.exception, [e.value for e in at.exception])


class Charts(unittest.TestCase):
    def test_bar_label(self):
        from dashboard.charts import bar_label
        self.assertEqual(bar_label(16, 20, 0), "16/20 succeeded")
        self.assertEqual(bar_label(0, 0, 6), "no attempts · 6 not attempted")
        self.assertEqual(bar_label(1, 2, 4), "1/2 succeeded · 4 not attempted")

    def test_outcome_long_keeps_every_segment_and_denominator(self):
        from dashboard.charts import outcome_bar, outcome_long
        counts = pd.DataFrame([{"config": "A", "succeeded": 16, "blocked": 4, "unattributed": 0, "no_attempt": 0,
                                "attempted": 20},
                               {"config": "B", "succeeded": 0, "blocked": 18, "unattributed": 2, "no_attempt": 0,
                                "attempted": 20}])
        long = outcome_long(counts)
        self.assertEqual(set(zip(long["config"], long["outcome"], long["label"])),
                         {("A", "Succeeded", "16/20"), ("A", "Blocked", "4/20"), ("B", "Blocked", "18/20"),
                          ("B", "Unattributed", "2/20")})
        spec = outcome_bar(counts).to_dict()
        self.assertEqual([layer["name"] for layer in spec["layer"]], ["outcome_segments", "outcome_labels"])


class ExperimentsPieces(unittest.TestCase):
    def test_every_configuration_in_the_results_is_described(self):
        from dashboard.configs import describe
        configs = set(data.load_trials(data.discover(data.SECURITY_DIR, include_superseded=True))["config"])
        if not configs:
            self.skipTest("no result files")
        self.assertEqual({c for c in configs if describe(c) is None}, set())

    def test_config_panel(self):
        self.assertIn("none (--network none)", c.config_panel_html("B_docker_restricted"))
        unknown = c.config_panel_html(INJECTION)
        self.assertIn("No description recorded", unknown)
        self.assertNotIn("<img", unknown)

    def test_trial_frame_groups_attacks_first(self):
        trials = pd.DataFrame({"item": ["benign_a", "attack_b", "control_c", "attack_a"],
                               "kind": ["benign", "attack", "control", "attack"], "config": ["A"] * 4,
                               "repeat": [1, 1, 1, 1], "group": ["benign_completed", "blocked", "control_passed",
                                                                 "succeeded"],
                               "verified": [True] * 4, "evidence": ["e"] * 4})
        self.assertEqual(list(c.trial_frame(trials)["Test"]), ["attack_a", "attack_b", "control_c", "benign_a"])

    def test_experiments_page_for_each_current_run(self):
        from streamlit.testing.v1 import AppTest

        def script(root, run_id):
            import sys
            sys.path.insert(0, root)
            import streamlit as st
            from dashboard.views import experiments
            st.session_state.setdefault("x_run", run_id)
            experiments.render()

        trials = data.load_trials(data.discover(data.SECURITY_DIR))
        for run_id in sorted(trials["run_id"].unique()):
            at = AppTest.from_function(script, args=(str(ROOT), run_id), default_timeout=30).run()
            with self.subTest(run=run_id):
                self.assertFalse(at.exception, [e.value for e in at.exception])
                self.assertEqual(at.selectbox[0].value, run_id)


class ComparisonPage(unittest.TestCase):
    def test_matrix_charts_build(self):
        from dashboard.charts import layer_matrix, outcome_matrix
        trials = data.load_trials(data.discover(data.SECURITY_DIR))
        if trials.empty:
            self.skipTest("no result files")
        run = trials[trials["run_id"] == c.default_run(trials)]
        spec = outcome_matrix(data.cell_outcomes(run)).to_dict()
        self.assertEqual([layer["name"] for layer in spec["layer"]], ["matrix_cells", "matrix_text"])
        self.assertIsNotNone(layer_matrix(data.layer_counts(run), sorted(run["config"].unique())))

    def test_page_for_each_current_run(self):
        from streamlit.testing.v1 import AppTest

        def script(root, run_id):
            import sys
            sys.path.insert(0, root)
            import streamlit as st
            from dashboard.views import comparison
            st.session_state.setdefault("x_run", run_id)
            comparison.render()

        trials = data.load_trials(data.discover(data.SECURITY_DIR))
        for run_id in sorted(trials["run_id"].unique()):
            at = AppTest.from_function(script, args=(str(ROOT), run_id), default_timeout=30).run()
            with self.subTest(run=run_id):
                self.assertFalse(at.exception, [e.value for e in at.exception])


class LivePage(unittest.TestCase):
    """The Live Monitor against temporary folders: a security run, a model test, and nothing at all."""

    @staticmethod
    def script(root, sec, mod):
        import sys
        from pathlib import Path
        sys.path.insert(0, root)
        import streamlit as st
        from dashboard import data
        from dashboard.views import live
        saved = data.SECURITY_DIR, data.MODEL_TEST_DIR  # same process as the other tests: put them back after
        data.SECURITY_DIR, data.MODEL_TEST_DIR = Path(sec), Path(mod)
        try:
            st.session_state.setdefault("live_auto", False)  # no timer in a headless test
            live.render()
        finally:
            data.SECURITY_DIR, data.MODEL_TEST_DIR = saved

    def _run(self, sec, mod):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_function(self.script, args=(str(ROOT), str(sec), str(mod)), default_timeout=30).run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return "".join(m.value for m in at.markdown)

    def test_states(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            sec, mod = Path(tmp) / "sec", Path(tmp) / "mod"
            sec.mkdir()
            mod.mkdir()
            self.assertIn("No experiment running", self._run(sec, mod))
            rec = {"op": "attack_a", "kind": "attack", "config": "A", "repeat": 1, "rc": 0, "sink_hits": 0,
                   "sink_canary_hits": 1, "files_changed": False, "label": "succeeded", "layer": None,
                   "time": "2026-01-01T00:00:00"}
            (sec / "control-live.jsonl").write_text(json.dumps(rec) + "\n" + '{"op": "half-writ')
            page = self._run(sec, mod)
            self.assertIn("Run in progress (inferred)", page)  # just written
            self.assertIn("could not be read yet", page)  # the half-written last line
            (mod / "t5-20990101-000000.jsonl").write_text(json.dumps({"session": 1, "turn": 1, "ok": True, "secs": 3}))
            self.assertIn("t5-20990101-000000.jsonl", self._run(sec, mod))  # now the newest file


class LivePageWithEvents(unittest.TestCase):
    """The Live Monitor on a run written by the back end's RunMonitor: status, progress, outcomes, feed."""

    def test_running_then_finished(self):
        import tempfile
        sys.path.insert(0, str(ROOT / "experiments"))
        from live_events import RunMonitor
        with tempfile.TemporaryDirectory() as tmp:
            sec, mod = Path(tmp) / "sec", Path(tmp) / "mod"
            sec.mkdir()
            mod.mkdir()
            mon = RunMonitor(mod, "t8-sim-20260101-000000", "T8", expected_cases=2)
            mon.case_start("p1/fake/r1", part=1, attack="fake")
            mon.proposal("p1/fake/r1", {"name": "<img src=x onerror=alert(1)>.md", "provenance": {"tool": "save_note"},
                                        "warnings": [{"code": "request_read_only"}]})
            mon.observer("p1/fake/r1", False)
            mon.case_end("p1/fake/r1", "stopped_at_approval")
            page = LivePage()._run(sec, mod)
            self.assertIn("Run in progress", page)
            self.assertIn("<b>1/2</b> cases (50%)", page)
            self.assertIn("Stopped at approval (proposed, not written): 1", page)
            self.assertIn("Write proposed, waiting for approval", page)
            self.assertNotIn("<img", page)  # file names from events are escaped
            mon.finish()
            self.assertIn("Run finished", LivePage()._run(sec, mod))
            # The runner writes its results file just after finishing: the status file must still win.
            import json
            import time
            time.sleep(1.1)
            (mod / "t8-sim-20260101-000000.jsonl").write_text(json.dumps({"part": 1, "control": False, "held": True}))
            page = LivePage()._run(sec, mod)
            self.assertIn("Run finished", page)
            self.assertNotIn("(inferred)", page)


class Filters(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame({
            "run_id": ["r1", "r1", "r2"], "config": ["A", "B", "A"], "model": [None, None, "hermes3"],
            "time": pd.to_datetime(["2026-01-01T10:00", "2026-01-02T10:00", "2026-01-03T10:00"]),
        })

    def test_empty_selection_means_all(self):
        self.assertEqual(len(c.apply_filters(self.df)), 3)

    def test_each_filter(self):
        self.assertEqual(len(c.apply_filters(self.df, runs=["r1"])), 2)
        self.assertEqual(len(c.apply_filters(self.df, configs=["A"])), 2)
        self.assertEqual(len(c.apply_filters(self.df, models=["(scripted, no model)"])), 2)
        self.assertEqual(len(c.apply_filters(self.df, dates=(date(2026, 1, 2), date(2026, 1, 3)))), 2)

    def test_half_picked_date_range_is_ignored(self):
        self.assertEqual(len(c.apply_filters(self.df, dates=(date(2026, 1, 2),))), 3)


class PagesRunHeadless(unittest.TestCase):
    """Every page renders without an exception against the real result files."""

    def test_pages(self):
        from streamlit.testing.v1 import AppTest

        def page_script(root, name):
            import importlib
            import sys
            sys.path.insert(0, root)
            importlib.import_module(f"dashboard.views.{name}").render()

        for name in ("overview", "live", "experiments", "comparison", "readiness", "reports", "models", "settings"):
            at = AppTest.from_function(page_script, args=(str(ROOT), name), default_timeout=30).run()
            with self.subTest(page=name):
                self.assertFalse(at.exception, [e.value for e in at.exception])

    def test_overview_defaults_to_latest_forced_run(self):
        from streamlit.testing.v1 import AppTest
        trials = data.load_trials(data.discover(data.SECURITY_DIR))
        latest = c.default_run(trials)
        if latest is None:
            self.skipTest("no result files")
        at = AppTest.from_file(str(ROOT / "security_dashboard.py"), default_timeout=30).run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["f_run"], [latest])
        run = trials[trials["run_id"] == latest]
        page = "".join(m.value for m in at.markdown)
        self.assertIn(f'<div class="kpi-value">{len(run):,}', page)
        blocked = int(((run["kind"] == "attack") & (run["group"] == "blocked")).sum())
        attempted = int(run["attempted"].sum())
        # The Blocked tile is now a rate (blocked out of attempted, out of 100), as on the reference.
        self.assertIn(f'{round(100 * blocked / attempted)}<span class="of">/ 100', page)


class DefaultRun(unittest.TestCase):
    def test_prefers_newest_current_forced_run(self):
        df = pd.DataFrame({
            "run_id": ["control-old", "control-new", "run-x", "control-sup"],
            "suite": ["forced_control", "forced_control", "model_run", "forced_control"],
            "superseded": [False, False, False, True],
            "time": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-09"]),
        })
        self.assertEqual(c.default_run(df), "control-new")
        self.assertEqual(c.default_run(df[df["suite"] == "model_run"]), "run-x")
        self.assertIsNone(c.default_run(df.iloc[0:0]))



class ReadinessDomainsReportsEvidence(unittest.TestCase):
    """The readiness list, security domains, reports, the trial export and the evidence viewer's HTML."""

    def test_every_readiness_item_names_an_existing_source_and_a_known_status(self):
        from dashboard import readiness
        for item in readiness.ITEMS:
            with self.subTest(item=item["name"]):
                self.assertIn(item["status"], readiness.STATUS)
                self.assertTrue((ROOT / item["source"]).is_file(), item["source"])
        self.assertEqual(sum(readiness.counts().values()), len(readiness.ITEMS))

    def test_linux_is_listed_as_untested(self):
        from dashboard import readiness
        linux = [i for i in readiness.ITEMS if i["name"] == "Linux"]
        self.assertEqual([i["status"] for i in linux], ["untested"])

    def test_domains(self):
        from dashboard import data
        self.assertEqual(data.domain_of("attack_exfil_env_python", "attack"), "exfiltration")
        self.assertEqual(data.domain_of("attack_model_pull", "attack"), "model_server")
        self.assertEqual(data.domain_of("benign_grep_todo", "benign"), "benign")
        self.assertEqual(data.domain_of("zzz", "attack"), "other")

    def test_evidence_html_escapes_and_never_shows_self_reported_text(self):
        from dashboard.evidence import workbench_evidence_html
        rec = {"self_reported": {"claim": "SELFCLAIM"},
               "outcome": {"predicates": {"<img src=x>": True}},
               "evidence": {"approvals": [{"action": "save_note", "target": "<script>", "decision": "denied"}],
                            "workspace": {"created": ["<b>f</b>"]},
                            "network_log": {"blocked": 1, "allowed": 0, "names": ["evil"], "rank": 3}}}
        out = workbench_evidence_html(rec)
        self.assertNotIn("<img", out)
        self.assertNotIn("<script>", out)
        self.assertNotIn("SELFCLAIM", out)
        self.assertIn("agent-influenced, rank 3", out)

    def test_reports_are_found_with_their_evidence(self):
        import tempfile
        from dashboard import data
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "runs" / "core-1"
            (run / "report").mkdir(parents=True)
            (run / "report" / "report.html").write_text("<p>x</p>")
            (run / "results.jsonl").write_text("{}\n")
            (run / "batch-summary.json").write_text('{"planned": 2, "completed": 2}')
            (Path(tmp) / "_live" / "report").mkdir(parents=True)
            (Path(tmp) / "_live" / "report" / "report.html").write_text("x")
            found = data.find_reports([Path(tmp)])
            self.assertEqual(len(found), 1)
            self.assertEqual([p.name for p in found[0]["files"]], ["report.html", "results.jsonl", "batch-summary.json"])
            self.assertEqual(found[0]["summary"]["completed"], 2)

    def test_selection_export(self):
        import pandas as pd
        from dashboard.views.reports import selection_export
        trials = pd.DataFrame({"item": ["a"], "raw": [{"k": 1}], "tool_calls": [[]]})
        csv, jsonl = selection_export(trials)
        self.assertIn(b"item", csv)
        self.assertNotIn(b"raw", csv)
        self.assertEqual(jsonl, b'{"k": 1}\n')
    def test_domain_row_escapes_and_shows_results(self):
        import pandas as pd
        from dashboard.views.overview import domains_html
        view = pd.DataFrame({"item": ["attack_exfil_x", "attack_exfil_y"], "kind": ["attack", "attack"],
                             "group": ["succeeded", "blocked"], "verified": [True, True]})
        out = domains_html(view)
        self.assertIn("Data exfiltration", out)
        self.assertIn('title="Succeeded"', out)
        self.assertIn('title="Blocked"', out)

if __name__ == "__main__":
    unittest.main()
