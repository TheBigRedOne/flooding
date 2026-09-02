#!/bin/sh
# Host entry for the pure-R2 NFD runtime gate.
# Uses the already-existing experiment/solution Vagrant VM.
# Never destroys, never provisions, never reloads the solution box.
set -eu

PROVIDER=${PROVIDER:-libvirt}
REQUIRED_NFD_VERSION='24.07+git.56b8d8db'
REMOTE_DIR=/home/vagrant/flooding
REMOTE_RUNTIME=${REMOTE_DIR}/test/r2-runtime
HOST_ALIAS=solution

usage() {
  echo "usage: $0 A|CF|R|all" >&2
  exit 2
}

if [ "$#" -ne 1 ]; then
  usage
fi

cell_arg=$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')
case "$cell_arg" in
  A|CF|R|ALL) ;;
  *) usage ;;
esac

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
VAGRANT_DIR=${ROOT}/experiment/solution
SSH_CONFIG=${ROOT}/test/.ssh_config_r2_runtime
HOST_RESULTS=${ROOT}/test/r2-runtime-results

if [ ! -f "${VAGRANT_DIR}/Vagrantfile" ]; then
  echo "FAIL: missing ${VAGRANT_DIR}/Vagrantfile" >&2
  exit 1
fi

vagrant_cmd() {
  VAGRANT_DEFAULT_PROVIDER="$PROVIDER" VAGRANT_CWD="$VAGRANT_DIR" vagrant "$@"
}

echo "*** R2 runtime gate: PROVIDER=${PROVIDER} VAGRANT_CWD=experiment/solution"

# --- VM state: refuse not_created; start halted VMs without provisioning ---
status=$(vagrant_cmd status --machine-readable | awk -F, '$3 == "state" { print $4; exit }')
if [ -z "$status" ]; then
  echo "FAIL: could not read Vagrant machine state" >&2
  exit 1
fi
echo "*** Vagrant machine state: ${status}"

case "$status" in
  not_created)
    echo "FAIL: experiment/solution VM is not_created." >&2
    echo "Refusing vagrant up so the old solution box cannot be instantiated." >&2
    exit 1
    ;;
  running)
    ;;
  poweroff|aborted|saved|shutoff)
    echo "*** Starting existing VM with vagrant up --no-provision"
    vagrant_cmd up --no-provision
    ;;
  *)
    echo "FAIL: unsupported Vagrant state '${status}'" >&2
    echo "Refusing operations that could recreate or provision the VM." >&2
    exit 1
    ;;
esac

vagrant_cmd ssh-config --host "$HOST_ALIAS" > "$SSH_CONFIG"
ssh_base() {
  ssh -F "$SSH_CONFIG" -o TCPKeepAlive=no -o ServerAliveInterval=10 "$@"
}

# --- NFD version preflight (before rsync/build/run) ---
remote_nfd_path=$(ssh_base "$HOST_ALIAS" 'command -v nfd || true')
if [ -z "$remote_nfd_path" ]; then
  echo "FAIL: nfd is not on PATH in the experiment/solution VM" >&2
  exit 1
fi
remote_nfd_version=$(ssh_base "$HOST_ALIAS" 'nfd --version')
echo "*** remote nfd: ${remote_nfd_path}"
echo "*** remote nfd --version: ${remote_nfd_version}"
if [ "$remote_nfd_version" != "$REQUIRED_NFD_VERSION" ]; then
  echo "FAIL: NFD version mismatch." >&2
  echo "  required: ${REQUIRED_NFD_VERSION}" >&2
  echo "  actual:   ${remote_nfd_version}" >&2
  echo "Refusing to run any cell." >&2
  exit 1
fi

# --- Rsync only harness + application sources/assets ---
ssh_base "$HOST_ALIAS" "mkdir -p ${REMOTE_DIR}/test ${REMOTE_DIR}/experiment/app ${REMOTE_RUNTIME}"
rsync -avH -e "ssh -F ${SSH_CONFIG} -o TCPKeepAlive=no -o ServerAliveInterval=10" \
  "${ROOT}/test/r2_runtime.py" \
  "${ROOT}/test/validate_r2.py" \
  "$HOST_ALIAS:${REMOTE_DIR}/test/"
