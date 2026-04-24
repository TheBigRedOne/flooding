import pandas as pd
import argparse
import os
import bisect
import matplotlib.pyplot as plt

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
# TUNING: Bar chart and annotation appearance.
# ---------------------------------------------------------------------------
HANDOFF_BAR_COLOR = 'orangered'
STEADY_BAR_COLOR = 'deepskyblue'
VALUE_LABEL_OFFSET_MIN = 0.02
VALUE_LABEL_OFFSET_RATIO = 0.025
LOSS_Y_TOP_PADDING = 0.08
TITLE_PAD_POINTS = 4.0


def _paper_figure_size():
    """Return figure size in inches for single-column paper figures."""
    return PAPER_FIGURE_WIDTH_CM * CM_TO_INCH, PAPER_FIGURE_HEIGHT_CM * CM_TO_INCH


def _configure_paper_style():
    """Apply style with larger labels for paper readability."""
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
    """Resolve explicit output paths for the loss figure and metrics file."""
    resolved_plot = plot_output
    resolved_metrics = metrics_output
    if output_dir:
        resolved_plot = resolved_plot or os.path.join(output_dir, 'loss_comparison.pdf')
        resolved_metrics = resolved_metrics or os.path.join(output_dir, 'loss_ratio.txt')
    if resolved_plot is None and resolved_metrics is None:
        raise ValueError("At least one loss output path must be specified.")
    return resolved_plot, resolved_metrics


