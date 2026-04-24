import argparse
import os
from typing import List

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# TUNING: Figure canvas size (physical export size before LaTeX scaling).
# ---------------------------------------------------------------------------
CM_TO_INCH = 1.0 / 2.54
PAPER_FIGURE_WIDTH_CM = 8.0
PAPER_FIGURE_HEIGHT_CM = 6.0

# ---------------------------------------------------------------------------
# TUNING: Text sizes inside the plot.
# ---------------------------------------------------------------------------
FONT_SIZE = 8
AXIS_LABEL_SIZE = 8
AXIS_TITLE_SIZE = 8
TICK_LABEL_SIZE = 8
FIGURE_TITLE_SIZE = 8

# ---------------------------------------------------------------------------
# TUNING: Bar chart appearance.
# ---------------------------------------------------------------------------
BAR_COLOR = 'skyblue'


def _paper_figure_size():
    """Return figure size in inches for printed two-column papers."""
    return PAPER_FIGURE_WIDTH_CM * CM_TO_INCH, PAPER_FIGURE_HEIGHT_CM * CM_TO_INCH


def _configure_paper_style():
    """Apply style with larger labels for paper figures."""
    plt.style.use('seaborn-v0_8-whitegrid')
    plt.rcParams.update({
        "font.size": FONT_SIZE,
        "axes.labelsize": AXIS_LABEL_SIZE,
        "axes.titlesize": AXIS_TITLE_SIZE,
        "xtick.labelsize": TICK_LABEL_SIZE,
        "ytick.labelsize": TICK_LABEL_SIZE,
        "figure.titlesize": FIGURE_TITLE_SIZE,
    })
    plt.rcParams["pdf.use14corefonts"] = True
    plt.rcParams["font.family"] = "serif"


def _resolve_output_paths(
    output_dir: str | None,
    plot_output: str | None,
    metrics_output: str | None,
) -> tuple[str | None, str | None]:
    """Resolve explicit output paths for the disruption figure and metrics file."""
    resolved_plot = plot_output
    resolved_metrics = metrics_output
    if output_dir:
        resolved_plot = resolved_plot or os.path.join(output_dir, 'disruption_times.pdf')
        resolved_metrics = resolved_metrics or os.path.join(output_dir, 'disruption_metrics.txt')
    if resolved_plot is None and resolved_metrics is None:
        raise ValueError("At least one disruption output path must be specified.")
    return resolved_plot, resolved_metrics


def _ensure_parent_dir(path: str) -> None:
    """Create the parent directory for one output path when needed."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _write_empty_outputs(plot_output: str | None, metrics_output: str | None) -> None:
    """Create empty placeholder outputs for missing or unusable input data."""
    if plot_output is not None:
        _ensure_parent_dir(plot_output)
        open(plot_output, 'w').close()
    if metrics_output is not None:
        _ensure_parent_dir(metrics_output)
        open(metrics_output, 'w').close()


def _write_metrics(metrics_output: str | None, disruption_times: List[float]) -> None:
    """Write per-handoff disruption metrics to the requested text output."""
    if metrics_output is None:
        return
    _ensure_parent_dir(metrics_output)
    with open(metrics_output, 'w', encoding='utf-8') as metrics_file:
        for index, disruption in enumerate(disruption_times, start=1):
            metrics_file.write(f"Handoff {index} Disruption Time: {disruption:.2f} ms\n")


def _write_plot(plot_output: str | None, disruption_times: List[float]) -> None:
    """Write the disruption bar chart to the requested PDF output."""
    if plot_output is None:
        return
    _ensure_parent_dir(plot_output)
    fig, ax = plt.subplots(figsize=_paper_figure_size())
    handoff_labels = [f'Handoff {i+1}' for i in range(len(disruption_times))]
    ax.bar(handoff_labels, disruption_times, color=BAR_COLOR)
    ax.set_ylabel('Service Disruption Time (ms)')
    ax.set_title('Per-Handoff Service Disruption Time')
    ax.set_ylim(bottom=0)
    ax.grid(axis='y', linestyle='--', alpha=0.7)
    fig.tight_layout()
    plt.savefig(plot_output)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Analyze service disruption time from NDN pcap CSV.")
    parser.add_argument('--input', type=str, required=True, help='Input CSV file from tshark.')
    parser.add_argument('--output-dir', type=str, help='Legacy directory used to derive default output files.')
    parser.add_argument('--plot-output', type=str, help='Path to the disruption PDF output.')
    parser.add_argument('--metrics-output', type=str, help='Path to the disruption metrics text output.')
    parser.add_argument('--handoff-times', type=str, required=True, help='Comma-separated list of handoff event times in seconds.')
    parser.add_argument('--prefix', type=str, default='/example/LiveStream', help='Application prefix to include.')
    args = parser.parse_args()

    plot_output, metrics_output = _resolve_output_paths(
        args.output_dir,
        args.plot_output,
        args.metrics_output,
    )
    _configure_paper_style()
    
    try:
        df = pd.read_csv(args.input)
        if df.empty:
            raise pd.errors.EmptyDataError
    except (pd.errors.EmptyDataError, FileNotFoundError):
        print(f"Warning: Input file {args.input} is empty or not found. Skipping analysis.")
        _write_empty_outputs(plot_output, metrics_output)
        return

    df.rename(columns={'frame.time_epoch': 'time', 'ndn.type': 'type', 'ndn.name': 'name'}, inplace=True)
    df = df.dropna().copy()

    # App traffic only
    app_prefix = args.prefix
    df = df[df['name'].astype(str).str.startswith(app_prefix)]
    df = df[~df['name'].astype(str).str.startswith('/localhost/')]
    df = df[~df['name'].astype(str).str.startswith('/localhop/ndn/nlsr/')]

    if df.empty:
        print(f"Warning: No packets under prefix {app_prefix}. Skipping analysis.")
        _write_empty_outputs(plot_output, metrics_output)
        return

    # Convert type to lowercase string
    df['type'] = df['type'].str.lower()
    
    # Get experiment start time (time of the first packet)
    start_time = df['time'].min()
    
    handoffs_relative = [float(t.strip()) for t in args.handoff_times.split(',')]
    handoffs_absolute = [start_time + t for t in handoffs_relative]

    all_data_times = np.sort(df[df['type'] == 'data']['time'].unique())
    disruption_times: List[float] = []

    for t_h in handoffs_absolute:
        # Find the timestamp of the last data packet received *before* or at the handoff time
        data_before_indices = np.where(all_data_times <= t_h)[0]
        if len(data_before_indices) == 0:
            print(f"Warning: No data packets found before handoff at {t_h - start_time:.2f}s. Cannot calculate disruption.")
            continue
        last_data_time_before = all_data_times[data_before_indices[-1]]

        # Find the timestamp of the first data packet received *after* the handoff time
        data_after_indices = np.where(all_data_times > t_h)[0]
        if len(data_after_indices) == 0:
            print(f"Warning: No data packets found after handoff at {t_h - start_time:.2f}s. Cannot calculate disruption.")
            continue
        first_data_time_after = all_data_times[data_after_indices[0]]
        
        disruption = (first_data_time_after - last_data_time_before) * 1000  # in ms
        disruption_times.append(disruption)

    if not disruption_times:
        print("Warning: Could not calculate any disruption times. No plots generated.")
        _write_empty_outputs(plot_output, metrics_output)
        return

    _write_plot(plot_output, disruption_times)
    _write_metrics(metrics_output, disruption_times)
    
    print("Generated service disruption outputs")

if __name__ == '__main__':
    main()
