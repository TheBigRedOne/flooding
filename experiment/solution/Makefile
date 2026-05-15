# Makefile for the SOLUTION experiment, to be run inside the VM.

# --- Target groups ---
EXPERIMENT_RESULTS = results/consumer_capture.pcap \
                     results/pcap_nodes/core.pcap \
                     results/pcap_nodes/agg1.pcap \
                     results/pcap_nodes/agg2.pcap \
                     results/pcap_nodes/acc1.pcap \
                     results/pcap_nodes/acc2.pcap \
                     results/pcap_nodes/acc3.pcap \
                     results/pcap_nodes/acc4.pcap \
                     results/pcap_nodes/acc5.pcap \
                     results/pcap_nodes/acc6.pcap \
                     results/pcap_nodes/producer.pcap \
                     results/pcap_nodes/consumer.pcap \
                     results/handoffs.txt

# --- Targets ---

# The default target produces only raw experiment artifacts for host-side analysis.
all: $(EXPERIMENT_RESULTS)

# The experiment script generates the complete raw result set in one run.
$(EXPERIMENT_RESULTS) &: ../tool/exp.py producer consumer
	mkdir -p results
	# Run the experiment script using sudo, preserving EXPERIMENT_DIR environment.
	sudo -E env EXPERIMENT_DIR=$(shell pwd) python3 ../tool/exp.py

# Recipe to compile the producer.
producer: ../app/producer.cpp
	g++ -std=c++17 -g -O2 -DSOLUTION_ENABLED -o $@ $< $$(pkg-config --cflags --libs libndn-cxx)

# Recipe to compile the consumer.
consumer: ../app/consumer.cpp
	g++ -std=c++17 -g -O2 -DSOLUTION_ENABLED -o $@ $< $$(pkg-config --cflags --libs libndn-cxx)

# A target to clean up all generated files.
clean:
	sudo rm -rf producer consumer results

.PHONY: all clean
