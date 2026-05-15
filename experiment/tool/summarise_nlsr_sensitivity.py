#!/usr/bin/env python3
"""Summarize baseline profile outputs into a single comparison CSV."""

from __future__ import annotations

import argparse
import csv
import os
import re
from typing import Dict, List, Optional, Tuple


def parse_args() -> argparse.Namespace:
    """Parse profile aggregation arguments."""
    parser = argparse.ArgumentParser(
        description="Summarize baseline profile outputs into one comparison CSV."
    )
    parser.add_argument("--root-dir", required=True, help="Root directory containing per-profile result folders.")
    parser.add_argument(
        "--profiles",
        required=True,
        help="Comma-separated profile directory names in the desired output order.",
    )
    parser.add_argument(
        "--default-profile",
        help="Profile directory name that should be annotated as the default baseline.",
    )
    parser.add_argument("--output", required=True, help="Summary CSV output path.")
    return parser.parse_args()


def _parse_params_file(path: str) -> Dict[str, str]:
    """Parse a key=value parameters file as written by exp.py."""
    params: Dict[str, str] = {}
    if not os.path.exists(path):
        return params
    with open(path, "r", encoding="utf-8") as input_file:
        for raw_line in input_file:
            line = raw_line.strip()
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            params[key.strip()] = value.strip()
    return params


def _parse_disruption_values(path: str) -> List[float]:
    """Read all per-handoff disruption values (ms) from a metrics text file."""
    values: List[float] = []
    if not os.path.exists(path):
        return values
    with open(path, "r", encoding="utf-8") as input_file:
        for raw_line in input_file:
            line = raw_line.strip()
            if "Disruption Time:" not in line:
                continue
            token = line.split("Disruption Time:", 1)[1].strip().split()
            if not token:
                continue
            try:
                values.append(float(token[0]))
            except ValueError:
                continue
    return values


def _parse_overhead_metrics(path: str) -> Dict[str, str]:
    """Parse the `[Full Run]` section of an overhead summary file."""
    metrics: Dict[str, str] = {}
    if not os.path.exists(path):
        return metrics
    current_section: Optional[str] = None
    with open(path, "r", encoding="utf-8") as input_file:
        for raw_line in input_file:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1]
                continue
            if current_section != "Full Run" or ":" not in line:
                continue
            key, value = line.split(":", 1)
            metrics[key.strip()] = value.strip()
    return metrics


def _extract_numeric_prefix(raw: str) -> str:
    """Return the leading numeric token of a `value unit` string, or '' for n/a."""
    tokens = raw.strip().split()
    if not tokens:
        return ""
    token = tokens[0]
    return "" if token.lower() == "n/a" else token


def _aggregate_disruption(values: List[float]) -> Tuple[str, str, str, str]:
    """Return (count, min, max, mean) formatted strings; n/a when no samples."""
    if not values:
        return "0", "n/a", "n/a", "n/a"
    return (
        str(len(values)),
        f"{min(values):.2f}",
        f"{max(values):.2f}",
        f"{sum(values) / len(values):.2f}",
    )


def _profile_prefix(profile: str) -> str:
    """Return the compact profile prefix used as the plot label."""
    return profile.split("-", 1)[0].upper()


def main() -> int:
    """Aggregate per-profile metrics into one summary CSV row per profile."""
    args = parse_args()
    profiles = [profile.strip() for profile in re.split(r"[,\s]+", args.profiles) if profile.strip()]

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    fieldnames: List[str] = [
        "profile",
        "profile_label",
        "hello_interval",
        "adj_lsa_build_interval",
        "routing_calc_interval",
        "handoff_count",
        "disruption_min_ms",
        "disruption_max_ms",
        "disruption_mean_ms",
        "full_run_fcr",
        "full_run_control_bytes",
    ]

    with open(args.output, "w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()

        for profile in profiles:
            profile_dir = os.path.join(args.root_dir, profile)
            params = _parse_params_file(os.path.join(profile_dir, "params.txt"))
            disruption_values = _parse_disruption_values(
                os.path.join(profile_dir, "disruption_metrics.txt")
            )
            overhead = _parse_overhead_metrics(os.path.join(profile_dir, "overhead_total.txt"))

            hello = params.get("neighbors.hello-interval", "n/a")
            adj = params.get("neighbors.adj-lsa-build-interval", "n/a")
            route = params.get("fib.routing-calc-interval", "n/a")
            handoff_count_label, dis_min, dis_max, dis_mean = _aggregate_disruption(disruption_values)

            writer.writerow({
                "profile": profile,
                "profile_label": _profile_prefix(profile),
                "hello_interval": hello,
                "adj_lsa_build_interval": adj,
                "routing_calc_interval": route,
                "handoff_count": handoff_count_label,
                "disruption_min_ms": dis_min,
                "disruption_max_ms": dis_max,
                "disruption_mean_ms": dis_mean,
                "full_run_fcr": _extract_numeric_prefix(overhead.get("Forwarding Cost Ratio", "n/a")),
                "full_run_control_bytes": _extract_numeric_prefix(
                    overhead.get("NLSR Control Bytes", "n/a")
                ),
            })

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