rsync -avH -e "ssh -F ${SSH_CONFIG} -o TCPKeepAlive=no -o ServerAliveInterval=10" \
  "${ROOT}/experiment/app/producer.cpp" \
  "${ROOT}/experiment/app/consumer.cpp" \
  "${ROOT}/experiment/app/optoflood-daemon.cpp" \
  "${ROOT}/experiment/app/trust-schema.conf" \
  "$HOST_ALIAS:${REMOTE_DIR}/experiment/app/"

echo "*** Compiling candidate binaries in ${REMOTE_RUNTIME}"
ssh_base "$HOST_ALIAS" "set -e
  . /home/vagrant/.profile >/dev/null 2>&1 || true
  export PATH=\"/usr/local/bin:\$HOME/.local/bin:\$PATH\"
  export LD_LIBRARY_PATH=\"\${LD_LIBRARY_PATH:-}:/usr/local/lib64:/usr/local/lib\"
  export PKG_CONFIG_PATH=\"\${PKG_CONFIG_PATH:-}:/usr/local/lib64/pkgconfig:/usr/local/lib/pkgconfig\"
  mkdir -p ${REMOTE_RUNTIME}
  cd ${REMOTE_RUNTIME}
  rm -f producer consumer optoflood-daemon
  PKG=\$(pkg-config --cflags --libs libndn-cxx)
  g++ -std=c++17 -g -O2 -o producer ${REMOTE_DIR}/experiment/app/producer.cpp \$PKG
  g++ -std=c++17 -g -O2 -o consumer ${REMOTE_DIR}/experiment/app/consumer.cpp \$PKG
  g++ -std=c++17 -g -O2 -o optoflood-daemon ${REMOTE_DIR}/experiment/app/optoflood-daemon.cpp \$PKG
  chmod +x producer consumer optoflood-daemon
  cp -f ${REMOTE_DIR}/experiment/app/trust-schema.conf ${REMOTE_RUNTIME}/
"

run_one_cell() {
  cell=$1
  echo "*** Running cell ${cell}"
  mkdir -p "${HOST_RESULTS}/${cell}"
  ssh_rc=0
  ssh_base "$HOST_ALIAS" "set -e
    . /home/vagrant/.profile >/dev/null 2>&1 || true
    export PATH=\"/usr/local/bin:\$HOME/.local/bin:\$PATH\"
    export LD_LIBRARY_PATH=\"\${LD_LIBRARY_PATH:-}:/usr/local/lib64:/usr/local/lib\"
    mkdir -p ${REMOTE_RUNTIME}/results/${cell}
    cd ${REMOTE_RUNTIME}
    rt=0
    /usr/bin/sudo -E env \
      PATH=\"\$PATH\" \
      LD_LIBRARY_PATH=\"\$LD_LIBRARY_PATH\" \
      PYTHONUNBUFFERED=1 \
      EXPERIMENT_DIR=${REMOTE_RUNTIME} \
      R2_CELL=${cell} \
      R2_REQUIRED_NFD_VERSION=${REQUIRED_NFD_VERSION} \
      python3 ${REMOTE_DIR}/test/r2_runtime.py || rt=\$?
    /usr/bin/sudo chown -R vagrant:vagrant ${REMOTE_RUNTIME}/results/${cell}
    val=0
    python3 ${REMOTE_DIR}/test/validate_r2.py ${cell} ${REMOTE_RUNTIME}/results/${cell} || val=\$?
    echo rt=\$rt val=\$val > ${REMOTE_RUNTIME}/results/${cell}/exit_codes.txt
    if [ \"\$val\" -ne 0 ]; then exit \"\$val\"; fi
    if [ \"\$rt\" -ne 0 ]; then exit \"\$rt\"; fi
  " || ssh_rc=$?
  rsync -avH -e "ssh -F ${SSH_CONFIG} -o TCPKeepAlive=no -o ServerAliveInterval=10" \
    "$HOST_ALIAS:${REMOTE_RUNTIME}/results/${cell}/" \
    "${HOST_RESULTS}/${cell}/" || true
  echo "*** Cell ${cell} artifacts: ${HOST_RESULTS}/${cell}/"
  return "$ssh_rc"
}

rc=0
if [ "$cell_arg" = "ALL" ]; then
  run_one_cell A || rc=$?
  run_one_cell CF || rc=$?
  run_one_cell R || rc=$?
else
  run_one_cell "$cell_arg" || rc=$?
fi

echo "*** R2 runtime gate finished (leave experiment/solution VM running; no destroy/halt)"
exit "$rc"
