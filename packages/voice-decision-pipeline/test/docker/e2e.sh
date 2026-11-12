#!/usr/bin/env bash
# voice-decision-pipeline for real, in the monorepo's box (test/docker/box.sh):
# the real install.sh after embedding-lib's, the real venv download (spaCy,
# en_core_web_trf), and every command run through the installed binary on
# made-up data (test/fixtures.py, a fake Bitbucket API), on Ubuntu 24.04.
# test/run-tests.sh covers the same steps on this machine; this is where the
# installer, the sandbox exclusion and the uninstall refusal run for real.
#
#   test/docker/box.sh up                        (once, from the repo root)
#   packages/voice-decision-pipeline/test/docker/e2e.sh
#
# Downloads about 1.9 GB for embedding-lib and 1.8 GB for the pipeline's
# venv on the first run. Ends by uninstalling both, so nothing it installed
# stays in the box; the box itself stays up for the next run.
#
# Where to run it: your own terminal, or ! in Claude Code. Claude's Bash tool
# can't reach the Docker socket.
#
# Logs to test/docker/results/<time>-voice-decision-pipeline-e2e/run.log at
# the repo root, results/latest pointing at it; summary.txt there has one
# line per check.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/../../../../test/docker/lib.sh"
start_log voice-decision-pipeline-e2e
need_box

P=voice-decision-pipeline
PKGDIR="$H/pkg/$P"
ELDIR="$H/pkg/embedding-lib"
B="$H/.local/bin/$P"
VH="$H/.local/share/$P"
ST="$H/.claude/$P"
F="$H/vdp-fixtures"
ctx() { as_dev "cd $PKGDIR && $1"; }

cleanup() {
  as_dev "pkill -f fake_bitbucket.py" >/dev/null 2>&1 || true
  as_dev "rm -rf $ST" >/dev/null 2>&1 || true
  ctx './uninstall.sh --yes' >/dev/null 2>&1 || true
  as_dev "cd $ELDIR && ./uninstall.sh --yes" >/dev/null 2>&1 || true
  as_dev "rm -rf $F" >/dev/null 2>&1 || true
}
cleanup
trap cleanup EXIT

echo "==> copying both packages into the box"
copy_package embedding-lib
copy_package "$P"
as_dev 'mkdir -p ~/.claude && [ -f ~/.claude/settings.json ] || echo "{}" > ~/.claude/settings.json'

echo "==> install before embedding-lib: must refuse and say why"
out=$(ctx './install.sh --yes' 2>&1); rc=$?
printf '%s\n' "$out" > "$RESULTS/install-no-el.txt"
check needs-el "install fails without embedding-lib" test "$rc" -ne 0
check needs-el-says "and says to install embedding-lib first" grep -q 'embedding-lib is not installed' "$RESULTS/install-no-el.txt"
ctx './uninstall.sh --yes' >/dev/null 2>&1 || true

echo "==> embedding-lib install --yes (about 1.9 GB)"
as_dev "cd $ELDIR && ./install.sh --yes" > "$RESULTS/el-install.txt" 2>&1
check el-install "embedding-lib installs" grep -q '"ok": true' "$RESULTS/el-install.txt"

echo "==> install with no terminal and no --yes: must refuse, download nothing"
out=$(ctx './install.sh </dev/null' 2>&1); rc=$?
printf '%s\n' "$out" > "$RESULTS/install-no-yes.txt"
check refuse-no-yes "install without --yes and no terminal fails" test "$rc" -ne 0
check refuse-nothing "and no venv was built" as_dev "[ ! -e $VH/venv ]"

echo "==> install --yes: the venv download (about 1.8 GB)"
t0=$(date +%s)
ctx './install.sh --yes' > "$RESULTS/install.txt" 2>&1; rc=$?
echo "  took $(( $(date +%s) - t0 ))s; $(as_dev "du -sh $VH | cut -f1") in $VH"
check install "install --yes succeeds" test "$rc" -eq 0
check probe "the install's probe found both names with spaCy" grep -q '"ok": true' "$RESULTS/install.txt"
check excluded "settings.json excludes the command from the sandbox" \
  as_dev "jq -e '.sandbox.excludedCommands | index(\"$P *\")' ~/.claude/settings.json"
check venv-python "the venv runs on embedding-lib's Python 3.14.10" \
  as_dev "$VH/venv/bin/python -c 'import platform,sys; sys.exit(platform.python_version()!=\"3.14.10\")'"

