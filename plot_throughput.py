import matplotlib.pyplot as plt
import csv
import sys
import os

def plot_throughput(csv_file):
    times = []
    throughput = []

    with open(csv_file, 'r') as f:
        reader = csv.DictReader(f)
        start_time = None
        for row in reader:
            time = float(row['time'])
            if start_time is None:
                start_time = time
            # 使用相对时间来确保时间刻度为正常的秒数
            times.append(time - start_time)
            throughput.append(int(row['throughput']))

    plt.figure(figsize=(10, 5))
    plt.plot(times, throughput, label='Throughput')
    plt.xlabel('Time (seconds)')
    plt.ylabel('Throughput (bytes)')
    plt.title('Network Throughput Over Time')
    plt.legend()
    plt.grid(True)

    # 设置X轴刻度，从0开始，每20秒一个刻度
    max_time = int(max(times))
    plt.xticks(range(0, max_time + 20, 20))

    # 禁用时间偏移显示，移除 '1e9'
    plt.gca().get_xaxis().get_major_formatter().set_useOffset(False)

    output_file = os.path.splitext(csv_file)[0] + '.pdf'
    plt.savefig(output_file)
    plt.show()

if __name__ == "__main__":
    plot_throughput(sys.argv[1])
