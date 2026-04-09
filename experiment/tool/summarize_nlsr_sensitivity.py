#!/usr/bin/env python3
"""Summarize NLSR sensitivity experiment outputs into a single CSV."""

from __future__ import annotations

import argparse
import csv
import os
from typing import Dict, List, Optional


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize NLSR sensitivity experiment outputs into one CSV."
    )
    parser.add_argument("--root-dir", required=True, help="Root directory containing per-profile result folders.")
    parser.add_argument(
        "--profiles",
        required=True,
        help="Comma-separated profile directory names in the desired output order.",
    )
    parser.add_argument("--output", required=True, help="Summary CSV output path.")
    return parser.parse_args()


def _parse_params_file(path: str) -> Dict[str, str]:
    params: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as input_file:
        for raw_line in input_file:
            line = raw_line.strip()
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            params[key.strip()] = value.strip()
    return params


def _parse_disruption_metrics(path: str) -> Dict[str, str]:
    metrics: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as input_file:
        for raw_line in input_file:
            line = raw_line.strip()
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            metrics[key.strip()] = value.strip()
    return metrics


def _require_metric(metrics: Dict[str, str], key: str, path: str) -> str:
    if key not in metrics:
        raise ValueError(
            f"Missing '{key}' in {path}. Re-run the per-profile plotting step so "
            "disruption_metrics.txt is regenerated in the current format."
        )
    return metrics[key]


def _parse_overhead_metrics(path: str) -> Dict[str, str]:
    metrics: Dict[str, str] = {}
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
    tokens = raw.strip().split()
    if not tokens:
        return ""
    token = tokens[0]
    return "" if token.lower() == "n/a" else token


def main() -> int:
    args = parse_args()
    profiles = [profile.strip() for profile in args.profiles.split(",") if profile.strip()]

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    fieldnames: List[str] = [
        "profile",
        "profile_label",
        "hello_interval",
        "adj_lsa_build_interval",
        "routing_calc_interval",
        "handoff_1_disruption_ms",
        "handoff_2_disruption_ms",
        "full_run_fcr",
        "full_run_control_bytes",
    ]

    with open(args.output, "w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()

        for profile in profiles:
            profile_dir = os.path.join(args.root_dir, profile)
            params = _parse_params_file(os.path.join(profile_dir, "params.txt"))
            disruption = _parse_disruption_metrics(os.path.join(profile_dir, "disruption_metrics.txt"))
            overhead = _parse_overhead_metrics(os.path.join(profile_dir, "overhead_total.txt"))

            hello = params["neighbors.hello-interval"]
            adj = params["neighbors.adj-lsa-build-interval"]
            route = params["fib.routing-calc-interval"]
            writer.writerow({
                "profile": profile,
                "profile_label": f"{hello}/{adj}/{route}",
                "hello_interval": hello,
                "adj_lsa_build_interval": adj,
                "routing_calc_interval": route,
                "handoff_1_disruption_ms": _extract_numeric_prefix(
                    _require_metric(
                        disruption,
                        "Handoff 1 Disruption Time",
                        os.path.join(profile_dir, "disruption_metrics.txt"),
                    )
                ),
                "handoff_2_disruption_ms": _extract_numeric_prefix(
                    _require_metric(
                        disruption,
                        "Handoff 2 Disruption Time",
                        os.path.join(profile_dir, "disruption_metrics.txt"),
                    )
                ),
                "full_run_fcr": _extract_numeric_prefix(
                    overhead["Forwarding Cost Ratio"]
                ),
                "full_run_control_bytes": _extract_numeric_prefix(
                    overhead["NLSR Control Bytes"]
                ),
            })

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
