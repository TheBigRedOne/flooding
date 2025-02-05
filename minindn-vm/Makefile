# Makefile for minindn box

MININDN_BOX = $(CURDIR)/minindn.box

all: $(MININDN_BOX)

$(MININDN_BOX): Vagrantfile
	@echo "Creating minindn box..."
	-rm -f $(MININDN_BOX)
	vagrant up
	vagrant package --output $(MININDN_BOX)
	vagrant halt
	vagrant destroy -f

clean:
	@echo "Cleaning minindn box file..."
	-rm -f $(MININDN_BOX)

.PHONY: all clean
