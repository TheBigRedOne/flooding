# Vagrantfile path
VAGRANTFILE = Vagrantfile
RESULTS_DIR = results
EXTERNAL_RESULTS_DIR = results

# Vagrant VM start
start-vagrant:
	vagrant up --provider virtualbox

# Compile consumer.cpp
compile-consumer: start-vagrant
	vagrant ssh -c 'cd /home/vagrant/mini-ndn/flooding && \
	g++ -std=c++17 -o consumer consumer.cpp $$(pkg-config --cflags --libs libndn-cxx)'

# Compile producer.cpp
compile-producer: start-vagrant
	vagrant ssh -c 'cd /home/vagrant/mini-ndn/flooding && \
	g++ -std=c++17 -o producer producer.cpp $$(pkg-config --cflags --libs libndn-cxx)'

# Generate trust anchor
generate-keys: start-vagrant
	vagrant ssh -c 'cd /home/vagrant/mini-ndn/flooding && \
	ndnsec key-gen /example && \
	ndnsec cert-dump -i /example > example-trust-anchor.cert && \
	ndnsec key-gen /example/testApp && \
	ndnsec sign-req /example/testApp | ndnsec cert-gen -s /example -i example | ndnsec cert-install -'

# Run the experiment
run-test: compile-consumer compile-producer generate-keys
	vagrant ssh -c 'cd /home/vagrant/mini-ndn/flooding && sudo python test.py'

# Export results
export-results: run-test
	mkdir -p $(EXTERNAL_RESULTS_DIR)
	vagrant ssh -c 'cp /home/vagrant/mini-ndn/flooding/consumer.log /vagrant/$(RESULTS_DIR)/'
	vagrant ssh -c 'cp /home/vagrant/mini-ndn/flooding/producer.log /vagrant/$(RESULTS_DIR)/'

# Shut down Vagrant VM
stop-vagrant: export-results
	vagrant halt

# Clean Vagrant VM
clean-vagrant: stop-vagrant
	vagrant destroy -f

# Run
all: clean-vagrant
