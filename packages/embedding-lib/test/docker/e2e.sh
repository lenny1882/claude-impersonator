#!/usr/bin/env bash
# embedding-lib for real, in the monorepo's box (test/docker/box.sh): the real
# download from github.com, PyPI, PyTorch and Hugging Face, the real
# install.sh and uninstall.sh, on Ubuntu 24.04, whose system Python (3.12)
# isn't the bundled one. test/run-tests.sh stubs the downloads; this is where
# they happen.
#
#   test/docker/box.sh up                        (once, from the repo root)
#   packages/embedding-lib/test/docker/e2e.sh
#
# About 1.9 GB downloads into the box on the first install. The repair step
# downloads the Python again (35 MB) and reinstalls the libraries from pip's
# cache in the box.
#
# Ends by uninstalling, so nothing it installed stays in the box; the box
# itself stays up for the next run.
#
# Where to run it: your own terminal, or ! in Claude Code. Claude's Bash tool
# can't reach the Docker socket.
#
# Logs to test/docker/results/<time>-embedding-lib-e2e/run.log at the repo
# root, results/latest pointing at it; summary.txt there has one line per
# check.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/../../../../test/docker/lib.sh"
start_log embedding-lib-e2e
need_box

PKGDIR="$H/pkg/embedding-lib"
EL="$H/.local/share/embedding-lib"
B="$H/.local/bin/embedding-lib"
ctx() { as_dev "cd $PKGDIR && $1"; }

cleanup() { ctx './uninstall.sh --yes' >/dev/null 2>&1 || true; }
cleanup
trap cleanup EXIT

echo "==> copying the package into the box"
copy_package embedding-lib
as_dev 'mkdir -p ~/.claude && [ -f ~/.claude/settings.json ] || echo "{}" > ~/.claude/settings.json'

echo "==> install with no terminal and no --yes: must refuse, download nothing"
out=$(ctx './install.sh </dev/null' 2>&1); rc=$?
printf '%s\n' "$out" > "$RESULTS/install-no-yes.txt"
check refuse-no-yes "install without --yes and no terminal fails" test "$rc" -ne 0
check refuse-says "and says to use --yes" grep -q 'setup --yes' "$RESULTS/install-no-yes.txt"
check refuse-nothing "and nothing was downloaded" as_dev "[ ! -e $EL/python ] && [ ! -e $EL/venv ] && [ ! -e $EL/hf ]"

echo "==> install --yes: the real download (about 1.9 GB)"
t0=$(date +%s)
ctx './install.sh --yes' > "$RESULTS/install.txt" 2>&1; rc=$?
echo "  took $(( $(date +%s) - t0 ))s; $(as_dev "du -sh $EL | cut -f1") in $EL"
check install "install --yes succeeds" test "$rc" -eq 0
check probe "the install's probe embedded test sentences" grep -q '"ok": true' "$RESULTS/install.txt"

id=$(as_dev "$B identity" 2>&1)
printf '%s\n' "$id" > "$RESULTS/identity.json"
check bundled-python "identity says Python 3.14.10, not the box's $(as_dev 'python3 --version')" \
  grep -q '"python": "3.14.10"' "$RESULTS/identity.json"
check cpu-torch "torch is the CPU build" grep -q '"torch": "2.15.0+cpu"' "$RESULTS/identity.json"
check no-cuda "no CUDA libraries were installed" \
  as_dev "! ls $EL/venv/lib/python3.14/site-packages | grep -qi '^nvidia'"

out=$(as_dev "printf '{\"id\":1,\"text\":\"Can you review the PR?\"}\n{\"id\":2,\"text\":\"Please take a look at my pull request\"}\n' | $B embed" 2>&1)
printf '%s\n' "$out" > "$RESULTS/embed.jsonl"
check embed "embed gives two 768-wide vectors" \
  python3 -c "import json,sys; r=[json.loads(l) for l in open(sys.argv[1])]; sys.exit(not (len(r)==2 and all(len(x['vector'])==768 for x in r)))" "$RESULTS/embed.jsonl"

echo "==> offline: embed with every proxy and Hugging Face pointed at a closed port"
check offline "embedding needs no network" as_dev \
  "https_proxy=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 HF_ENDPOINT=http://127.0.0.1:9 $B check"

echo "==> identity: the same record matches; another Python is refused"
check id-match "the record matches its own environment" as_dev "$B identity | $B check-identity"
check id-refuse "a record from Python 3.12 is refused with exit 3" as_dev \
  "$B identity | sed 's/\"python\": \"3.14.10\"/\"python\": \"3.12.3\"/' | $B check-identity; [ \$? -eq 3 ]"

echo "==> reinstall: nothing to download"
t0=$(date +%s)
ctx './install.sh --yes' > "$RESULTS/reinstall.txt" 2>&1; rc=$?
secs=$(( $(date +%s) - t0 ))
check reinstall "reinstall succeeds" test "$rc" -eq 0
check reinstall-nodl "and downloads nothing (${secs}s)" grep -q 'nothing to download' "$RESULTS/reinstall.txt"

echo "==> a venv whose Python has gone, as when a system Python moves"
as_dev "mv $EL/python $EL/python.gone"
out=$(as_dev "$B check" 2>&1); rc=$?
printf '%s\n' "$out" > "$RESULTS/broken.txt"
check broken-exit "a broken environment exits 4" test "$rc" -eq 4
check broken-says "and says to run setup" grep -q 'run: embedding-lib setup' "$RESULTS/broken.txt"
as_dev "rm -rf $EL/python.gone"
as_dev "$B setup --yes" > "$RESULTS/repair.txt" 2>&1; rc=$?
check repair "setup --yes repairs it" test "$rc" -eq 0
check repair-works "and check passes again" as_dev "$B check"
check repair-model "without downloading the model again" bash -c "! grep -q '== Model' '$RESULTS/repair.txt'"

echo "==> uninstall"
ctx './uninstall.sh --yes' > "$RESULTS/uninstall.txt" 2>&1; rc=$?
check uninstall "uninstall succeeds" test "$rc" -eq 0
check uninstall-gone "the command and everything in ~/.local/share/embedding-lib are gone" \
  as_dev "[ ! -e $B ] && [ ! -e $EL ]"
check uninstall-settings "settings.json has no embedding-lib entries" \
  as_dev "! grep -q embedding-lib ~/.claude/settings.json"
trap - EXIT

printf '\n== finished: embedding-lib e2e, %d passed, %d failed\n' "$PASSES" "$FAILS" | tee -a "$RESULTS/summary.txt"
[ "$FAILS" -eq 0 ]
