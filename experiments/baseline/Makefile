# Baseline Test Makefile

# Base paths
BASE_DIR := $(shell pwd)
RESULTS_DIR := $(BASE_DIR)/results
TOOLS_DIR := $(BASE_DIR)/../tools

# Executable names and sources
CONSUMER_SRC := consumer.cpp
CONSUMER_EXEC := $(BASE_DIR)/consumer
PRODUCER_SRC := producer.cpp
PRODUCER_EXEC := $(BASE_DIR)/producer

# Logs and output files
CONSUMER_LOG := $(RESULTS_DIR)/consumer.log
PRODUCER_LOG := $(RESULTS_DIR)/producer.log
PCAP_FILE := $(RESULTS_DIR)/consumer_capture.pcap
PCAP_CSV := $(RESULTS_DIR)/consumer_capture.csv
THROUGHPUT_CSV := $(RESULTS_DIR)/consumer_capture_throughput.csv
THROUGHPUT_PDF := $(RESULTS_DIR)/consumer_capture_throughput.pdf

# Key file and trust schema
CERT_FILE := example-trust-anchor.cert
TRUST_SCHEMA := $(TOOLS_DIR)/trust-schema.conf

# Main targets
all: $(PCAP_FILE) $(THROUGHPUT_CSV) $(THROUGHPUT_PDF)

# Ensure results directory exists
$(RESULTS_DIR):
	mkdir -p $@

# Build executables
$(CONSUMER_EXEC): $(CONSUMER_SRC)
	g++ -std=c++17 -o $@ $< $$(pkg-config --cflags --libs libndn-cxx)

$(PRODUCER_EXEC): $(PRODUCER_SRC)
	g++ -std=c++17 -o $@ $< $$(pkg-config --cflags --libs libndn-cxx)

# Generate the key and cert
$(CERT_FILE): $(TRUST_SCHEMA)
	ndnsec key-gen /example && \
	ndnsec cert-dump -i /example > $@ && \
	ndnsec key-gen /example/LiveStream && \
	ndnsec sign-req /example/LiveStream | ndnsec cert-gen -s /example -i example | ndnsec cert-install -
	cp $< .

# Generate the PCAP file
$(PCAP_FILE): $(CONSUMER_EXEC) $(PRODUCER_EXEC) $(CERT_FILE) | $(RESULTS_DIR)
	env EXPERIMENT_DIR=$(BASE_DIR) sudo -E python $(TOOLS_DIR)/exp.py
	cp consumer_capture.pcap $@

# Generate the CSV file from PCAP
$(PCAP_CSV): $(PCAP_FILE) | $(RESULTS_DIR)
	tshark -r $< -T fields -e frame.time_epoch -e frame.len -E header=y -E separator=, -E quote=d > $@

# Generate the throughput CSV
$(THROUGHPUT_CSV): $(PCAP_CSV) | $(RESULTS_DIR)
	python $(TOOLS_DIR)/throughput_calculation.py $<

# Generate the throughput PDF
$(THROUGHPUT_PDF): $(THROUGHPUT_CSV) | $(RESULTS_DIR)
	python $(TOOLS_DIR)/plot_throughput.py $<

# Cleanup intermediate files
clean:
	rm -f $(CONSUMER_LOG) $(PRODUCER_LOG) $(PCAP_FILE) $(PCAP_CSV) $(THROUGHPUT_CSV) $(THROUGHPUT_PDF)
	rm -f $(CONSUMER_EXEC) $(PRODUCER_EXEC) $(CERT_FILE)

# Cleanup all generated files, including results directory
deep-clean: clean
	rm -rf $(RESULTS_DIR)

.PHONY: all clean deep-clean
.DELETE_ON_ERROR:
.NOTINTERMEDIATE: $(PCAP_CSV) $(THROUGHPUT_CSV)
