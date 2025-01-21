# Solution Test Makefile

# Base paths
BASE_DIR := $(shell pwd)
RESULTS_DIR := $(BASE_DIR)/results
TOOLS_DIR := $(BASE_DIR)/../tools

# Executable names and sources
CONSUMER_SRC := consumer_mp.cpp
CONSUMER_EXEC := $(BASE_DIR)/consumer
PRODUCER_SRC := producer_mp.cpp
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

# Build the consumer executable
$(CONSUMER_EXEC): $(CONSUMER_SRC)
	g++ -std=c++17 -o $(CONSUMER_EXEC) $(CONSUMER_SRC) $$(pkg-config --cflags --libs libndn-cxx)

# Build the producer executable
$(PRODUCER_EXEC): $(PRODUCER_SRC)
	g++ -std=c++17 -o $(PRODUCER_EXEC) $(PRODUCER_SRC) $$(pkg-config --cflags --libs libndn-cxx)

# Generate the key and cert
$(CERT_FILE): $(TRUST_SCHEMA)
	ndnsec key-gen /example && \
	ndnsec cert-dump -i /example > $(CERT_FILE) && \
	ndnsec key-gen /example/LiveStream && \
	ndnsec sign-req /example/LiveStream | ndnsec cert-gen -s /example -i example | ndnsec cert-install -
	cp $(TRUST_SCHEMA) .

# Generate the PCAP file
$(PCAP_FILE): $(CONSUMER_EXEC) $(PRODUCER_EXEC) $(CERT_FILE)
	env EXPERIMENT_DIR=$(BASE_DIR) sudo -E python $(TOOLS_DIR)/exp.py
	mkdir -p $(RESULTS_DIR)
	cp consumer_capture.pcap $(PCAP_FILE)

# Generate the CSV file from PCAP
$(PCAP_CSV): $(PCAP_FILE)
	tshark -r $(PCAP_FILE) -T fields -e frame.time_epoch -e frame.len -E header=y -E separator=, -E quote=d > $(PCAP_CSV)

# Generate the throughput CSV
$(THROUGHPUT_CSV): $(PCAP_CSV)
	python $(TOOLS_DIR)/throughput_calculation.py $(PCAP_CSV)

# Generate the throughput PDF
$(THROUGHPUT_PDF): $(THROUGHPUT_CSV)
	python $(TOOLS_DIR)/plot_throughput.py $(THROUGHPUT_CSV)

# Cleanup
clean:
	rm -f $(CONSUMER_LOG) $(PRODUCER_LOG) $(PCAP_FILE) $(PCAP_CSV) $(THROUGHPUT_CSV) $(THROUGHPUT_PDF)
	rm -f $(CONSUMER_EXEC) $(PRODUCER_EXEC) $(CERT_FILE)

.PHONY: all clean
.DELETE_ON_ERROR:
