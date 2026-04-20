#!/usr/bin/env python3
"""Run baseline result collection for all configured parameter sets.

Purpose:
    Read the baseline profile configuration and invoke the shared result
    collection workflow once per configured profile.

Interface:
    PROVIDER=<provider> [MOBILITY_LOG_NODES="<nodes>"] \
    python3 scripts/run-baseline-profiles.py \
        --config <json> --results-root <dir> --ssh-config <file> \
        --box-path <path> --remote-dir <dir>
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_DIR = REPO_ROOT / "experiment" / "tool"
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from baseline_profiles import get_result_dir, load_profiles  # noqa: E402


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for baseline result collection."""
    parser = argparse.ArgumentParser(
        description="Run baseline result collection for all configured parameter sets."
    )
    parser.add_argument("--config", required=True, help="Baseline profile JSON configuration.")
    parser.add_argument("--results-root", required=True, help="Root directory for baseline results.")
    parser.add_argument("--vagrant-dir", required=True, help="Vagrant working directory.")
    parser.add_argument("--host-alias", required=True, help="Host alias used in ssh-config.")
    parser.add_argument("--ssh-config", required=True, help="SSH config file path.")
    parser.add_argument("--box-env-name", required=True, help="Environment variable carrying the box path.")
    parser.add_argument("--box-path", required=True, help="Baseline box path.")
    parser.add_argument("--source-dir", required=True, help="Source directory to sync into the VM.")
    parser.add_argument("--remote-dir", required=True, help="Remote repository root inside the VM.")
    parser.add_argument("--experiment-subdir", required=True, help="Experiment subdirectory executed inside the VM.")
    parser.add_argument("--run-script", required=True, help="Path to the shared collection shell script.")
    return parser.parse_args()


def run_profile_collection(args: argparse.Namespace) -> None:
    """Run the shared collection workflow once per configured baseline profile."""
    profiles = load_profiles(args.config)
    results_root = Path(args.results_root)
    results_root.mkdir(parents=True, exist_ok=True)

    for profile in profiles:
        result_dir = get_result_dir(args.results_root, profile)
        result_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["CLEAR_LOCAL_RESULTS"] = "1"
        env["NLSR_HELLO_INTERVAL"] = str(profile.hello_interval)
        env["NLSR_ADJ_LSA_BUILD_INTERVAL"] = str(profile.adj_lsa_build_interval)
        env["NLSR_ROUTING_CALC_INTERVAL"] = str(profile.routing_calc_interval)
        env["NLSR_TUNING_PROFILE"] = profile.directory_name

        subprocess.run(
            [
                "sh",
                args.run_script,
                args.vagrant_dir,
                args.host_alias,
                args.ssh_config,
                args.box_env_name,
                args.box_path,
                args.source_dir,
                args.remote_dir,
                args.experiment_subdir,
                str(result_dir),
                "--require-params",
            ],
            check=True,
            env=env,
        )


def main() -> int:
    """Execute configured baseline profile collection."""
    args = parse_args()
    run_profile_collection(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
