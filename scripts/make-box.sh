#!/bin/sh

set -e

if [ $# != 2 ]; then
  echo "Usage: $0 <dir> <box>"
  exit 1
fi

DIR=$1
BOX=$2
LOCK=$BOX.lock

echo "*** Creating Vagrant box: $BOX ($PROVIDER, dir=$DIR)"

if [ -f $LOCK ]; then
  echo "*** Cleaning-up after interrupted build"
  VAGRANT_DEFAULT_PROVIDER=$PROVIDER VAGRANT_CWD=$DIR vagrant destroy -f
  VAGRANT_DEFAULT_PROVIDER=$PROVIDER VAGRANT_CWD=$DIR vagrant box remove $BOX || true
  rm -f $BOX
  echo "*** Clean-up finished"
fi

touch $LOCK

VAGRANT_DEFAULT_PROVIDER=$PROVIDER VAGRANT_CWD=$DIR vagrant up --provision
VAGRANT_DEFAULT_PROVIDER=$PROVIDER VAGRANT_CWD=$DIR vagrant package --output $BOX
VAGRANT_DEFAULT_PROVIDER=$PROVIDER VAGRANT_CWD=$DIR vagrant halt
VAGRANT_DEFAULT_PROVIDER=$PROVIDER VAGRANT_CWD=$DIR vagrant destroy -f

echo ""
echo "*** Finished building Vagrant box: $BOX ($PROVIDER, dir=$DIR)"
echo ""

rm -f $LOCK

