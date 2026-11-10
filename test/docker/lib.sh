# Shared by test/docker/box.sh and every package's test/docker scripts.
# Defines things; runs nothing.

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
BOX=impersonator-box
IMAGE=impersonator-box-image
DEV=dev
DEV_UID=1500
H=/home/$DEV

# Every script logs all it prints to results/<time>/run.log, so a run in
# James's terminal can be read afterwards; results/latest is the newest.
start_log() { # start_log <name>
  local base="$ROOT/test/docker/results"
  RESULTS=${RESULTS:-$base/$(date +%Y%m%d-%H%M%S)-$1}
  mkdir -p "$RESULTS"
  ln -sfn "$(basename "$RESULTS")" "$base/latest"
  exec > >(tee -a "$RESULTS/run.log") 2>&1
  echo "== $1, $(date -Is), log: $RESULTS/run.log"
}

need_docker() {
  docker info >/dev/null 2>&1 && return 0
  echo "Can't reach Docker. Run this in your own terminal, or with ! in Claude Code."
  echo "Claude's own Bash tool can't: its sandbox blocks the Docker socket."
  exit 1
}

need_box() {
  need_docker
  [[ $(docker inspect -f '{{.State.Running}}' "$BOX" 2>/dev/null) == true ]] && return 0
  docker inspect "$BOX" >/dev/null 2>&1 \
    && echo "$BOX is stopped: test/docker/box.sh start" \
    || echo "$BOX does not exist: test/docker/box.sh up"
  exit 1
}

in_box() { docker exec -i "$BOX" bash -c "$1"; }
as_dev() { docker exec -i -u "$DEV" -w "$H" "$BOX" bash -lc "$1"; }

wait_boot() {
  local state=
  for _ in $(seq 1 60); do
    state=$(docker exec "$BOX" systemctl is-system-running 2>/dev/null || true)
    [[ $state == running || $state == degraded ]] && return 0
    sleep 2
  done
  echo "$BOX did not finish booting (state: $state)"
  exit 1
}

# copy_package <name>: packages/<name> from this checkout to ~/pkg/<name> in
# the box, without test results or the sandbox's mount points.
copy_package() {
  as_dev "rm -rf ~/pkg/$1 && mkdir -p ~/pkg/$1"
  tar -C "$ROOT/packages/$1" --exclude=./test/docker/results --exclude=.claude \
    --exclude=.mcp.json -cf - . | docker exec -i -u "$DEV" "$BOX" tar -C "$H/pkg/$1" -xf -
}

PASSES=0; FAILS=0
result() { # result PASS|FAIL <check> <what>
  printf '  %-4s  %-22s %s\n' "$1" "$2" "$3" | tee -a "$RESULTS/summary.txt"
  if [ "$1" = PASS ]; then PASSES=$((PASSES+1)); else FAILS=$((FAILS+1)); fi
}
check() { # check <name> <what> <command...>: PASS if the command succeeds
  local name=$1 what=$2; shift 2
  if "$@"; then result PASS "$name" "$what"; else result FAIL "$name" "$what"; fi
}
