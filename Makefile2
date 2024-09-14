# Paths
VAGRANTFILE = Vagrantfile
FLOODING_DIR = /home/vagrant/mini-ndn/flooding
RESULTS_DIR = results

# Executable names
CONSUMER_EXEC = consumer
PRODUCER_EXEC = producer

# Logs and output files
CONSUMER_LOG = $(RESULTS_DIR)/consumer.log
PRODUCER_LOG = $(RESULTS_DIR)/producer.log
PCAP_FILE = $(RESULTS_DIR)/consumer_capture.pcap
PCAP_CSV = $(RESULTS_DIR)/consumer_capture.csv
THROUGHPUT_CSV = $(RESULTS_DIR)/consumer_capture_throughput.csv

# Main targets
all: $(PCAP_FILE) $(THROUGHPUT_CSV)

$(CONSUMER_EXEC): | start-vagrant
	vagrant ssh -c 'cd $(FLOODING_DIR) && g++ -std=c++17 -o $(CONSUMER_EXEC) consumer.cpp $$(pkg-config --cflags --libs libndn-cxx)'

$(PRODUCER_EXEC): | start-vagrant
	vagrant ssh -c 'cd $(FLOODING_DIR) && g++ -std=c++17 -o $(PRODUCER_EXEC) producer.cpp $$(pkg-config --cflags --libs libndn-cxx)'

$(PCAP_FILE): $(CONSUMER_EXEC) $(PRODUCER_EXEC) generate-keys | start-vagrant
	vagrant ssh -c 'cd $(FLOODING_DIR) && sudo python exp.py'
	mkdir -p $(RESULTS_DIR)
	vagrant ssh -c 'cp $(FLOODING_DIR)/consumer_capture.pcap /vagrant/$(PCAP_FILE)'

$(THROUGHPUT_CSV): $(PCAP_FILE) | start-vagrant
	vagrant ssh -c 'tshark -r /vagrant/$(PCAP_FILE) -T fields -e frame.time_epoch -e frame.len -E header=y -E separator=, -E quote=d > /vagrant/$(PCAP_CSV)'
	vagrant ssh -c 'python3 $(FLOODING_DIR)/throughput_calculation.py /vagrant/$(PCAP_CSV)'
	vagrant ssh -c 'python3 $(FLOODING_DIR)/plot_throughput.py /vagrant/$(THROUGHPUT_CSV)'

# Vagrant management
start-vagrant:
	vagrant up --provider virtualbox

stop-vagrant:
	vagrant halt

clean-vagrant:
	vagrant destroy -f

# Key generation
generate-keys: | start-vagrant
	vagrant ssh -c 'cd $(FLOODING_DIR) && \
	ndnsec key-gen /example && \
	ndnsec cert-dump -i /example > example-trust-anchor.cert && \
	ndnsec key-gen /example/testApp && \
	ndnsec sign-req /example/testApp | ndnsec cert-gen -s /example -i example | ndnsec cert-install -'

# Cleanup
clean:
	rm -f $(CONSUMER_LOG) $(PRODUCER_LOG) $(PCAP_FILE) $(PCAP_CSV) $(THROUGHPUT_CSV)
	vagrant ssh -c 'cd $(FLOODING_DIR) && rm -f $(CONSUMER_EXEC) $(PRODUCER_EXEC)'

# .PHONY ensures these are not treated as files
.PHONY: all start-vagrant stop-vagrant clean-vagrant generate-keys clean

# Automatically remove files on error
.DELETE_ON_ERROR:
