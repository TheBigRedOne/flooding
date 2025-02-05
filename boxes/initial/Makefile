# Initial Box Makefile

INITIAL_BOX = $(CURDIR)/initial.box

all: $(INITIAL_BOX)

$(INITIAL_BOX): Vagrantfile
	@echo "Creating initial box..."
	-rm -f $(INITIAL_BOX)
	vagrant up
	vagrant package --output $(INITIAL_BOX)
	vagrant halt
	vagrant destroy -f

clean:
	@echo "Cleaning initial box file..."
	-rm -f $(INITIAL_BOX)

.PHONY: all clean
