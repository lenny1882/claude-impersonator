#!/usr/bin/env bash
# The one Docker box every package's end-to-end tests run in (PLAN §5):
# Ubuntu 24.04 booting systemd, a user `dev`, real Claude
# Code installed for that user. Packages are copied into it from this
# checkout and installed with their own install.sh, so no release is needed
# to test. Fixture data only, never the real corpus.
#
# Same container pattern as repo-remote-control-server's test/docker/confirm.sh.
# Ubuntu 24.04 is the WorkSpace's OS, and its system Python (3.12) is not the
# one embedding-lib bundles, so a test that finds 3.14.10 proves the bundled
# one is used.
#
# usage:
#   test/docker/box.sh up       build the image and start the box
#   test/docker/box.sh start    start a stopped box again (a login survives)
#   test/docker/box.sh status   is it there, running, logged in
#   test/docker/box.sh down     log out, remove the box and its image
#
# Claude Code's login is only needed by packages whose hooks call a model;
# `up` prints the step. embedding-lib's tests don't need it.
#
# Where to run it: your own terminal, or ! in Claude Code. Claude's Bash tool
# can't reach the Docker socket.
#
# Logs to test/docker/results/<time>/run.log, and test/docker/results/latest
# points at the newest run.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/lib.sh"
start_log "box-${1:-help}"

up() {
  down quiet
  echo "==> building $IMAGE (Ubuntu 24.04, systemd, curl, jq, git, python3)"
  docker build -q -t "$IMAGE" - >/dev/null <<-'EOF'
	FROM ubuntu:24.04
	ENV DEBIAN_FRONTEND=noninteractive
	RUN apt-get update -qq && apt-get install -y -qq \
	    systemd systemd-sysv dbus git jq curl ca-certificates procps sudo \
	    bubblewrap socat python3 >/dev/null \
	    && apt-get clean
	RUN systemctl mask getty@tty1.service console-getty.service
	CMD ["/sbin/init"]
	EOF

  echo "==> starting $BOX with systemd"
  docker run -d --name "$BOX" --hostname "$BOX" \
    --privileged --cgroupns=host -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
    --tmpfs /run --tmpfs /run/lock "$IMAGE" >/dev/null
  wait_boot

  echo "==> user $DEV, Claude Code"
  in_box "useradd -m -u $DEV_UID -s /bin/bash $DEV && loginctl enable-linger $DEV"
  as_dev 'curl -fsSL https://claude.ai/install.sh | bash >/dev/null'
  as_dev 'echo "export PATH=\$HOME/.local/bin:\$PATH" >> ~/.profile'
  as_dev 'echo "export DISABLE_AUTOUPDATER=1" >> ~/.profile'
  echo "  $(as_dev 'claude --version' | head -1); system Python $(as_dev 'python3 --version')"
  cat <<-EOF

	$BOX is up. Only for packages whose hooks call a model, log in once, in
	your own terminal:

	  docker exec -it -u $DEV $BOX bash -lc 'claude auth login'

	embedding-lib's tests need no login:

	  packages/embedding-lib/test/docker/e2e.sh
	EOF
}

start() {
  docker start "$BOX" >/dev/null
  wait_boot
  echo "$BOX is running"
}

status() {
  if [[ $(docker inspect -f '{{.State.Running}}' "$BOX" 2>/dev/null) == true ]]; then
    echo "$BOX is running"
    as_dev 'claude auth status' >/dev/null 2>&1 && echo "claude is logged in" || echo "claude is not logged in"
  elif docker inspect "$BOX" >/dev/null 2>&1; then
    echo "$BOX is stopped: test/docker/box.sh start"
  else
    echo "$BOX does not exist: test/docker/box.sh up"
  fi
}

down() {
  if docker exec "$BOX" true >/dev/null 2>&1; then
    docker exec -u "$DEV" "$BOX" bash -lc 'claude auth logout' >/dev/null 2>&1 || true
  fi
  docker rm -f "$BOX" >/dev/null 2>&1 || true
  docker rmi "$IMAGE" >/dev/null 2>&1 || true
  [[ ${1:-} == quiet ]] || echo "logged out, removed $BOX and $IMAGE"
}

need_docker
case "${1:-}" in
  up) up ;;
  start) start ;;
  status) status ;;
  down) down ;;
  *) sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
echo "== finished: box.sh ${1:-}"
