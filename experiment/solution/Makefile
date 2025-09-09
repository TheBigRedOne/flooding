# Makefile for the SOLUTION experiment, to be run inside the VM.

# --- Variables ---
PCAP_FILE := results/consumer_capture.pcap
CSV_FILE  := results/consumer_capture.csv

CXX      := g++
# CRITICAL: Add -DSOLUTION_ENABLED to activate solution-specific code via preprocessor macros.
CXXFLAGS := -std=c++17 -g -O2 -DSOLUTION_ENABLED
LDFLAGS  := $(shell pkg-config --cflags --libs libndn-cxx)

APP_DIR  := ../app
TOOL_DIR := ../tool

# --- Targets ---

# The main target to run the full experiment and get all result files.
all: results/latency_timeseries.pdf results/loss_ratio.txt results/overhead_interests.txt

# The final plots/data depend on the CSV file, which in turn depends on the PCAP file.
results/latency_timeseries.pdf results/loss_ratio.txt results/overhead_interests.txt: $(CSV_FILE)
	# Generate plots and metrics from the CSV data
	python3 $(TOOL_DIR)/plot_latency.py --input $(CSV_FILE) --output-dir results --handoff-times "60, 120"
	python3 $(TOOL_DIR)/plot_loss.py --input $(CSV_FILE) --output-dir results
	python3 $(TOOL_DIR)/plot_overhead.py --input $(CSV_FILE) --output-dir results --handoff-times "60, 120"

# Convert PCAP to CSV using tshark
$(CSV_FILE): $(PCAP_FILE)
	tshark -r $< -T fields -e frame.time_epoch -e ndn.type -e ndn.name -E separator=, -E header=y > $@

# The PCAP result depends on the experiment script and the compiled apps.
$(PCAP_FILE): $(TOOL_DIR)/exp.py producer consumer
	mkdir -p results
	# Run the experiment script using sudo in 'solution' mode.
	sudo python3 $(TOOL_DIR)/exp.py --mode solution --interval 60

# Recipe to compile the producer.
producer: $(APP_DIR)/producer.cpp
	$(CXX) $(CXXFLAGS) -o $@ $< $(LDFLAGS)

# Recipe to compile the consumer.
consumer: $(APP_DIR)/consumer.cpp
	$(CXX) $(CXXFLAGS) -o $@ $< $(LDFLAGS)

# A target to clean up all generated files.
clean:
	rm -rf producer consumer results

.PHONY: all clean
