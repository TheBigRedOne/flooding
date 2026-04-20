#!/usr/bin/env python3
"""Load and validate baseline profile definitions.

Purpose:
    Provide one canonical source for baseline parameter-set configuration and
    expose a small CLI for Makefile integration.

Interface:
    python3 experiment/tool/baseline_profiles.py --config <json> \
        print-default-dir --root-dir <dir>
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class BaselineProfile:
    """Structured baseline profile definition loaded from JSON configuration."""

    id: str
    directory_name: str
    hello_interval: int
    adj_lsa_build_interval: int
    routing_calc_interval: int
    is_default: bool

    @property
    def display_label(self) -> str:
        """Return the human-readable parameter label used in plots."""
        return (
            f"{self.hello_interval}/"
            f"{self.adj_lsa_build_interval}/"
            f"{self.routing_calc_interval}"
        )


def _parse_profile(entry: dict) -> BaselineProfile:
    """Convert one JSON object into a validated baseline profile."""
    return BaselineProfile(
        id=str(entry["id"]),
        directory_name=str(entry["directory_name"]),
        hello_interval=int(entry["hello_interval"]),
        adj_lsa_build_interval=int(entry["adj_lsa_build_interval"]),
        routing_calc_interval=int(entry["routing_calc_interval"]),
        is_default=bool(entry.get("is_default", False)),
    )


def load_profiles(config_path: str) -> List[BaselineProfile]:
    """Load and validate the full ordered baseline profile list."""
    with open(config_path, "r", encoding="utf-8") as input_file:
        payload = json.load(input_file)

    if "profiles" not in payload or not isinstance(payload["profiles"], list):
        raise ValueError("baseline profile config must contain a 'profiles' list.")

    profiles = [_parse_profile(entry) for entry in payload["profiles"]]
    if not profiles:
        raise ValueError("baseline profile config must define at least one profile.")

    ids = [profile.id for profile in profiles]
    if len(ids) != len(set(ids)):
        raise ValueError("baseline profile ids must be unique.")

    directory_names = [profile.directory_name for profile in profiles]
    if len(directory_names) != len(set(directory_names)):
        raise ValueError("baseline profile directory names must be unique.")

    default_profiles = [profile for profile in profiles if profile.is_default]
    if len(default_profiles) != 1:
        raise ValueError("baseline profile config must define exactly one default profile.")

    return profiles


def get_default_profile(profiles: List[BaselineProfile]) -> BaselineProfile:
    """Return the unique default baseline profile from the ordered list."""
    for profile in profiles:
        if profile.is_default:
            return profile
    raise ValueError("missing default baseline profile.")


def get_result_dir(root_dir: str, profile: BaselineProfile) -> Path:
    """Return the host-side result directory for one profile."""
    return Path(root_dir) / profile.directory_name


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for Makefile-oriented helper commands."""
    parser = argparse.ArgumentParser(
        description="Load and query baseline profile configuration."
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the baseline profile JSON configuration file.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    print_default_dir = subparsers.add_parser(
        "print-default-dir",
        help="Print the default profile result directory under the given root.",
    )
    print_default_dir.add_argument(
        "--root-dir",
        required=True,
        help="Root directory under which baseline result directories are created.",
    )
    return parser.parse_args()


def main() -> int:
    """Execute the requested helper command."""
    args = parse_args()
    profiles = load_profiles(args.config)

    if args.command == "print-default-dir":
        print(get_result_dir(args.root_dir, get_default_profile(profiles)).as_posix())
        return 0

    raise ValueError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
