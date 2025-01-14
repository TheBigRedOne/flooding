# External Makefile

all:
	vagrant up --provider virtualbox
	vagrant ssh -c 'cd /home/vagrant/mini-ndn/flooding/experiment && make'
	vagrant halt

.PHONY: all
