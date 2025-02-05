# Baseline Box Makefile

BASELINE_BOX = $(CURDIR)/baseline.box

all: $(BASELINE_BOX)

$(BASELINE_BOX): Vagrantfile
	@echo "Creating baseline box (with mini-ndn)..."
	-rm -f $(BASELINE_BOX)
	vagrant up
	vagrant package --output $(BASELINE_BOX)
	vagrant halt
	vagrant destroy -f

clean:
	@echo "Cleaning baseline box file..."
	-rm -f $(BASELINE_BOX)

.PHONY: all clean
