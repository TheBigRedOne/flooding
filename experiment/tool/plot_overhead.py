import pandas as pd
import argparse
import os
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

CM_TO_INCH = 1.0 / 2.54
PAPER_FIGURE_WIDTH_CM = 8.8
PAPER_FIGURE_HEIGHT_CM = 5.4


def _paper_figure_size():
    """Return figure size in inches for single-column paper figures."""
    return PAPER_FIGURE_WIDTH_CM * CM_TO_INCH, PAPER_FIGURE_HEIGHT_CM * CM_TO_INCH


def _configure_paper_style():
    """Apply style with larger labels for paper readability."""
    plt.style.use('seaborn-v0_8-whitegrid')
    plt.rcParams.update({
        "font.size": 9,
        "axes.labelsize": 9,
        "axes.titlesize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 8,
        "figure.titlesize": 9,
    })

def main():
    parser = argparse.ArgumentParser(description="Analyze and plot flooding overhead from NDN pcap CSV.")
    parser.add_argument('--input', type=str, required=True, help='Input CSV file from tshark.')
    parser.add_argument('--output-dir', type=str, default='.', help='Directory to save output files.')
    parser.add_argument('--handoff-times', type=str, help='Comma-separated list of handoff event times in seconds.')
    parser.add_argument('--window', type=int, default=10, help='Time window in seconds after a handoff for analysis.')
    parser.add_argument('--prefix', type=str, default='/example/LiveStream', help='Application prefix to count as overhead.')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    _configure_paper_style()

    try:
        df = pd.read_csv(args.input)
        if df.empty:
            raise pd.errors.EmptyDataError
    except (pd.errors.EmptyDataError, FileNotFoundError):
        print(f"Warning: Input file {args.input} is empty or not found. Skipping.")
        open(os.path.join(args.output_dir, 'overhead_timeseries.pdf'), 'w').close()
        open(os.path.join(args.output_dir, 'overhead_total.txt'), 'w').close()
        return
        
    df.rename(columns={'frame.time_epoch': 'time', 'ndn.type': 'type', 'ndn.name': 'name'}, inplace=True)
    df = df.dropna().copy()

    # Interest traffic only
    app_prefix = args.prefix
    df = df[df['name'].astype(str).str.startswith(app_prefix)]
    df = df[~df['name'].astype(str).str.startswith('/localhost/')]
    df = df[~df['name'].astype(str).str.startswith('/localhop/ndn/nlsr/')]

    df['type'] = df['type'].str.lower()
    interests_df = df[df['type'] == 'interest'].copy()
    
    if interests_df.empty:
        print("Warning: No interest packets found. Cannot generate overhead plot.")
        open(os.path.join(args.output_dir, 'overhead_timeseries.pdf'), 'w').close()
        open(os.path.join(args.output_dir, 'overhead_total.txt'), 'w').close()
        return

    start_time = df['time'].min()
    interests_df['relative_time'] = interests_df['time'] - start_time
    
    # --- (R3) Flooding overhead and scope (K3) ---
    # Convert time to datetime objects for resampling
    interests_df['timestamp'] = pd.to_datetime(interests_df['relative_time'], unit='s')
    interests_df.set_index('timestamp', inplace=True)
    
    # Resample to get packets per second
    packets_per_second = interests_df.resample('1s').size()
    
    # Time series plot of flooded packets per second
    fig, ax = plt.subplots(figsize=_paper_figure_size())
    packets_per_second.plot(ax=ax, label='Interests per Second', color='crimson')
    
    total_overhead = len(interests_df)

    if args.handoff_times:
        handoffs = [float(t.strip()) for t in args.handoff_times.split(',')]
        for i, t in enumerate(handoffs):
            label = f'Handoff Window' if i == 0 else None
            ax.axvspan(t, t + args.window, color='orange', alpha=0.3, label=label)
    
    ax.set_xlabel('Time (seconds)')
    ax.set_ylabel('Flooded Packets per Second')
    ax.set_title('Flooding Overhead Over Time')
    ax.set_ylim(bottom=0)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=6, integer=True))
    ax.legend()
    ax.grid(True, which="both", ls="--")
    fig.tight_layout()
    plt.savefig(os.path.join(args.output_dir, 'overhead_timeseries.pdf'))
    plt.close(fig)

    # Save the total overhead count to a text file
    total_output_file = os.path.join(args.output_dir, 'overhead_total.txt')
    with open(total_output_file, 'w') as f:
        f.write(f"Total Flooded Interests: {total_overhead}\n")

    print(f"Generated R3 (Flooding Overhead) plot and metrics in {args.output_dir}")

if __name__ == '__main__':
    main()
