#!/bin/sh
# Boot one smoke VM, run its driver and validator, and return the validator status.
set -eu

role=${1:?baseline or solution}
provider=${PROVIDER:?PROVIDER is required}
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)

case "$role" in
  baseline)
    vagrant_dir=$root/test/baseline
    box_path=$root/box/baseline/baseline.$provider.box
    box_env=ACTUAL_BASELINE_BOX_PATH
    box_name=optoflood-baseline-smoke
    host_alias=baseline-smoke
    ;;
  solution)
    vagrant_dir=$root/test/solution
    box_path=$root/box/solution/solution.$provider.box
    box_env=ACTUAL_SOLUTION_BOX_PATH
    box_name=optoflood-solution-smoke
    host_alias=solution-smoke
    ;;
  *)
    echo "unknown smoke role: $role" >&2
    exit 2
    ;;
esac

export "$box_env=$box_path"
if [ "$role" = "baseline" ]; then
  export BASELINE_BOX_NAME=$box_name
else
  export SOLUTION_BOX_NAME=$box_name
fi

cd "$vagrant_dir"
VAGRANT_DEFAULT_PROVIDER=$provider vagrant up --provision
VAGRANT_DEFAULT_PROVIDER=$provider vagrant ssh-config --host "$host_alias" > "$root/test/.ssh_config_$role"
rsync -aH --stats --human-readable -e "ssh -F $root/test/.ssh_config_$role" \
  --exclude .git --exclude .vagrant --exclude results --exclude paper/bin \
  --exclude box --exclude '*.box' \
  --exclude experiment/tool/.venv/ \
  --exclude __pycache__/ \
  --exclude '*.pyc' \
  --exclude '.ssh_config_*' \
  "$root/" "$host_alias:/home/vagrant/flooding/"

set +e
ssh -F "$root/test/.ssh_config_$role" "$host_alias" \
  "sh /home/vagrant/flooding/test/inside_smoke.sh $role"
status=$?
set -e
mkdir -p "$vagrant_dir/results"
rsync -aH --stats --human-readable -e "ssh -F $root/test/.ssh_config_$role" \
  "$host_alias:/home/vagrant/flooding/test/$role/results/" "$vagrant_dir/results/" || true
VAGRANT_DEFAULT_PROVIDER=$provider vagrant halt -f || true
exit "$status"
