import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import argparse
import os

def main():
    parser = argparse.ArgumentParser(description="Analyze service disruption time from NDN pcap CSV.")
    parser.add_argument('--input', type=str, required=True, help='Input CSV file from tshark.')
    parser.add_argument('--output-dir', type=str, default='.', help='Directory to save output files.')
    parser.add_argument('--handoff-times', type=str, required=True, help='Comma-separated list of handoff event times in seconds.')
    parser.add_argument('--prefix', type=str, default='/example/LiveStream', help='Application prefix to include.')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    plt.style.use('seaborn-v0_8-whitegrid')
    
    try:
        df = pd.read_csv(args.input)
        if df.empty:
            raise pd.errors.EmptyDataError
    except (pd.errors.EmptyDataError, FileNotFoundError):
        print(f"Warning: Input file {args.input} is empty or not found. Skipping analysis.")
        open(os.path.join(args.output_dir, 'disruption_times.pdf'), 'w').close()
        open(os.path.join(args.output_dir, 'disruption_metrics.txt'), 'w').close()
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
        open(os.path.join(args.output_dir, 'disruption_times.pdf'), 'w').close()
        open(os.path.join(args.output_dir, 'disruption_metrics.txt'), 'w').close()
        return

    # Convert type to lowercase string
    df['type'] = df['type'].str.lower()
    
    # Get experiment start time (time of the first packet)
    start_time = df['time'].min()
    
    handoffs_relative = [float(t.strip()) for t in args.handoff_times.split(',')]
    handoffs_absolute = [start_time + t for t in handoffs_relative]

    all_data_times = np.sort(df[df['type'] == 'data']['time'].unique())
    disruption_times = []

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
        open(os.path.join(args.output_dir, 'disruption_times.pdf'), 'w').close()
        open(os.path.join(args.output_dir, 'disruption_metrics.txt'), 'w').close()
        return

    # --- (R1) Service disruption time (K1) ---
    # Bar plot of per-handoff disruption times
    fig, ax = plt.subplots(figsize=(10, 6))
    handoff_labels = [f'Handoff {i+1}' for i in range(len(disruption_times))]
    ax.bar(handoff_labels, disruption_times, color='skyblue')
    ax.set_ylabel('Service Disruption Time (ms)')
    ax.set_title('Per-Handoff Service Disruption Time')
    ax.grid(axis='y', linestyle='--', alpha=0.7)
    fig.tight_layout()
    plt.savefig(os.path.join(args.output_dir, 'disruption_times.pdf'))
    plt.close(fig)

    # Median and 90th percentile
    median_disruption = np.median(disruption_times)
    p90_disruption = np.percentile(disruption_times, 90)

    metrics_file = os.path.join(args.output_dir, 'disruption_metrics.txt')
    with open(metrics_file, 'w') as f:
        f.write(f"Median Disruption Time: {median_disruption:.2f} ms\n")
        f.write(f"90th Percentile Disruption Time: {p90_disruption:.2f} ms\n")
    
    print(f"Generated R1 (Service Disruption) plots and metrics in {args.output_dir}")

if __name__ == '__main__':
    main()
