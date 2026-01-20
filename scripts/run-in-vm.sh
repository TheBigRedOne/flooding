#!/bin/sh

set -e 


if [ $# != 2 ]; then
  echo "Usage: $0 <dir> <cmd>"
  exit 1
fi

DIR=$1
CMD=$2

LOCK=$DIR/vm.lock

if [ x$PROVIDER = x ]; then
  echo "Cannot run VM using Vagrant box in $DIR - provider is not set"
  exit 1
fi

echo "*** Running VM using Vagrant box in $DIR ($PROVIDER)"

if [ -f $LOCK ]; then
  echo "*** Cleaning-up after interrupted build"
  VAGRANT_DEFAULT_PROVIDER=$PROVIDER VAGRANT_CWD=$DIR vagrant destroy -f
  echo "*** Clean-up finished"
fi

touch $LOCK

rm -f $DIR/ssh-config

VAGRANT_DEFAULT_PROVIDER=$PROVIDER VAGRANT_CWD=$DIR vagrant up --provision
VAGRANT_DEFAULT_PROVIDER=$PROVIDER VAGRANT_CWD=$DIR vagrant ssh-config > $DIR/ssh-config

echo "=== Synchronising files to VM in $DIR"
rsync -avH --delete -e "ssh -F $DIR/ssh-config" $DIR/vm default:

echo "=== Running \"$CMD\" using VM in $DIR"
VAGRANT_DEFAULT_PROVIDER=$PROVIDER VAGRANT_CWD=$DIR vagrant ssh -c "(cd vm && $CMD)"

echo "=== Retrieving files from VM in $DIR"
rsync -avH --delete -e "ssh -F $DIR/ssh-config" default:vm $DIR

VAGRANT_DEFAULT_PROVIDER=$PROVIDER VAGRANT_CWD=$DIR vagrant halt

rm -f $DIR/ssh-config

echo ""
echo "*** Finished running VM using Vagrant box in $DIR ($PROVIDER)"
echo ""

rm -f $LOCK

