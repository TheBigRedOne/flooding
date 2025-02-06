# Solution Box Makefile

INITIAL_BOX := $(abspath ../../boxes/initial/initial.box)
SOLUTION_BOX = $(CURDIR)/solution.box

all: $(SOLUTION_BOX)

$(SOLUTION_BOX): Vagrantfile $(INITIAL_BOX)
	@echo "Creating solution box (with modified mini-ndn)..."
	-rm -f $(SOLUTION_BOX)
	vagrant up
	vagrant package --output $(SOLUTION_BOX)
	vagrant halt
	vagrant destroy -f

clean:
	@echo "Cleaning solution box file..."
	-rm -f $(SOLUTION_BOX)

.PHONY: all clean
