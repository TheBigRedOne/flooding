# Master Control Makefile

# Ensure all commands are executed in sequence; stop on errors
all:
	vagrant status | grep "running (virtualbox)" > /dev/null || vagrant up --provider virtualbox
	vagrant ssh -c '\
		if [ -d /home/vagrant/mini-ndn/flooding/experiments/baseline ]; then \
			cd /home/vagrant/mini-ndn/flooding/experiments/baseline && make; \
		else \
			echo "Error: Path /home/vagrant/mini-ndn/flooding/experiments/baseline does not exist."; \
			exit 1; \
		fi'
	vagrant halt

.PHONY: all
