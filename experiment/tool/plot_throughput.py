import argparse
import csv
import os
from collections import defaultdict
from typing import Dict, Iterable, List, Tuple

import matplotlib.pyplot as plt


def _load_packets(csv_path: str) -> List[Tuple[float, int]]:
    """Load (time, length) tuples from a tshark CSV."""
    with open(csv_path, "r", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        required = {"frame.time_epoch", "frame.len"}
        if not required.issubset(reader.fieldnames or set()):
            raise ValueError("Missing frame.time_epoch or frame.len; cannot compute throughput.")

        packets: List[Tuple[float, int]] = []
        for row in reader:
            try:
                time_val = float(row["frame.time_epoch"])
                length_val = int(row["frame.len"])
            except (ValueError, KeyError):
                continue
            packets.append((time_val, length_val))

    if not packets:
        raise ValueError("No valid rows available; throughput cannot be plotted.")

    return packets


def _aggregate_per_second(packets: Iterable[Tuple[float, int]]) -> Dict[int, int]:
    """Accumulate bytes per whole-second timestamp."""
    throughput: Dict[int, int] = defaultdict(int)
    for time_val, length_val in packets:
        second = int(time_val)
        throughput[second] += length_val
    return throughput


def _percentile(values: List[int], percentile: float) -> float:
    """Compute percentile with linear interpolation."""
    if not values:
        return 0.0
    if percentile <= 0:
        return float(min(values))
    if percentile >= 100:
        return float(max(values))

    sorted_vals = sorted(values)
    rank = (percentile / 100) * (len(sorted_vals) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_vals) - 1)
    fraction = rank - lower
    return sorted_vals[lower] + (sorted_vals[upper] - sorted_vals[lower]) * fraction


def _write_metrics(out_dir: str, values: List[int], seconds: List[int]) -> None:
    """Write throughput metrics to throughput_metrics.txt."""
    if not values or not seconds:
        avg = peak = p95 = total_bytes = 0
        duration = 0
    else:
        total_bytes = sum(values)
        duration = max(seconds[-1] - seconds[0] + 1, 1)
        avg = total_bytes / duration
        peak = max(values)
        p95 = _percentile(values, 95)

    metrics_path = os.path.join(out_dir, "throughput_metrics.txt")
    with open(metrics_path, "w", encoding="utf-8") as metrics_file:
        metrics_file.write(f"Average: {avg:.2f} bytes/s\n")
        metrics_file.write(f"Peak: {peak:.2f} bytes/s\n")
        metrics_file.write(f"P95: {p95:.2f} bytes/s\n")
        metrics_file.write(f"TotalBytes: {int(total_bytes)}\n")
        metrics_file.write(f"Duration: {duration:.2f} s\n")


def _safe_empty_outputs(out_dir: str) -> None:
    """Create empty outputs when input data is unusable."""
    os.makedirs(out_dir, exist_ok=True)
    metrics_path = os.path.join(out_dir, "throughput_metrics.txt")
    with open(metrics_path, "w", encoding="utf-8") as metrics_file:
        metrics_file.write("Average: 0.00 bytes/s\n")
        metrics_file.write("Peak: 0.00 bytes/s\n")
        metrics_file.write("P95: 0.00 bytes/s\n")
        metrics_file.write("TotalBytes: 0\n")
        metrics_file.write("Duration: 0.00 s\n")
    fig, _ = plt.subplots(figsize=(10, 5))
    empty_pdf = os.path.join(out_dir, "throughput_timeseries.pdf")
    fig.savefig(empty_pdf)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot throughput from tshark CSV.")
    parser.add_argument("--input", required=True, help="Path to tshark CSV.")
    parser.add_argument("--output-dir", required=True, help="Directory to write outputs.")
    parser.add_argument("--handoff-times", help="Comma-separated handoff times in seconds (relative).")
    parser.add_argument("--window", type=int, default=10, help="Shaded window length after each handoff (seconds).")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    if not os.path.exists(args.input):
        _safe_empty_outputs(args.output_dir)
        return

    try:
        packets = _load_packets(args.input)
    except Exception:
        _safe_empty_outputs(args.output_dir)
        return

    per_second = _aggregate_per_second(packets)
    if not per_second:
        _safe_empty_outputs(args.output_dir)
        return

    sorted_seconds = sorted(per_second.keys())
    start_second = sorted_seconds[0]
    rel_times = [sec - start_second for sec in sorted_seconds]
    values = [per_second[sec] for sec in sorted_seconds]

    _write_metrics(args.output_dir, values, sorted_seconds)

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(rel_times, values, color="steelblue", label="Bytes per second")

    if args.handoff_times:
        handoffs = [float(t.strip()) for t in args.handoff_times.split(",") if t.strip()]
        for idx, handoff in enumerate(handoffs):
            start = handoff
            end = handoff + args.window
            label = "Handoff Window" if idx == 0 else None
            ax.axvspan(start, end, color="orange", alpha=0.3, label=label)

    ax.set_xlabel("Time (seconds)")
    ax.set_ylabel("Throughput (bytes/s)")
    ax.set_title("Throughput Over Time")
    ax.legend()
    ax.grid(True)

    max_time = int(max(rel_times)) if rel_times else 0
    tick_step = 20 if max_time >= 20 else max(1, max_time or 1)
    ax.set_xticks(list(range(0, max_time + tick_step, tick_step)))
    ax.get_xaxis().get_major_formatter().set_useOffset(False)

    fig.tight_layout()
    output_pdf = os.path.join(args.output_dir, "throughput_timeseries.pdf")
    plt.savefig(output_pdf)
    plt.close(fig)


if __name__ == "__main__":
    main()
