import csv
import sys
from collections import defaultdict
import os

def calculate_throughput(csv_file):
    throughput = defaultdict(int)
    with open(csv_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            time = float(row['frame.time_epoch'])
            length = int(row['frame.len'])
            second = int(time)
            throughput[second] += length

    output_file = os.path.splitext(csv_file)[0] + '_throughput.csv'
    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['time', 'throughput'])
        for time, data in sorted(throughput.items()):
            writer.writerow([time, data])

if __name__ == "__main__":
    calculate_throughput(sys.argv[1])
