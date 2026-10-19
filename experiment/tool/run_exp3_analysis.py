#!/usr/bin/env python3
"""Host-side Exp3 analysis. Does not start a VM or modify raw run evidence.

One recorded run:
    python3 experiment/tool/run_exp3_analysis.py p1 r1
    python3 experiment/tool/run_exp3_analysis.py p4 pilot

All fifteen formal runs, after they exist:
    python3 experiment/tool/run_exp3_analysis.py --campaign
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import check_exp3_evidence as checker
import exp3_metrics as exp3
import mobility_event_metrics as metrics
import run_mobility_event_analysis as decoder

ROOT = Path(__file__).resolve().parents[2]
RESULT_ROOT = ROOT / "results" / "extended" / "exp3"
ANALYSIS_ROOT = RESULT_ROOT / "analysis"


def _write_csv(path: Path, fields: Sequence[str], rows: Sequence[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), lineterminator="\n", extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def _refuse_raw_output(run_dir: Path, output_dir: Path) -> None:
    raw = run_dir.resolve()
    derived = output_dir.resolve()
    if derived == raw or raw in derived.parents or derived in raw.parents:
        raise exp3.Exp3AnalysisError(
            f"analysis output {output_dir} must not be inside or above the raw run {run_dir}"
        )


def _read_log(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def _concat_logs(run_dir: Path, filename: str) -> Optional[str]:
    root = run_dir / "minindn-logs"
    if not root.is_dir():
        return None
    parts = []
    for path in sorted(root.glob(f"*/{filename}")):
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    if not parts:
        return None
    return "\n".join(parts)


def load_logs(run_dir: Path, context: exp3.RunContext) -> exp3.LogEvidence:
    daemon = {}
    consumer = {}
    seen = set()
    for window in context.windows:
        if window.producer in seen:
            continue
        seen.add(window.producer)
        daemon[window.producer] = _read_log(run_dir / f"optoflood_{window.producer}.log")
        consumer[window.consumer] = _read_log(run_dir / f"{window.consumer}.log")
    return exp3.LogEvidence(daemon, consumer, _concat_logs(run_dir, "nfd.log"), _concat_logs(run_dir, "nlsr.log"))


def _capture_identity(run_dir: Path, context: exp3.RunContext) -> str:
    lines = [
        f"campaign={context.configuration}",
        f"population={context.population}",
        f"run_id={context.run_id}",
        f"source_kind={context.source_kind}",
        f"source={run_dir.resolve()}",
    ]
    for pcap in exp3.validate_packet_captures(run_dir):
        lines.append(f"{pcap.name}:{pcap.stat().st_size}")
    return "\n".join(lines) + "\n"


def load_packets(run_dir: Path, context: exp3.RunContext, analysis_root: Path) -> List[metrics.Packet]:
    """Decode into the analysis tree. Raw PCAPs are only read."""
    identity = _capture_identity(run_dir, context)
    decoded = analysis_root / "packets" / context.population / context.run_id / "mobility_packets.csv"
    identity_path = decoded.with_suffix(".identity")
    _refuse_raw_output(run_dir, decoded.parent)
    reusable = (
        decoded.is_file()
        and decoded.stat().st_size > 0
        and identity_path.is_file()
        and identity_path.read_text(encoding="utf-8") == identity
    )
    if reusable:
        print(f"reuse decoded packets {decoded}", flush=True)
    else:
        decoder.decode_run(run_dir, decoded)
        identity_path.write_text(identity, encoding="utf-8", newline="\n")
    return metrics.load_packets(str(decoded))


def write_measurement(output_dir: Path, measurement: exp3.Measurement) -> None:
    _write_csv(output_dir / "events.csv", exp3.EVENT_FIELDS, measurement.events)
    _write_csv(output_dir / "prefix_rfv.csv", exp3.PREFIX_RFV_FIELDS, measurement.prefix_rfv)
    _write_csv(output_dir / "network_overhead.csv", exp3.NETWORK_FIELDS, measurement.network)
    _write_csv(output_dir / "run_summary.csv", exp3.SUMMARY_FIELDS, measurement.summary)
    _write_csv(output_dir / "timing_audit.csv", exp3.TIMING_FIELDS, measurement.timing)
    (output_dir / "analysis_audit.txt").write_text(measurement.audit, encoding="utf-8", newline="\n")


def clear_campaign_tables(analysis_root: Path) -> None:
    """Remove aggregate tables so an older complete campaign cannot be reread as current."""
    campaign = analysis_root / "campaign"
    for name in (
        "events.csv",
        "prefix_rfv.csv",
        "network_overhead.csv",
        "run_summary.csv",
        "timing_audit.csv",
        "population_comparison.csv",
    ):
        path = campaign / name
        if path.is_file():
            path.unlink()


def write_campaign_status(path: Path, complete: bool, missing: Sequence[str], detail: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    missing_text = ",".join(missing)
    text = (
        f"complete={'true' if complete else 'false'}\n"
        f"formal_runs={len(exp3.formal_run_keys())}\n"
        f"missing={missing_text}\n"
        f"pilot_included=false\n"
        f"detail={detail}\n"
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def analyze_run(run_dir: Path, output_dir: Path, analysis_root: Path = ANALYSIS_ROOT) -> exp3.Measurement:
    """Measure one full run. Infrastructure failures abort before any derived table is written."""
    _refuse_raw_output(run_dir, output_dir)
    problems = checker.inspect_run(run_dir)
    if problems:
        raise exp3.Exp3AnalysisError(
            "infrastructure evidence is invalid:\n" + "\n".join(problems)
        )
    context = exp3.load_run_context(run_dir)
    measurement = exp3.measure_run(load_packets(run_dir, context, analysis_root), context, load_logs(run_dir, context))
    write_measurement(output_dir, measurement)
    print(
        f"Exp3 analysis wrote {output_dir} "
        f"({context.population} {context.run_id}, {context.source_kind}, {len(measurement.events)} handoffs)",
        flush=True,
    )
    return measurement


def analyze_campaign(result_root: Path = RESULT_ROOT, analysis_root: Path = ANALYSIS_ROOT) -> int:
    """Aggregate formal P=1/P=2/P=4 runs. An incomplete campaign is reported and not labelled final."""
    status_path = analysis_root / "campaign" / "campaign_status.txt"
    missing = exp3.missing_formal_runs(result_root)
    if missing:
        clear_campaign_tables(analysis_root)
        write_campaign_status(status_path, False, missing, "formal run evidence is absent")
        print("Exp3 formal campaign is incomplete:", file=sys.stderr)
        for item in missing:
            print(f"  missing {item}", file=sys.stderr)
        print("No formal comparison table was written.", file=sys.stderr)
        return 2
    combined_events: List[Dict[str, str]] = []
    combined_prefix: List[Dict[str, str]] = []
    combined_network: List[Dict[str, str]] = []
    combined_summary: List[Dict[str, str]] = []
    combined_timing: List[Dict[str, str]] = []
    try:
        for population, run_id in exp3.formal_run_keys():
            measurement = analyze_run(
                result_root / population / run_id,
                analysis_root / population / run_id,
                analysis_root,
            )
            if measurement.events and measurement.events[0]["source_kind"] != "formal":
                raise exp3.Exp3AnalysisError(f"{population}/{run_id} is not a formal run")
            combined_events.extend(measurement.events)
            combined_prefix.extend(measurement.prefix_rfv)
            combined_network.extend(measurement.network)
            combined_summary.extend(measurement.summary)
            combined_timing.extend(measurement.timing)
        comparison = exp3.population_comparison(combined_summary, combined_network)
    except (exp3.Exp3AnalysisError, metrics.MobilityMetricError) as error:
        clear_campaign_tables(analysis_root)
        write_campaign_status(status_path, False, [], str(error).replace("\n", " "))
        print(f"Exp3 campaign analysis failed: {error}", file=sys.stderr)
        return 1
    campaign_dir = analysis_root / "campaign"
    _write_csv(campaign_dir / "events.csv", exp3.EVENT_FIELDS, combined_events)
    _write_csv(campaign_dir / "prefix_rfv.csv", exp3.PREFIX_RFV_FIELDS, combined_prefix)
    _write_csv(campaign_dir / "network_overhead.csv", exp3.NETWORK_FIELDS, combined_network)
    _write_csv(campaign_dir / "run_summary.csv", exp3.SUMMARY_FIELDS, combined_summary)
    _write_csv(campaign_dir / "timing_audit.csv", exp3.TIMING_FIELDS, combined_timing)
    _write_csv(campaign_dir / "population_comparison.csv", exp3.COMPARISON_FIELDS, comparison)
    write_campaign_status(status_path, True, [], "fifteen formal runs measured; pilot excluded")
    print(f"Exp3 formal campaign analysis wrote {campaign_dir}", flush=True)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if arguments == ["--campaign"]:
            return analyze_campaign()
        if len(arguments) != 2:
            print(
                "usage: run_exp3_analysis.py <p1|p2|p4> <r1|r2|r3|r4|r5|pilot>\n"
                "       run_exp3_analysis.py --campaign",
                file=sys.stderr,
            )
            return 2
        population, run_id = arguments
        relative = exp3.analysis_relative(population, run_id)
        analyze_run(RESULT_ROOT / population / run_id, ANALYSIS_ROOT / relative, ANALYSIS_ROOT)
    except (exp3.Exp3AnalysisError, metrics.MobilityMetricError) as error:
        print(f"Exp3 analysis failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
