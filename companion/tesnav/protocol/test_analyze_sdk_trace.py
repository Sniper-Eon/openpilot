"""Synthetic parser tests; these are not SDK acceptance evidence."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from analyze_sdk_trace import analyze


def row(event, elapsed=100, details="", pid=123, engine=1, context=1, wall="1700000000.100"):
    return (f"{wall} {pid} 456 D TesNav-AMap: sdk_event={event} elapsedMs={elapsed} "
            f"repository=42 engine={engine} requestContext={context} revision=1 pending=true "
            f"acceptedPathId=9 currentPathId=9 {details}\n")


def report(*rows):
    return analyze("".join(rows).encode())


class TraceTests(unittest.TestCase):
    def test_callback_and_accepted_unchanged_zero_distance_are_separate(self):
        result = report(
            row("guidance", details="callbackPathId=9 step=16 distance=0"),
            row("guidance_accepted", 101, "callbackPathId=9 step=16 distance=0 progressChanged=true"),
            row("guidance", 1100, "callbackPathId=9 step=16 distance=0"),
            row("guidance_accepted", 1101, "callbackPathId=9 step=16 distance=0 progressChanged=false"),
        )
        observed = result["observations"]
        self.assertEqual(observed["repository_reports_guidance_accepted"], 2)
        self.assertEqual(observed["accepted_guidance_progress_changed"], 1)
        self.assertEqual(observed["accepted_guidance_progress_unchanged"], 1)
        self.assertEqual(observed["accepted_guidance_zero_distance"], 2)
        self.assertEqual(result["metrics"]["guidance_callback_interval_ms"]["max"], 1000)
        self.assertEqual(result["acceptance"], "not_established")

    def test_persisted_source_status_and_dropped_rows_are_reported(self):
        result = report("1700000000.100 123 123 D TesNavNavState: source=budgetsUnconfirmed controlAllowed=false\n",
                        row("location", details="sourceMs=1700000000100 traceDropped=3"))
        self.assertEqual(result["source_status_counts"], {"budgetsUnconfirmed": 1})
        self.assertEqual(result["observations"]["trace_reports_dropped_rows"], 1)
        self.assertEqual(result["metrics"]["reported_dropped_rows"]["max"], 3)
        self.assertEqual(result["acceptance"], "not_established")

    def test_independent_call_token_is_separate_from_sdk_id(self):
        result = report(row("request_bound", details="token=1 sdkRequestId=101"),
                        row("independent_success", 120, "token=1 sdkRequestId=0"),
                        row("route_accepted", 130, "token=1 sdkRequestId=0"),
                        row("independent_success", 140, "token=1 sdkRequestId=0"))
        self.assertEqual(result["observations"]["independent_result_with_observed_call_token"], 1)
        self.assertEqual(result["observations"]["independent_sdk_id_differs_from_invocation"], 1)
        self.assertEqual(result["observations"]["independent_result_without_matching_observed_call_token"], 1)
        self.assertEqual(result["observations"]["repository_reports_route_accepted"], 1)
        self.assertEqual(result["acceptance"], "not_established")

    def test_empty_and_truncated_are_not_usable(self):
        self.assertEqual(report("unrelated\n")["capture_status"], "insufficient_or_malformed")
        result = report(row("location"), "TesNav-AMap: sdk_event=location elapsedMs=2\n")
        self.assertEqual(result["malformed_sdk_lines"], [2])
        self.assertEqual(result["capture_status"], "insufficient_or_malformed")

    def test_binding_is_scoped_and_consumed(self):
        result = report(row("request_bound", details="sdkRequestId=7"),
                        row("route_success", 120, "sdkRequestId=7"),
                        row("route_success", 130, "sdkRequestId=7"))
        self.assertEqual(result["observations"]["result_with_matching_observed_binding"], 1)
        self.assertEqual(result["observations"]["result_without_matching_observed_binding"], 1)
        self.assertEqual(result["metrics"]["bound_to_result_ms"]["max"], 20)
        self.assertEqual(result["acceptance"], "not_established")

    def test_stop_context_process_engine_do_not_inherit_binding(self):
        for transition in (row("stop_navigation", 110), row("reroute_yaw", 110)):
            result = report(row("request_bound", details="sdkRequestId=7"), transition,
                            row("route_success", 120, "sdkRequestId=7"))
            self.assertNotIn("result_with_matching_observed_binding", result["observations"])
        for changed in ({"pid": 999}, {"engine": 2}, {"context": 2}):
            result = report(row("request_bound", details="sdkRequestId=7"),
                            row("route_success", 120, "sdkRequestId=7", **changed))
            self.assertNotIn("result_with_matching_observed_binding", result["observations"])

    def test_source_duplicate_regression_future_and_missing(self):
        result = report(*(row("location", 100 + i, f"sourceMs={source}") for i, source in
                          enumerate((1700000000000, 1700000000000, 1699999999999, 1700000000200, 0))))
        for name in ("duplicate_location_source", "regressing_location_source",
                     "location_source_ahead_of_log_clock", "missing_or_nonpositive_location_source"):
            self.assertEqual(result["observations"][name], 1)
        self.assertEqual(result["metrics"]["location_age_at_log_ms"]["min"], -100)

    def test_paths_and_unkeyed_callbacks_do_not_prove_acceptance(self):
        result = report(row("guidance", details="callbackPathId=9"),
                        row("guidance", 200, "callbackPathId=8"), row("lane_callback", 300))
        self.assertEqual(result["observations"]["guidance_paths_match"], 1)
        self.assertEqual(result["observations"]["guidance_paths_unconfirmed"], 1)
        self.assertEqual(result["observations"]["callback_without_independent_source_id"], 1)
        self.assertEqual(result["acceptance"], "not_established")

    def test_clock_reset_breaks_interval(self):
        result = report(row("location", 200, "sourceMs=10"), row("location", 100, "sourceMs=20"))
        self.assertEqual(result["observations"]["elapsed_regression_or_interleaved_log"], 1)
        self.assertNotIn("location_callback_interval_ms", result["metrics"])

    def test_no_epoch_does_not_invent_source_age(self):
        result = report(row("location", details="sourceMs=1700000000000").split(" D ", 1)[1])
        self.assertEqual(result["sdk_rows"], 1)
        self.assertEqual(result["epoch_sdk_rows"], 0)
        self.assertNotIn("location_age_at_log_ms", result["metrics"])

    def test_service_status_and_utf8(self):
        result = report("I TesNavNavState: mode=REALTIME source=budgetsUnconfirmed\n")
        self.assertEqual(result["source_status_counts"], {"budgetsUnconfirmed": 1})
        with self.assertRaises(UnicodeDecodeError):
            analyze(b"\xff")

    def test_route_selection_breaks_callback_interval(self):
        result = report(row("guidance", details="callbackPathId=9"),
                        row("route_selected", 200), row("guidance", 300, "callbackPathId=9"))
        self.assertNotIn("guidance_callback_interval_ms", result["metrics"])

    def test_cli_reports_and_protects_input(self):
        script = str(Path(__file__).with_name("analyze_sdk_trace.py"))
        with tempfile.TemporaryDirectory(prefix="tesnav-trace-test-") as directory:
            trace = Path(directory) / "sdk.log"
            output = Path(directory) / "report.json"
            for content, expected in ((row("plan_requested"), 0), ("unrelated\n", 2)):
                trace.write_text(content, encoding="utf-8")
                run = subprocess.run([sys.executable, "-B", script, str(trace), "--report", str(output)],
                                     capture_output=True, text=True)
                self.assertEqual(run.returncode, expected, run.stderr)
                self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["acceptance"], "not_established")
            original = trace.read_bytes()
            run = subprocess.run([sys.executable, "-B", script, str(trace), "--report", str(trace)],
                                 capture_output=True)
            self.assertEqual(run.returncode, 2)
            self.assertEqual(trace.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
