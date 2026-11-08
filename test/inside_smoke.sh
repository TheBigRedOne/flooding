#!/bin/sh
# Compile and run one integration smoke inside the VM. Arguments: baseline|solution
set -eu

role=${1:?baseline or solution}
repo=/home/vagrant/flooding
work=$repo/test
role_dir=$work/$role
results=$role_dir/results
pkg=$(pkg-config --cflags --libs libndn-cxx)

mkdir -p "$results"
rm -f "$work/producer" "$work/consumer" "$work/optoflood-daemon"
g++ -std=c++17 -O2 -o "$work/producer" "$repo/experiment/app/producer.cpp" $pkg
g++ -std=c++17 -O2 -o "$work/consumer" "$repo/experiment/app/consumer.cpp" $pkg
if [ "$role" = "solution" ]; then
  g++ -std=c++17 -O2 -o "$work/optoflood-daemon" "$repo/experiment/app/optoflood-daemon.cpp" $pkg
fi
cp -f "$repo/experiment/app/trust-schema.conf" "$work/trust-schema.conf"

cd "$work"
# Mini-NDN requires root. Compilation above stays unprivileged.
# A driver failure returns that status after the logs are made readable.
set +e
sudo -E env EXPERIMENT_DIR="$role_dir" python3 "$work/${role}_smoke.py"
status=$?
sudo chmod -R a+rX "$results"
chmod_status=$?
set -e
if [ "$status" -ne 0 ]; then
  exit "$status"
fi
if [ "$chmod_status" -ne 0 ]; then
  exit "$chmod_status"
fi
EXPERIMENT_DIR="$role_dir" python3 "$work/validate_${role}.py" "$results"
