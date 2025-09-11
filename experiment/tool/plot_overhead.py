import pandas as pd
import argparse
import os
import re

def main():
    parser = argparse.ArgumentParser(description="Analyze control overhead from NDN pcap CSV.")
    parser.add_argument('--input', type=str, required=True, help='Input CSV file from tshark.')
    parser.add_argument('--output-dir', type=str, default='.', help='Directory to save output plots.')
    parser.add_argument('--handoff-times', type=str, help='Comma-separated list of handoff event times in seconds.')
    parser.add_argument('--window', type=int, default=5, help='Time window in seconds after a handoff to analyze.')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    try:
        df = pd.read_csv(args.input)
        if df.empty:
            raise pd.errors.EmptyDataError
    except (pd.errors.EmptyDataError, FileNotFoundError):
        print(f"Warning: Input file {args.input} is empty or not found. Skipping.")
        # Create empty files to satisfy Makefile
        open(os.path.join(args.output_dir, 'overhead_interests.txt'), 'w').close()
        open(os.path.join(args.output_dir, 'overhead_nacks.txt'), 'w').close()
        return
        
    df.rename(columns={'frame.time_epoch': 'time', 'ndn.type': 'type', 'ndn.name': 'name'}, inplace=True)
    df = df.dropna().copy()
    
    # Filter out NLSR sync packets, which are not part of the experiment data
    df = df[~df['name'].str.startswith('/localhop/ndn/nlsr/sync')]
    
    # Convert type to lowercase string
    df['type'] = df['type'].str.lower()
    
    start_time = df['time'].min()
    df['relative_time'] = df['time'] - start_time

    interest_count = 0
    nack_count = 0

    if args.handoff_times:
        handoffs = [float(t.strip()) for t in args.handoff_times.split(',')]
        for t in handoffs:
            window_start = t
            window_end = t + args.window
            
            window_df = df[(df['relative_time'] >= window_start) & (df['relative_time'] < window_end)]
            
            interest_count += (window_df['type'] == 'interest').sum()
            nack_count += (window_df['type'] == 'nack').sum()
    else:
        print("Warning: No handoff times provided. Cannot calculate overhead.")

    interest_output_file = os.path.join(args.output_dir, 'overhead_interests.txt')
    with open(interest_output_file, 'w') as f:
        f.write(str(interest_count))
        
    nack_output_file = os.path.join(args.output_dir, 'overhead_nacks.txt')
    with open(nack_output_file, 'w') as f:
        f.write(str(nack_count))

    print(f"Control Overhead within {args.window}s windows after handoffs:")
    print(f"  - Interests: {interest_count}")
    print(f"  - Nacks: {nack_count}")
    print(f"Results saved to {args.output_dir}")

if __name__ == '__main__':
    main()
