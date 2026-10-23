"""Summarize existing TesNav logcat traces; never authorize control or budgets."""

import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re


EPOCH = re.compile(r"^\s*(\d{10}\.\d+)\s+(\d+)\s+\d+\s+[VDIWEF]\s+")
FIELDS = re.compile(r"(\w+)=([^\s]*)")
REQUIRED = ("elapsedMs", "repository", "engine", "requestContext", "revision")


def integer(value):
    return int(value) if value is not None and re.fullmatch(r"-?\d+", value) else None


def distribution(values):
    values = sorted(values)
    if not values:
        return {"count": 0}
    return {"count": len(values), "min": values[0],
            "median": values[(len(values) - 1) // 2], "max": values[-1]}


def analyze(raw):
    events, sources, observations = Counter(), Counter(), Counter()
    examples, metrics, streams = defaultdict(list), defaultdict(list), {}
    malformed, sdk_rows, epoch_rows = [], 0, 0

    def observe(kind, line):
        observations[kind] += 1
        if len(examples[kind]) < 10:
            examples[kind].append(line)

    for number, line in enumerate(raw.decode("utf-8-sig", errors="strict").splitlines(), 1):
        if "TesNavNavState" in line and "source=" in line:
            source = dict(FIELDS.findall(line)).get("source")
            sources[source] += 1
        if "TesNav-AMap" not in line or "sdk_event=" not in line:
            continue
        fields = dict(FIELDS.findall(line[line.index("sdk_event="):]))
        event = fields.get("sdk_event")
        if not event or any(integer(fields.get(key)) is None for key in REQUIRED):
            malformed.append(number)
            continue
        sdk_rows += 1
        events[event] += 1
        epoch = EPOCH.match(line)
        epoch_rows += int(epoch is not None)
        pid = epoch.group(2) if epoch else "unknown"
        key = (pid, fields["repository"], fields["engine"])
        elapsed = int(fields["elapsedMs"])
        state = streams.setdefault(key, {})
        if elapsed < state.get("last_elapsed", elapsed):
            observe("elapsed_regression_or_interleaved_log", number)
            state.clear()
        state["last_elapsed"] = elapsed

        dropped = integer(fields.get("traceDropped"))
        if dropped is not None and dropped > 0:
            observe("trace_reports_dropped_rows", number)
            metrics["reported_dropped_rows"].append(dropped)

        if event in ("plan_requested", "stop_navigation", "release", "reroute_yaw", "reroute_traffic", "route_selected"):
            if event != "route_selected":
                state.pop("binding", None)
            # Do not pool intervals across stopped navigation or route transitions.
            for name in ("location_elapsed", "source_ms", "guidance_elapsed"):
                state.pop(name, None)
        if event == "request_bound":
            request = integer(fields.get("sdkRequestId"))
            if request is None or request <= 0:
                observe("invalid_request_binding", number)
            else:
                state["binding"] = (fields["requestContext"], request, elapsed)
                state["binding_token"] = fields.get("token")
        elif event in ("independent_success", "independent_failure"):
            binding = state.get("binding")
            token = fields.get("token")
            if (binding is not None and token is not None and token == state.get("binding_token")
                    and fields["requestContext"] == binding[0]):
                observe("independent_result_with_observed_call_token", number)
                metrics["independent_bound_to_result_ms"].append(elapsed - binding[2])
                if integer(fields.get("sdkRequestId")) != binding[1]:
                    observe("independent_sdk_id_differs_from_invocation", number)
                state.pop("binding", None)
            else:
                observe("independent_result_without_matching_observed_call_token", number)
        elif event == "route_accepted":
            observe("repository_reports_route_accepted", number)
        elif event in ("route_success", "route_failure"):
            binding = state.get("binding")
            request = integer(fields.get("sdkRequestId"))
            if binding is None or binding[:2] != (fields["requestContext"], request):
                observe("result_without_matching_observed_binding", number)
            else:
                metrics["bound_to_result_ms"].append(elapsed - binding[2])
                state.pop("binding", None)
                observe("result_with_matching_observed_binding", number)
        elif event == "location":
            if "location_elapsed" in state:
                metrics["location_callback_interval_ms"].append(elapsed - state["location_elapsed"])
            state["location_elapsed"] = elapsed
            source = integer(fields.get("sourceMs"))
            if source is None or source <= 0:
                observe("missing_or_nonpositive_location_source", number)
            else:
                previous = state.get("source_ms")
                if previous is not None:
                    delta = source - previous
                    metrics["location_source_delta_ms"].append(delta)
                    if delta <= 0:
                        observe("duplicate_location_source" if delta == 0 else "regressing_location_source", number)
                state["source_ms"] = source
                if epoch:
                    age = int(Decimal(epoch.group(1)) * 1000) - source
                    metrics["location_age_at_log_ms"].append(age)
                    if age < 0:
                        observe("location_source_ahead_of_log_clock", number)
            if fields.get("speed") == "0.0" or fields.get("speed") == "0":
                observe("zero_speed_location", number)
            elif fields.get("speed") is not None:
                observe("nonzero_or_unknown_speed_location", number)
        elif event == "guidance":
            paths = [integer(fields.get(name)) for name in
                     ("acceptedPathId", "currentPathId", "callbackPathId")]
            matching = all(path is not None and path > 0 for path in paths) and len(set(paths)) == 1
            observe("guidance_paths_match" if matching else "guidance_paths_unconfirmed", number)
            if "guidance_elapsed" in state:
                metrics["guidance_callback_interval_ms"].append(elapsed - state["guidance_elapsed"])
            state["guidance_elapsed"] = elapsed
        elif event == "guidance_accepted":
            # Repository acceptance and changed progress are different facts.
            # A new callback with the same zero distance must not renew progress.
            observe("repository_reports_guidance_accepted", number)
            if fields.get("progressChanged") == "true":
                observe("accepted_guidance_progress_changed", number)
            elif fields.get("progressChanged") == "false":
                observe("accepted_guidance_progress_unchanged", number)
            if fields.get("distance") == "0":
                observe("accepted_guidance_zero_distance", number)
        elif event in ("next_icon", "lane_callback"):
            observe("callback_without_independent_source_id", number)

    return {
        "format_version": 1,
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "input_bytes": len(raw),
        "capture_status": "usable_observations" if sdk_rows and not malformed else "insufficient_or_malformed",
        "sdk_rows": sdk_rows, "epoch_sdk_rows": epoch_rows,
        "stream_count": len(streams), "malformed_sdk_lines": malformed,
        "events": dict(sorted(events.items())), "source_status_counts": dict(sorted(sources.items())),
        "observations": dict(sorted(observations.items())),
        "example_line_numbers": dict(sorted(examples.items())),
        "metrics": {name: distribution(values) for name, values in sorted(metrics.items())},
        "acceptance": "not_established",
        "limitations": [
            "Input provenance and scenario coverage require a separate capture record; synthetic input is not device evidence.",
            "Callbacks are logged before validation. Matching request IDs or paths do not prove state acceptance or export.",
            "route_accepted records Repository acceptance; it is not control permission. Independent call tokens and global SDK IDs are distinct.",
            "Missing bindings can mean late callbacks, truncated capture, or callback/log ordering; inspect original lines.",
            "No epoch prefix means no PID separation or wall-clock source-age measurement.",
            "Log time is not source time. Clock changes and logging delay affect measured source ages.",
            "Older guidance logs omit link/icon/remaining-path fields. Callback intervals never substitute for accepted progress freshness; newer guidance_accepted rows report these separately.",
            "Service source-status logs are change-driven, not periodic health samples.",
            "Intervals are pooled observations, not recommended source/progress budgets or proof of unkeyed callback ownership.",
        ],
        "remaining_evidence": [
            "Real device capture with build/SDK identity, clock conditions, scenario times and observed UI/export behavior.",
            "SDK location timestamp semantics and accepted guidance progression under stationary/moving/background/weak-GPS cases.",
            "Independent association for unkeyed callbacks and SDK-initiated reroutes.",
            "Reviewed health budgets, target C3 handover/cancellation tests, and Xcode/XCTest results.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.trace.resolve() == args.report.resolve():
        parser.error("report must not overwrite the input trace")
    try:
        report = analyze(args.trace.read_bytes())
    except (OSError, UnicodeError) as error:
        parser.exit(2, f"Cannot read UTF-8 trace: {error}\n")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{report['capture_status']}: {report['sdk_rows']} SDK rows; acceptance=not_established")
    return 0 if report["capture_status"] == "usable_observations" else 2


if __name__ == "__main__":
    raise SystemExit(main())
