# Vagrantfile path
VAGRANTFILE = Vagrantfile
RESULTS_DIR = results
FLOODING_DIR = /home/vagrant/mini-ndn/flooding

# Vagrant VM start
start-vagrant:
	vagrant up --provider virtualbox

# Compile consumer.cpp
compile-consumer: start-vagrant
	vagrant ssh -c 'cd $(FLOODING_DIR) && \
	g++ -std=c++17 -o consumer consumer.cpp $$(pkg-config --cflags --libs libndn-cxx)'

# Compile producer.cpp
compile-producer: start-vagrant
	vagrant ssh -c 'cd $(FLOODING_DIR) && \
	g++ -std=c++17 -o producer producer.cpp $$(pkg-config --cflags --libs libndn-cxx)'

# Generate trust anchor
generate-keys: start-vagrant
	vagrant ssh -c 'cd $(FLOODING_DIR) && \
	ndnsec key-gen /example && \
	ndnsec cert-dump -i /example > example-trust-anchor.cert && \
	ndnsec key-gen /example/testApp && \
	ndnsec sign-req /example/testApp | ndnsec cert-gen -s /example -i example | ndnsec cert-install -'

# Run the experiment
run-test: compile-consumer compile-producer generate-keys
	vagrant ssh -c 'cd $(FLOODING_DIR) && sudo python exp.py'

# Export results (including pcap file)
export-results: run-test
	mkdir -p $(RESULTS_DIR)
	vagrant ssh -c 'cp $(FLOODING_DIR)/consumer.log /vagrant/$(RESULTS_DIR)/'
	vagrant ssh -c 'cp $(FLOODING_DIR)/producer.log /vagrant/$(RESULTS_DIR)/'
	vagrant ssh -c 'cp $(FLOODING_DIR)/consumer_capture.pcap /vagrant/$(RESULTS_DIR)/'

# Convert pcap to CSV, calculate throughput, and plot graph (all in results/)
analyze-results: export-results
	vagrant ssh -c 'tshark -r /vagrant/$(RESULTS_DIR)/consumer_capture.pcap -T fields -e frame.time_epoch -e frame.len -E header=y -E separator=, -E quote=d > /vagrant/$(RESULTS_DIR)/consumer_capture.csv'
	vagrant ssh -c 'python3 $(FLOODING_DIR)/throughput_calculation.py /vagrant/$(RESULTS_DIR)/consumer_capture.csv'
	vagrant ssh -c 'python3 $(FLOODING_DIR)/plot_throughput.py /vagrant/$(RESULTS_DIR)/consumer_capture_throughput.csv'

# Shut down Vagrant VM
stop-vagrant: analyze-results
	vagrant halt

# Clean Vagrant VM
clean-vagrant: stop-vagrant
	vagrant destroy -f

# Run all steps, generate results, and export them
all: clean-vagrant
