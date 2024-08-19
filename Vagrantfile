# -*- mode: ruby -*-
# vi: set ft=ruby :

$INSTALL_BASE = <<EOF
  export DEBIAN_FRONTEND=noninteractive

  sudo apt-get update
  sudo apt-get install -y build-essential 
  sudo apt-get install -y python3-pip 
  sudo apt-get install -y python3-pep8 
  sudo apt-get install -y pkg-config 
  sudo apt-get install -y libboost-all-dev 
  sudo apt-get install -y libssl-dev 
  sudo apt-get install -y libsqlite3-dev 
  sudo apt-get install -y libpcap-dev 
  sudo apt-get install -y libsystemd-dev
  sudo apt-get install -y tcpdump

  # Clone and install mini-ndn
  #
  # install.sh has additional options that can be used to install specific 
  # versions of ndn-cxx, nfd, etc. from GitHub as needed. For details, see
  # https://github.com/named-data/mini-ndn/blob/master/install.sh
  #
  git clone https://github.com/named-data/mini-ndn.git /home/vagrant/mini-ndn
  cd /home/vagrant/mini-ndn
  git checkout b5c893d5a190f530885a4e31ce440e7077848f97
  ./install.sh -y --source 

  # Change ownership of the mini-ndn folder to vagrant user
  sudo chown -R vagrant:vagrant /home/vagrant/mini-ndn

  # Set environment variables in .profile rather than .bashrc
  # because .bashrc is only read for interactive shells and
  # "vagrant ssh -c command" starts a non-interactive shell.
  echo "export PATH=\$PATH:/usr/local/bin" >> /home/vagrant/.profile
  echo "export LD_LIBRARY_PATH=\$LD_LIBRARY_PATH:/usr/local/lib64/" >> /home/vagrant/.profile
  echo "export PKG_CONFIG_PATH=/usr/local/lib64/pkgconfig/" >> /home/vagrant/.profile
EOF

$DOWNLOAD_FILES = <<EOF
  # Clone Flooding project
  git clone https://github.com/TheBigRedOne/flooding_experiment.git /home/vagrant/mini-ndn/flooding
EOF

Vagrant.configure("2") do |config|
  # mininet-wifi and infoedit won't build on ubuntu-24.04 due to missing python-pep8 package
  # (e.g., see https://github.com/intrig-unicamp/mininet-wifi/issues/536 for mininet-wifi),
  # so for now use ubuntu-22.04 instead.
  config.vm.box = "bento/ubuntu-22.04"
  config.vm.box_version = "202407.23.0"

  config.vm.network "private_network", type: "dhcp"

  config.vm.provider :virtualbox do |v|
    v.customize ["modifyvm", :id, "--cpus", "4"]
    v.customize ["modifyvm", :id, "--memory", "32768"]
    v.customize ["modifyvm", :id, "--vram", "256"]
    v.gui = false
  end

  config.vm.provision "shell", inline: $INSTALL_BASE, privileged: false
  config.vm.provision "shell", inline: $DOWNLOAD_FILES, privileged: false
end
