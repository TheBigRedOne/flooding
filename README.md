Please use Vagrant 2.4.0 or later. You will also need a virtualization provider:
- For VirtualBox (default): VirtualBox 7.1 or later.
- For KVM: A working KVM/libvirt setup configured for Vagrant.

To run the full experiment and build the paper:

- Using the default VirtualBox provider: "make all
- Using KVM/libvirt: "make kvm all"
- Using VirtualBox explicitly: "make vb all"

This will download the repository, build necessary virtual machine images (boxes) if they don't exist for the selected provider, run experiments, and generate the paper.

Caution: If you run the project in an external environment of Ubuntu 24.04, it is likely that mini-ndn is not installed correctly, even though the internal environment we set in Vagrantfile to create a box and run experiments is Ubuntu 22.04.