def _ensure_parent_dir(path: str) -> None:
    """Create the parent directory for one output path when needed."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _write_empty_outputs(plot_output: str | None, metrics_output: str | None) -> None:
    """Create empty or default outputs when the input data is unusable."""
    if metrics_output is not None:
        _ensure_parent_dir(metrics_output)
        with open(metrics_output, 'w', encoding='utf-8') as output_file:
            output_file.write("Handoff Window Ratio: 1.0\n")
            output_file.write("Steady State Ratio: 1.0\n")
    if plot_output is not None:
        _ensure_parent_dir(plot_output)
        open(plot_output, 'w').close()


def _write_metrics(
    metrics_output: str | None,
    handoff_ratio: float,
    steady_state_ratio: float,
    handoff_total: int,
    handoff_unmet: int,
    steady_total: int,
    steady_unmet: int,
    deadline: float,
) -> None:
    """Write the unmet-interest metrics to the requested text output."""
    if metrics_output is None:
        return
    _ensure_parent_dir(metrics_output)
    with open(metrics_output, 'w', encoding='utf-8') as output_file:
        output_file.write(f"Handoff Window Ratio: {handoff_ratio:.4f}\n")
        output_file.write(f"Steady State Ratio: {steady_state_ratio:.4f}\n")
        output_file.write(f"Handoff Requests: {handoff_total}\n")
        output_file.write(f"Handoff Unmet: {handoff_unmet}\n")
        output_file.write(f"Steady Requests: {steady_total}\n")
        output_file.write(f"Steady Unmet: {steady_unmet}\n")
        output_file.write(f"Deadline Seconds: {deadline:.2f}\n")


def _write_plot(plot_output: str | None, ratios: list[float], deadline: float) -> None:
    """Write the unmet-interest comparison figure to the requested PDF output."""
    if plot_output is None:
        return
    _ensure_parent_dir(plot_output)
    fig, ax = plt.subplots(figsize=_paper_figure_size())
    labels = ['During\nHandoffs', 'Steady\nState']
    max_ratio = max(ratios) if ratios else 0.0
    label_offset = max(VALUE_LABEL_OFFSET_MIN, VALUE_LABEL_OFFSET_RATIO * max_ratio)
    ax.bar(labels, ratios, color=[HANDOFF_BAR_COLOR, STEADY_BAR_COLOR])
    ax.set_ylabel('Unmet-Interest Ratio')
    ax.set_title(
        f'Comparison of Unmet-Interest Ratio (deadline={deadline:.1f}s)',
        pad=TITLE_PAD_POINTS,
    )
    ax.set_ylim(0, max(1.0 + LOSS_Y_TOP_PADDING, max_ratio + label_offset + LOSS_Y_TOP_PADDING))
    ax.grid(axis='y', linestyle='--', alpha=0.7)

    for i, value in enumerate(ratios):
        ax.text(i, value + label_offset, f"{value:.3f}", ha='center', va='bottom')

    fig.tight_layout()
    fig.savefig(plot_output, bbox_inches='tight')
    plt.close(fig)


def normalize_name(name: str) -> str:
    """
    Keep only the canonical data name part before signer metadata.
    Example:
      /example/LiveStream/54=%01,/localhost/operator/KEY/... -> /example/LiveStream/54=%01
    """
    return str(name).split(',', 1)[0].strip()


def calculate_unmet_ratio(requests_df: pd.DataFrame) -> float:
    """Calculates unmet-interest ratio from request records containing `met` bool."""
    total = len(requests_df)
    if total == 0:
        return 0.0
    unmet = int((~requests_df['met']).sum())
    return unmet / total

def main():
    parser = argparse.ArgumentParser(description="Calculate and compare Unmet-Interest ratio from NDN pcap CSV.")
    parser.add_argument('--input', type=str, required=True, help='Input CSV file from tshark.')
    parser.add_argument('--output-dir', type=str, help='Legacy directory used to derive default output files.')
    parser.add_argument('--plot-output', type=str, help='Path to the loss comparison PDF output.')
    parser.add_argument('--metrics-output', type=str, help='Path to the unmet-interest metrics text output.')
    parser.add_argument('--handoff-times', type=str, required=True, help='Comma-separated list of handoff event times.')
    parser.add_argument('--window', type=float, default=10.0, help='Analysis window duration in seconds after each handoff.')
    parser.add_argument('--prefix', type=str, default='/example/LiveStream', help='Application prefix to include.')
    parser.add_argument('--deadline', type=float, default=6.0,
                        help='Deadline in seconds to consider an Interest satisfied by Data.')
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
        print(f"Warning: Input file {args.input} is empty or not found. No loss calculated.")
        _write_empty_outputs(plot_output, metrics_output)
        return

    df.rename(columns={'frame.time_epoch': 'time', 'ndn.type': 'type', 'ndn.name': 'name'}, inplace=True)
    df = df.dropna(subset=['time', 'type', 'name']).copy()
    df['time'] = pd.to_numeric(df['time'], errors='coerce')
    df = df.dropna(subset=['time'])
    app_prefix = args.prefix
    df = df[df['name'].astype(str).str.startswith(app_prefix)]
    df = df[~df['name'].astype(str).str.startswith('/localhost/')]
    df = df[~df['name'].astype(str).str.startswith('/localhop/ndn/nlsr/')]
    if df.empty:
        print(f"Warning: No packets under prefix {app_prefix}. No loss calculated.")
        _write_empty_outputs(plot_output, metrics_output)
        return

    df['type'] = df['type'].str.lower()
    df = df[df['type'].isin(['interest', 'data'])].copy()
    if df.empty:
        print("Warning: No Interest/Data packets after filtering. No loss calculated.")
        _write_empty_outputs(plot_output, metrics_output)
        return
    df['base_name'] = df['name'].apply(normalize_name)

    start_time = df['time'].min()

    handoffs = [float(t.strip()) for t in args.handoff_times.split(',')]

    interests = df[df['type'] == 'interest'][['time', 'base_name']].sort_values('time')
    data = df[df['type'] == 'data'][['time', 'base_name']].sort_values('time')
    if interests.empty:
        print("Warning: No Interests after filtering. No loss calculated.")
        _write_empty_outputs(plot_output, metrics_output)
        return

    first_requests = interests.groupby('base_name', as_index=False)['time'].min()
    data_times_by_name = {
        name: grp['time'].tolist()
        for name, grp in data.groupby('base_name')
    }

    records = []
    for _, row in first_requests.iterrows():
        name = row['base_name']
        req_time = float(row['time'])
        data_times = data_times_by_name.get(name, [])
        idx = bisect.bisect_left(data_times, req_time)
        data_time = data_times[idx] if idx < len(data_times) else None
        met = data_time is not None and (data_time - req_time) <= args.deadline
        records.append({
            'base_name': name,
            'request_time': req_time,
            'data_time': data_time,
            'met': met,
            'relative_time': req_time - start_time,
        })
    requests_df = pd.DataFrame.from_records(records)

    # --- (R2) Unmet-Interest ratio (K2) ---
    handoff_mask = pd.Series(False, index=requests_df.index)
    for t_h in handoffs:
        window_start = t_h
        window_end = t_h + args.window
        handoff_mask |= ((requests_df['relative_time'] >= window_start) &
                         (requests_df['relative_time'] < window_end))

    handoff_df = requests_df[handoff_mask]
    steady_state_df = requests_df[~handoff_mask]

    handoff_ratio = calculate_unmet_ratio(handoff_df)
    steady_state_ratio = calculate_unmet_ratio(steady_state_df)
    handoff_total = len(handoff_df)
    steady_total = len(steady_state_df)
    handoff_unmet = int((~handoff_df['met']).sum()) if handoff_total else 0
    steady_unmet = int((~steady_state_df['met']).sum()) if steady_total else 0

    ratios = [handoff_ratio, steady_state_ratio]
    _write_metrics(
        metrics_output,
        handoff_ratio,
        steady_state_ratio,
        handoff_total,
        handoff_unmet,
        steady_total,
        steady_unmet,
        args.deadline,
    )
    _write_plot(plot_output, ratios, args.deadline)

    print("Generated unmet-interest outputs")

if __name__ == '__main__':
    main()
