import pandas as pd
import argparse
import re
import os

def parse_info_column(infos):
    """Parses the 'Info' column from tshark CSV output into types."""
    types = []
    info_regex = re.compile(r'^(Interest|Data|Nack)')
    for s in infos:
        match = info_regex.match(str(s))
        if match:
            types.append(match.group(1).lower())
        else:
            types.append(None)
    return types

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
    except (pd.errors.EmptyDataError, FileNotFoundError):
        print(f"Warning: Input file {args.input} is empty or not found. Skipping.")
        return
        
    types = parse_info_column(df['Info'])
    clean_df = pd.DataFrame({
        'time': pd.to_numeric(df['Time'], errors='coerce'),
        'type': types
    }).dropna()
    
    start_time = clean_df['time'].min()
    clean_df['relative_time'] = clean_df['time'] - start_time

    interest_count = 0
    nack_count = 0

    if args.handoff_times:
        handoffs = [float(t.strip()) for t in args.handoff_times.split(',')]
        for t in handoffs:
            window_start = t
            window_end = t + args.window
            
            window_df = clean_df[(clean_df['relative_time'] >= window_start) & (clean_df['relative_time'] < window_end)]
            
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
