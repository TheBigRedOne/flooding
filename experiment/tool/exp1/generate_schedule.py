"""Write the one seeded Exp1 handoff schedule shared by the nine cells."""

from __future__ import annotations

import random
from pathlib import Path
from typing import List, Optional, Sequence

from experiment.tool.common.handoff_schedule import format_intervals

EXP1_HANDOFF_COUNT = 8
EXP1_INTERVAL_COUNT = EXP1_HANDOFF_COUNT + 1
EXP1_INTERVAL_BASE_S = 90.0
EXP1_INTERVAL_JITTER_S = 60.0


def sample_seeded_intervals(
    seed: int,
    count: int = EXP1_INTERVAL_COUNT,
    base_seconds: float = EXP1_INTERVAL_BASE_S,
    jitter_seconds: float = EXP1_INTERVAL_JITTER_S,
) -> List[float]:
    """Return count durations from base + Uniform(0, jitter), in sample order.

    The first count-1 values are pre-handoff waits and the last is the tail.
    random.Random(seed) is the generator, so the same seed repeats the list.
    """
    if seed < 0:
        raise ValueError(f"schedule seed must be non-negative: {seed}")
    if count != EXP1_INTERVAL_COUNT:
        raise ValueError(f"a handoff schedule has {EXP1_INTERVAL_COUNT} intervals, not {count}")
    if base_seconds < 0 or jitter_seconds < 0:
        raise ValueError("schedule base and jitter must be non-negative")
    generator = random.Random(seed)
    return [base_seconds + generator.uniform(0.0, jitter_seconds) for _ in range(count)]


def write_seeded_schedule(directory: Path, run_id: str, seed: int) -> None:
    """Write run_id.seed and the formatted interval list. The seed is not resampled later."""
    if not run_id or any(separator in run_id for separator in ("/", "\\")):
        raise ValueError(f"invalid repetition id: {run_id}")
    values = sample_seeded_intervals(seed)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{run_id}.seed").write_text(f"{int(seed)}\n", encoding="utf-8", newline="\n")
    (directory / f"{run_id}.txt").write_text(format_intervals(values) + "\n", encoding="utf-8", newline="\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Write one seeded Exp1 handoff schedule.")
    parser.add_argument("--directory", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--seed", required=True, type=int)
    args = parser.parse_args(list(argv) if argv is not None else None)
    write_seeded_schedule(Path(args.directory), args.run_id, args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
