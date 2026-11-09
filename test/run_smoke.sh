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

smoke_vm_absent() {
  output=$(VAGRANT_DEFAULT_PROVIDER=$provider vagrant status --machine-readable) || return 1
  printf '%s\n' "$output" | awk -F, '
    $3 == "state" { seen = 1; if ($4 != "not_created") bad = 1 }
    END { exit (seen && !bad) ? 0 : 1 }
  '
}

destroy_smoke_vm() {
  destroy_status=0
  VAGRANT_DEFAULT_PROVIDER=$provider vagrant destroy -f || destroy_status=$?
  if smoke_vm_absent; then
    return 0
  fi
  echo "smoke VM was not destroyed: $vagrant_dir (destroy status $destroy_status)" >&2
  return 1
}

cleanup_smoke() {
  status=$?
  if ! destroy_smoke_vm; then
    if [ "$status" -eq 0 ]; then
      status=1
    fi
  fi
  rm -f "$root/test/.ssh_config_$role"
  trap - EXIT
  exit "$status"
}

cd "$vagrant_dir"
if ! destroy_smoke_vm; then
  echo "refusing to start $role smoke; stale VM remains in $vagrant_dir" >&2
  exit 1
fi
trap cleanup_smoke EXIT
VAGRANT_DEFAULT_PROVIDER=$provider vagrant up --provision
VAGRANT_DEFAULT_PROVIDER=$provider vagrant ssh-config --host "$host_alias" > "$root/test/.ssh_config_$role"
rsync -aH --stats --human-readable -e "ssh -F $root/test/.ssh_config_$role" \
  --exclude .git/ --exclude .vagrant/ --exclude results/ --exclude paper/bin/ \
  --exclude box/ --exclude '*.box' \
  --exclude experiment/tool/.venv/ \
  --exclude __pycache__/ \
  --exclude '*.pyc' \
  --exclude '.ssh_config_*' \
  --exclude '*.tar' --exclude '*.tar.gz' --exclude '*.tgz' \
  "$root/" "$host_alias:/home/vagrant/flooding/"

set +e
ssh -F "$root/test/.ssh_config_$role" "$host_alias" \
  "sh /home/vagrant/flooding/test/inside_smoke.sh $role"
status=$?
set -e
mkdir -p "$vagrant_dir/results"
rsync -aH --stats --human-readable -e "ssh -F $root/test/.ssh_config_$role" \
  "$host_alias:/home/vagrant/flooding/test/$role/results/" "$vagrant_dir/results/" || true
exit "$status"