echo "==> the whole corpus flow on made-up data"
as_dev "python3 $PKGDIR/test/fixtures.py $F"
as_dev "mkdir -p ~/.claude/projects && cp -r $F/projects/. ~/.claude/projects/"
as_dev "nohup python3 $PKGDIR/test/fake_bitbucket.py $F/bitbucket-routes.json > $F/port 2>/dev/null &"
sleep 2
API="http://127.0.0.1:\$(cat $F/port)/2.0"
run() { as_dev "VDP_NETRC=$F/test-netrc VDP_BITBUCKET_API=$API $B $1"; }
check init "init-inputs" run "init-inputs $F/build-inputs.json"
check pick "pick-repos" run "pick-repos ws/new-repo ws/old-repo --me '{me-uuid}'"
run "extract all --gsd-root $F/dev" > "$RESULTS/extract.txt" 2>&1
check extract "extract all reads all four sources" bash -c \
  "grep -q 'corpus/slack.jsonl: 16' '$RESULTS/extract.txt' && grep -q 'corpus/bitbucket.jsonl: 5' '$RESULTS/extract.txt' && grep -q 'corpus/gsd.jsonl: 4' '$RESULTS/extract.txt' && grep -q 'corpus/transcripts.jsonl: 3' '$RESULTS/extract.txt'"
check extract-log "extract logs to /tmp/$P-extract.log" as_dev "test -s /tmp/$P-extract.log"
run "anonymise" > "$RESULTS/anonymise.txt" 2>&1
check anonymise "anonymise with the real spaCy model" grep -q 'ok    anon/slack.jsonl' "$RESULTS/anonymise.txt"
check anon-clean "no real name, email, phone or client name is left in the copies" as_dev \
  "! grep -q -i -e Priya -e Raman -e Gregor -e Whitfield -e Jamie -e acme -e '7700 900123' $ST/anon/*.jsonl"
check leak-check "anonymise ends with a clean leak check" grep -q 'ok    leak check: none of' "$RESULTS/anonymise.txt"
check group-dm "a group DM's name is all pseudonyms, the short handle too" as_dev \
  "grep -q 'mpdm-self-01--colleague-01--colleague-02-1' $ST/anon/slack.jsonl && ! grep -q -- '--tom-1' $ST/anon/slack.jsonl"
run "show bitbucket" > "$RESULTS/show.txt" 2>&1
check show "show bitbucket writes the view through the installed command" bash -c \
  "grep -q 'views/bitbucket.txt' '$RESULTS/show.txt'"
check show-view "the view holds your reply and the inline code" as_dev \
  "grep -q 'replying to Priya Raman' $ST/views/bitbucket.txt && grep -q '| +import json' $ST/views/bitbucket.txt"
check show-log "show logs to /tmp/$P-show.log" as_dev "test -s /tmp/$P-show.log"
check mining "the client product is a mining candidate" as_dev "jq -e 'map(.term)|index(\"Zephyrline\")' $ST/mining-candidates.json"
check gate "a batch can't be drawn while it's undecided" as_dev "! $B batch slack"
run "index" > "$RESULTS/index.txt" 2>&1
check index "the index is embedded by embedding-lib" as_dev "jq -e '.model==\"BAAI/bge-base-en-v1.5\"' $ST/index/identity.json"
check owner-only "state is owner-only" as_dev "[ -z \"\$(find $ST -perm /077 -print -quit)\" ]"
check forget "forget removes a person and strikes them" as_dev \
  "$B forget 'Gregor Whitfield' && ! grep -q UCLIGREGR $ST/corpus/slack.jsonl && jq -e '.struck_authors|index(\"UCLIGREGR\")' $ST/inputs.json"

echo "==> reinstall: nothing to download"
ctx './install.sh --yes' > "$RESULTS/reinstall.txt" 2>&1; rc=$?
check reinstall "reinstall succeeds" test "$rc" -eq 0
check reinstall-nodl "and builds nothing" grep -q 'nothing to do' "$RESULTS/reinstall.txt"
check reinstall-state "and the state is untouched" as_dev "test -f $ST/anonymising-map.json"

echo "==> uninstall refuses while live files exist"
ctx './uninstall.sh --yes' > "$RESULTS/uninstall-refused.txt" 2>&1; rc=$?
check uninstall-refuses "uninstall fails" test "$rc" -ne 0
check uninstall-says "and names the live files" grep -q 'anonymising-map.json' "$RESULTS/uninstall-refused.txt"
check uninstall-kept "and nothing was removed" as_dev "[ -x $B ] && [ -f $ST/anonymising-map.json ]"

echo "==> uninstall --keep-state"
ctx './uninstall.sh --yes --keep-state' > "$RESULTS/uninstall.txt" 2>&1; rc=$?
check uninstall "uninstall --keep-state succeeds" test "$rc" -eq 0
check uninstall-gone "the command and the venv are gone" as_dev "[ ! -e $B ] && [ ! -e $VH ]"
check uninstall-state "the state is kept" as_dev "test -f $ST/anonymising-map.json"
check uninstall-settings "the sandbox exclusion is removed" as_dev "! grep -q '$P' ~/.claude/settings.json"
trap - EXIT
cleanup

printf '\n== finished: %s e2e, %d passed, %d failed\n' "$P" "$PASSES" "$FAILS" | tee -a "$RESULTS/summary.txt"
[ "$FAILS" -eq 0 ]
