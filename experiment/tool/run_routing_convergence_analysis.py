#!/usr/bin/env python3
"""Host-side routing-convergence analysis.

Reads existing handoff records, NLSR logs, NFD logs, and mobility packet
tables. It does not start a virtual machine or change service-metric results.
"""

from __future__ import annotations

import argparse

import routing_convergence_metrics as routing


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure routing convergence from existing results.")
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="Also write LSA-lead, stage, and network-minus-service figures under results/routing/.",
    )
    args = parser.parse_args()
    return routing.main(diagnostic=args.diagnostic)


if __name__ == "__main__":
    raise SystemExit(main())
