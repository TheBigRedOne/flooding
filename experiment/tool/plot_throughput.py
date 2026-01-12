import argparse
import os
import pandas as pd
import matplotlib.pyplot as plt


def main():
    parser = argparse.ArgumentParser(description="Plot end-to-end throughput (bytes/s) from tshark CSV.")
    parser.add_argument('--input', type=str, required=True, help='Input CSV file from tshark.')
    parser.add_argument('--output-dir', type=str, default='.', help='Directory to save output files.')
    parser.add_argument('--handoff-times', type=str, help='Comma-separated list of handoff event times in seconds.')
    parser.add_argument('--window', type=int, default=10, help='Time window in seconds after a handoff for shading.')
    parser.add_argument('--prefix', type=str, default='/example/LiveStream', help='Application prefix to include.')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    plt.style.use('seaborn-v0_8-whitegrid')

    try:
        df = pd.read_csv(args.input)
        if df.empty:
            raise pd.errors.EmptyDataError
    except (pd.errors.EmptyDataError, FileNotFoundError):
        print(f"Warning: Input file {args.input} is empty or not found. Skipping.")
        open(os.path.join(args.output_dir, 'throughput_timeseries.pdf'), 'w').close()
        with open(os.path.join(args.output_dir, 'throughput_metrics.txt'), 'w') as f:
            f.write("Average: 0.0 bytes/s\nPeak: 0.0 bytes/s\nP95: 0.0 bytes/s\nTotalBytes: 0\nDuration: 0\n")
        return

    df.rename(columns={'frame.time_epoch': 'time', 'frame.len': 'length', 'ndn.name': 'name'}, inplace=True)
    df = df.dropna(subset=['time', 'length']).copy()

    app_prefix = args.prefix
    if 'name' in df.columns:
        df['name'] = df['name'].astype(str)
        df = df[df['name'].str.startswith(app_prefix)]
        df = df[~df['name'].str.startswith('/localhost/')]
        df = df[~df['name'].str.startswith('/localhop/ndn/nlsr/')]

    if df.empty:
        print(f"Warning: No packets under prefix {app_prefix}. Skipping.")
        open(os.path.join(args.output_dir, 'throughput_timeseries.pdf'), 'w').close()
        with open(os.path.join(args.output_dir, 'throughput_metrics.txt'), 'w') as f:
            f.write("Average: 0.0 bytes/s\nPeak: 0.0 bytes/s\nP95: 0.0 bytes/s\nTotalBytes: 0\nDuration: 0\n")
        return

    df['timestamp'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('timestamp', inplace=True)
    per_second = df['length'].resample('1S').sum()

    if per_second.empty:
        print("Warning: No per-second samples after resampling. Skipping.")
        open(os.path.join(args.output_dir, 'throughput_timeseries.pdf'), 'w').close()
        with open(os.path.join(args.output_dir, 'throughput_metrics.txt'), 'w') as f:
            f.write("Average: 0.0 bytes/s\nPeak: 0.0 bytes/s\nP95: 0.0 bytes/s\nTotalBytes: 0\nDuration: 0\n")
        return

    # Metrics
    total_bytes = per_second.sum()
    duration = max((per_second.index.max() - per_second.index.min()).total_seconds(), 1)
    avg_throughput = total_bytes / duration
    peak_throughput = per_second.max()
    p95_throughput = per_second.quantile(0.95)

    metrics_path = os.path.join(args.output_dir, 'throughput_metrics.txt')
    with open(metrics_path, 'w') as f:
        f.write(f"Average: {avg_throughput:.2f} bytes/s\n")
        f.write(f"Peak: {peak_throughput:.2f} bytes/s\n")
        f.write(f"P95: {p95_throughput:.2f} bytes/s\n")
        f.write(f"TotalBytes: {int(total_bytes)}\n")
        f.write(f"Duration: {duration:.2f} s\n")

    # Plot
    fig, ax = plt.subplots(figsize=(12, 6))
    per_second.plot(ax=ax, color='steelblue', label='Bytes per second')

    if args.handoff_times:
        handoffs = [float(t.strip()) for t in args.handoff_times.split(',')]
        for i, t in enumerate(handoffs):
            label = 'Handoff Window' if i == 0 else None
            ax.axvspan(per_second.index[0] + pd.to_timedelta(t, unit='s'),
                       per_second.index[0] + pd.to_timedelta(t + args.window, unit='s'),
                       color='orange', alpha=0.3, label=label)

    ax.set_xlabel('Time')
    ax.set_ylabel('Bytes per second')
    ax.set_title('Throughput Over Time')
    ax.legend()
    ax.grid(True, which="both", ls="--")
    fig.tight_layout()
    plt.savefig(os.path.join(args.output_dir, 'throughput_timeseries.pdf'))
    plt.close(fig)


if __name__ == '__main__':
    main()
