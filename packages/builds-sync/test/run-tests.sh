#!/usr/bin/env bash
# Tests for builds-sync.
#
# Redirects HOME and CLAUDE_DIR into a temp directory, so the real config is
# never touched. The "remote" is a bare git repo in that directory, and `age`
# and `age-keygen` are stand-ins from test/fake-bin (a reversible transform
# that fails without the right key), because age is not installed on every
# machine this runs on. test/fake-runtime holds a voice-runtime that records
# its install-build call. Nothing is installed on the machine.
#
# Two machines are simulated with BUILDS_SYNC_HOSTNAME: "alpha" uses the
# installed command and $CLAUDE_DIR, "beta" runs the checkout's command with
# its own CLAUDE_DIR and clone.
#
# Logs to /tmp/builds-sync-tests.log (BUILDS_SYNC_TEST_LOG to move it).
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${BUILDS_SYNC_TEST_LOG:-/tmp/builds-sync-tests.log}"
exec > >(tee "$LOG") 2>&1
echo "== builds-sync tests, $(date -Is)"

TMP=$(mktemp -d)
HOLDER=""
cleanup() { [ -n "$HOLDER" ] && kill "$HOLDER" 2>/dev/null; rm -rf "$TMP"; }
trap cleanup EXIT
export HOME="$TMP/home"; mkdir -p "$HOME"
export CLAUDE_DIR="$TMP/claude"; mkdir -p "$CLAUDE_DIR"
export KIT_SKIP_MACHINE_HOOKS=1   # pre_install and post_install change the real machine, not $HOME
unset BUILDS_SYNC_CLONE BUILDS_SYNC_KEY BUILDS_SYNC_LOCK_TIMEOUT
export BUILDS_SYNC_INSTALL_LOG="$TMP/install.log"
export GIT_CONFIG_NOSYSTEM=1

pass=0; fail=0
ok(){ printf '  ok    %s\n' "$1"; pass=$((pass+1)); }
no(){ printf '  FAIL  %s\n    %s\n' "$1" "$2"; fail=$((fail+1)); }
check(){ # check <name> <command...>: passes when the command succeeds
  local name="$1"; shift
  if out=$("$@" 2>&1); then ok "$name"; else no "$name" "$(printf '%s' "$out" | tail -3)"; fi
}

. "$REPO/test/installer-tests.sh"

echo "setup"
"$REPO/install.sh" --yes >"$TMP/out" 2>&1 && ok "installs (copy) for the behaviour tests" \
  || no "installs (copy) for the behaviour tests" "$(tail -5 "$TMP/out")"
for e in "builds-sync hook session-start" "builds-sync hook session-end"; do
  jq -e --arg e "$e" '[.hooks[][].hooks[].command] | any(endswith($e))' "$CLAUDE_DIR/settings.json" >/dev/null \
    && ok "registers $e" || no "registers $e" "$(jq -c .hooks "$CLAUDE_DIR/settings.json")"
done
jq -e '.hooks.SessionEnd' "$CLAUDE_DIR/settings.json" >/dev/null && ok "the push is on SessionEnd" \
  || no "the push is on SessionEnd" "no SessionEnd entry"

export PATH="$REPO/test/fake-bin:$HOME/.local/bin:$PATH"
BS="$HOME/.local/bin/builds-sync"
BETA_CLAUDE="$TMP/claude-beta"; mkdir -p "$BETA_CLAUDE"
beta(){ CLAUDE_DIR="$BETA_CLAUDE" BUILDS_SYNC_HOSTNAME=beta BUILDS_SYNC_CLONE="$TMP/clone-b" \
        "$REPO/skill/bin/builds-sync" "$@"; }
export BUILDS_SYNC_HOSTNAME=alpha
STATE="$CLAUDE_DIR/skills/builds-sync/state"
RT="$TMP/runtime-bin"; mkdir -p "$RT"; cp "$REPO/test/fake-runtime/voice-runtime" "$RT/"
export FAKE_RUNTIME_CALLS="$TMP/runtime-calls" FAKE_RUNTIME_GOT="$TMP/runtime-got"

mkdir -p "$HOME/.config/age"
age-keygen -o "$HOME/.config/age/builds.key"
git init -q --bare "$TMP/remote.git"
git -C "$TMP/remote.git" symbolic-ref HEAD refs/heads/main
git clone -q "$TMP/remote.git" "$TMP/seed" 2>/dev/null
( cd "$TMP/seed" && git checkout -q -b main && echo "Encrypted builds; nothing readable here." > README.md \
  && git add README.md && git -c user.name=t -c user.email=t@t commit -qm init && git push -q origin main )
remote_files(){ git -C "$TMP/remote.git" ls-tree -r --name-only main; }
remote_head(){ git -C "$TMP/remote.git" rev-parse main; }

"$BS" status 2>&1 | grep -q "not set up" && ok "status before setup says it is not set up" \
  || no "status before setup says it is not set up" "$("$BS" status 2>&1 | head -3)"
"$BS" push >"$TMP/out" 2>&1; [ $? = 1 ] && grep -q "builds-sync setup" "$TMP/out" \
  && ok "push before setup refuses and names setup" || no "push before setup refuses and names setup" "$(cat "$TMP/out")"
"$BS" setup --clone "$TMP/clone-a" --remote "$TMP/remote.git" --yes >"$TMP/out" 2>&1 \
  && [ -f "$TMP/clone-a/README.md" ] && ok "setup clones the remote" || no "setup clones the remote" "$(cat "$TMP/out")"
jq -e --arg c "$TMP/clone-a" '.clone == $c' "$STATE/config.json" >/dev/null \
  && ok "setup records the clone's location in state" || no "setup records the clone's location in state" "$(cat "$STATE/config.json" 2>&1)"
"$BS" setup --yes | grep -q "clone-a" && ok "setup again keeps what was recorded" || no "setup again keeps what was recorded" "-"
git clone -q "$TMP/remote.git" "$TMP/clone-b" 2>/dev/null
[ "$("$BS" api)" = 1 ] && ok "BUILDS_SYNC_API is 1" || no "BUILDS_SYNC_API is 1" "$("$BS" api 2>&1)"

echo "publish and install"
mkbuild(){ # mkbuild <dir> <marker>: a build tarball with a voice-runtime and an unknown runtime
  local d="$TMP/build-src-$2"; rm -rf "$d"; mkdir -p "$d/voice-runtime" "$d/other-runtime"
  for f in guide exemplars stats build; do printf '{"schema_version":1,"marker":"%s-%s"}\n' "$2" "$f" > "$d/voice-runtime/$f.json"; done
  echo '{}' > "$d/other-runtime/x.json"
  tar -cf "$1" -C "$d" voice-runtime other-runtime
}
BT1=20261101T100000Z; BT2=20261102T100000Z; BT3=20261103T100000Z
mkbuild "$TMP/b1.tar" plainmarker1
echo "key"
chmod 644 "$HOME/.config/age/builds.key"
"$BS" publish "$TMP/b1.tar" --build-time $BT1 >"$TMP/out" 2>&1
grep -q "chmod 600" "$TMP/out" && ok "a key readable by others is refused" || no "a key readable by others is refused" "$(cat "$TMP/out")"
chmod 600 "$HOME/.config/age/builds.key"
BUILDS_SYNC_KEY="$TMP/nowhere.key" "$BS" publish "$TMP/b1.tar" --build-time $BT1 >"$TMP/out" 2>&1
grep -q "no key at $TMP/nowhere.key" "$TMP/out" && ok "a missing key is named (BUILDS_SYNC_KEY moves it)" || no "a missing key is named (BUILDS_SYNC_KEY moves it)" "$(cat "$TMP/out")"
remote_files | grep -q "^builds/" && no "nothing is published without a usable key" "$(remote_files)" || ok "nothing is published without a usable key"
"$BS" publish /dev/null --build-time 20260101T000000Z >"$TMP/out" 2>&1
[ $? != 0 ] && grep -q "not a tar file" "$TMP/out" && ok "publish of a non-tar is refused" || no "publish of a non-tar is refused" "$(cat "$TMP/out")"

out=$("$BS" publish "$TMP/b1.tar" --build-time $BT1 2>&1)
[ "$out" = "builds/$BT1.tar.age" ] && ok "publish prints the repo path" || no "publish prints the repo path" "$out"
remote_files | grep -qx "builds/$BT1.tar.age" && ok "publish pushes builds/<bt>.tar.age" || no "publish pushes builds/<bt>.tar.age" "$(remote_files)"
git -C "$TMP/remote.git" show "main:builds/$BT1.tar.age" | grep -q plainmarker1 \
  && no "the pushed build is encrypted" "plaintext found" || ok "the pushed build is encrypted"
h=$(remote_head)
"$BS" publish "$TMP/b1.tar" --build-time $BT1 >/dev/null 2>&1 && [ "$(remote_head)" = "$h" ] \
  && ok "publishing the same build again adds no commit" || no "publishing the same build again adds no commit" "-"
mkbuild "$TMP/b1x.tar" other
"$BS" publish "$TMP/b1x.tar" --build-time $BT1 >"$TMP/out" 2>&1
[ $? != 0 ] && grep -q "different contents" "$TMP/out" && ok "a different build under the same time is refused" \
  || no "a different build under the same time is refused" "$(cat "$TMP/out")"
"$BS" publish "$TMP/b1.tar" --build-time 2026-11-01 >/dev/null 2>&1 \
  && no "a malformed build time is refused" "accepted" || ok "a malformed build time is refused"
mkdir -p "$TMP/evil"; echo x > "$TMP/evil/top.json"; tar -cf "$TMP/evil.tar" -C "$TMP/evil" top.json
"$BS" publish "$TMP/evil.tar" --build-time $BT2 >/dev/null 2>&1 \
  && no "a tarball with a file at the top level is refused" "accepted" || ok "a tarball with a file at the top level is refused"
mkbuild "$TMP/b2.tar" plainmarker2
"$BS" publish "$TMP/b2.tar" --build-time $BT2 >/dev/null 2>&1 || no "second publish" "failed"

"$BS" install >"$TMP/out" 2>&1; rc=$?
[ $rc = 1 ] && grep -q "nothing installed" "$TMP/out" && ok "install with no runtime on this machine installs nothing and says so" \
  || no "install with no runtime on this machine installs nothing and says so" "rc=$rc $(tail -3 "$TMP/out")"
export PATH="$RT:$PATH"
"$BS" install >"$TMP/out" 2>&1 && ok "install exits 0" || no "install exits 0" "$(tail -5 "$TMP/out")"
grep -qE "^install-build .*/voice-runtime --build-time $BT2\$" "$FAKE_RUNTIME_CALLS" \
  && ok "install runs voice-runtime install-build <tmp>/voice-runtime --build-time <newest>" \
  || no "install runs voice-runtime install-build <tmp>/voice-runtime --build-time <newest>" "$(cat "$FAKE_RUNTIME_CALLS" 2>&1)"
grep -q plainmarker2-guide "$FAKE_RUNTIME_GOT/guide.json" && [ -f "$FAKE_RUNTIME_GOT/build.json" ] \
  && ok "the runtime is handed its decrypted directory" || no "the runtime is handed its decrypted directory" "$(ls "$FAKE_RUNTIME_GOT" 2>&1)"
[ "$(tail -1 "$FAKE_RUNTIME_CALLS.modes")" = 700 ] && ok "the temp directory is mode 700" \
  || no "the temp directory is mode 700" "$(cat "$FAKE_RUNTIME_CALLS.modes")"
d=$(sed -n 's/^install-build \(.*\)\/voice-runtime .*/\1/p' "$FAKE_RUNTIME_CALLS" | tail -1)
[ -n "$d" ] && [ ! -e "$d" ] && ok "the temp directory is removed afterwards" || no "the temp directory is removed afterwards" "$d"
grep -q "skip other-runtime: not installed" "$BUILDS_SYNC_INSTALL_LOG" && ok "a runtime not on this machine is skipped, in the log" \
  || no "a runtime not on this machine is skipped, in the log" "$(cat "$BUILDS_SYNC_INSTALL_LOG")"
tail -1 "$BUILDS_SYNC_INSTALL_LOG" | grep -q "install finished: ok" && ok "the log ends with the result" \
  || no "the log ends with the result" "$(tail -2 "$BUILDS_SYNC_INSTALL_LOG")"
"$BS" install $BT1 >/dev/null 2>&1 && tail -1 "$FAKE_RUNTIME_CALLS" | grep -q "build-time $BT1\$" \
  && ok "install <build-time> installs that older build" || no "install <build-time> installs that older build" "$(tail -1 "$FAKE_RUNTIME_CALLS")"
"$BS" install 20200101T000000Z >"$TMP/out" 2>&1
[ $? != 0 ] && grep -q "no build 20200101T000000Z" "$TMP/out" && ok "install of a build not in the repo fails, naming it" \
  || no "install of a build not in the repo fails, naming it" "$(cat "$TMP/out")"
FAKE_RUNTIME_FAIL=1 "$BS" install $BT1 >/dev/null 2>&1 \
  && no "a failing install-build fails the install" "exit 0" || ok "a failing install-build fails the install"
grep -q "FAIL voice-runtime" "$BUILDS_SYNC_INSTALL_LOG" && ok "the failure is in the log" || no "the failure is in the log" "$(tail -3 "$BUILDS_SYNC_INSTALL_LOG")"
"$BS" status | grep -q "voice-runtime: *$BT1" && ok "status says which build this machine runs" \
  || no "status says which build this machine runs" "$("$BS" status)"

echo "push"
DRAFTS="$CLAUDE_DIR/skills/voice-runtime/state/drafts.jsonl"
printf '{"id":"a1","text":"one"}\n{"id":"a2","text":"two"}\n{"id":"a3","te' > "$DRAFTS"
"$BS" push >"$TMP/out" 2>&1 && ok "push exits 0" || no "push exits 0" "$(cat "$TMP/out")"
segs(){ remote_files | grep "^live/$1/$2/" ; }
[ "$(segs alpha voice-runtime | wc -l)" = 1 ] && segs alpha voice-runtime | grep -qE '/[0-9]{8}T[0-9]{6}Z\.jsonl\.age$' \
  && ok "push writes live/<hostname>/<package>/<push-time>.jsonl.age" || no "push writes live/<hostname>/<package>/<push-time>.jsonl.age" "$(remote_files)"
seg1=$(segs alpha voice-runtime | head -1)
git -C "$TMP/remote.git" show "main:$seg1" > "$TMP/seg.age"
grep -q '"a1"' "$TMP/seg.age" && no "segments are encrypted" "plaintext" || ok "segments are encrypted"
age -d -i "$HOME/.config/age/builds.key" -o "$TMP/seg.txt" "$TMP/seg.age"
[ "$(wc -l < "$TMP/seg.txt")" = 2 ] && ! grep -q a3 "$TMP/seg.txt" \
  && ok "a segment holds complete lines only" || no "a segment holds complete lines only" "$(cat "$TMP/seg.txt")"
h=$(remote_head)
"$BS" push >"$TMP/out" 2>&1; [ "$(remote_head)" = "$h" ] && grep -q "nothing new" "$TMP/out" \
  && ok "pushing again adds nothing" || no "pushing again adds nothing" "$(cat "$TMP/out")"
printf 'xt":"three"}\n{"id":"a4","text":"four"}\n' >> "$DRAFTS"
"$BS" push >/dev/null 2>&1
seg2=$(segs alpha voice-runtime | sort | tail -1)
git -C "$TMP/remote.git" show "main:$seg2" > "$TMP/seg.age"; age -d -i "$HOME/.config/age/builds.key" -o "$TMP/seg.txt" "$TMP/seg.age"
[ "$seg2" != "$seg1" ] && [ "$(cat "$TMP/seg.txt")" = "$(printf '{"id":"a3","text":"three"}\n{"id":"a4","text":"four"}')" ] \
  && ok "the next push carries only the records added since" || no "the next push carries only the records added since" "$(cat "$TMP/seg.txt")"
[ "$("$BS" pending)" = "{}" ] && ok "nothing pending after a push" || no "nothing pending after a push" "$("$BS" pending)"

echo "read_live"
mkdir -p "$BETA_CLAUDE/skills/voice-runtime/state"
printf '{"id":"a2","text":"two"}\n{"text":"five","id":"b5"}\n' > "$BETA_CLAUDE/skills/voice-runtime/state/drafts.jsonl"
sleep 1   # push times are whole seconds; keep the order these tests expect
beta push >"$TMP/out" 2>&1 && segs beta voice-runtime | grep -q . && ok "a second machine pushes to its own live/<hostname>/" \
  || no "a second machine pushes to its own live/<hostname>/" "$(cat "$TMP/out"; remote_files)"
# A rewritten file (a migration) is re-sent from the start: exact repeats.
sleep 1
printf '{"id":"a1","text":"one"}\n{"id":"a2","text":"two"}\n{"id":"a3","text":"three"}\n{"id":"a4","text":"FOUR"}\n' > "$DRAFTS"
"$BS" push >/dev/null 2>&1
[ "$(segs alpha voice-runtime | wc -l)" = 3 ] && ok "a rewritten live file is re-sent from the start" \
  || no "a rewritten live file is re-sent from the start" "$(segs alpha voice-runtime)"
readlive(){ CLAUDE_DIR="${2:-$CLAUDE_DIR}" python3 - "$1" "${2:-$CLAUDE_DIR}" <<'EOF'
import importlib.util, json, os, sys
p = os.path.join(sys.argv[2], "skills", "builds-sync", "lib", "builds_sync.py")
spec = importlib.util.spec_from_file_location("builds_sync", p)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
assert m.BUILDS_SYNC_API == 1
print(json.dumps(m.read_live(sys.argv[1])))
EOF
}
got=$(readlive voice-runtime)
# Records come back as they were written (b5's keys stay in their order).
want='[{"id": "a1", "text": "one"}, {"id": "a2", "text": "two"}, {"id": "a3", "text": "three"}, {"id": "a4", "text": "four"}, {"text": "five", "id": "b5"}, {"id": "a4", "text": "FOUR"}]'
[ "$got" = "$want" ] && ok "read_live joins both machines in push-time order and keeps exact repeats once" \
  || no "read_live joins both machines in push-time order and keeps exact repeats once" "$got"
[ "$(readlive question-store)" = "[]" ] && ok "read_live of a package with no segments is empty" || no "read_live of a package with no segments is empty" "$(readlive question-store)"
# read_live pulls first: a segment beta pushes now is seen by alpha.
printf '{"id":"b6","text":"six"}\n' >> "$BETA_CLAUDE/skills/voice-runtime/state/drafts.jsonl"
beta push >/dev/null 2>&1
readlive voice-runtime | grep -q '"b6"' && ok "read_live pulls before reading" || no "read_live pulls before reading" "$(readlive voice-runtime)"
mkdir -p "$CLAUDE_DIR/question-store"; printf '{"id":"q1","answer":null}\n' > "$CLAUDE_DIR/question-store/questions.jsonl"
"$BS" push >/dev/null 2>&1
segs alpha question-store | grep -q . && ok "every live file in the list is pushed (question-store)" || no "every live file in the list is pushed (question-store)" "$(remote_files)"

echo "only .age is pushed"
printf '{"id":"a5"}\n' >> "$DRAFTS"
( cd "$TMP/clone-a" && echo secret > notes.txt && git add notes.txt && git -c user.name=t -c user.email=t@t commit -qm oops )
h=$(remote_head)
"$BS" push >"$TMP/out" 2>&1; rc=$?
[ $rc = 3 ] && grep -q "notes.txt" "$TMP/out" && ok "push refuses (exit 3) while a commit holds a file not ending in .age, naming it" \
  || no "push refuses (exit 3) while a commit holds a file not ending in .age, naming it" "rc=$rc $(cat "$TMP/out")"
[ "$(remote_head)" = "$h" ] && ok "nothing reaches the remote" || no "nothing reaches the remote" "remote moved"
"$BS" pending | grep -q voice-runtime && ok "the refused records stay pending" || no "the refused records stay pending" "$("$BS" pending)"
[ -z "$(git -C "$TMP/clone-a" status --porcelain -- live)" ] && ok "the refused segment is withdrawn from the clone" \
  || no "the refused segment is withdrawn from the clone" "$(git -C "$TMP/clone-a" status --porcelain)"
mkbuild "$TMP/b3.tar" plainmarker3
"$BS" publish "$TMP/b3.tar" --build-time $BT3 >"$TMP/out" 2>&1
[ $? = 3 ] && [ "$(remote_head)" = "$h" ] && ok "publish refuses too" || no "publish refuses too" "$(cat "$TMP/out")"
git -C "$TMP/clone-a" reset -q --hard origin/main
( cd "$TMP/clone-a" && echo x > staged.json && git add staged.json )
"$BS" push >"$TMP/out" 2>&1; rc=$?
[ $rc = 3 ] && grep -q "staged.json" "$TMP/out" && ok "push refuses a staged plaintext file as well" \
  || no "push refuses a staged plaintext file as well" "rc=$rc $(cat "$TMP/out")"
git -C "$TMP/clone-a" reset -q -- staged.json; rm -f "$TMP/clone-a/staged.json"
"$BS" push >/dev/null 2>&1 && [ "$("$BS" pending)" = "{}" ] && ok "once the clone is clean, the pending records push" \
  || no "once the clone is clean, the pending records push" "$("$BS" pending)"
( cd "$TMP/clone-a" && echo "changed" > README.md && git -c user.name=t -c user.email=t@t commit -qam readme )
"$BS" push >/dev/null 2>&1 && ok "README.md is allowed" || no "README.md is allowed" "refused"

echo "day-stamp check"
rm -f "$STATE/last-check" "$STATE/check.json"
"$BS" check && [ "$(cat "$STATE/last-check")" = "$(date +%F)" ] && ok "check writes today's stamp" || no "check writes today's stamp" "$(cat "$STATE/last-check" 2>&1)"
jq -e --arg b $BT2 '.newest == $b' "$STATE/check.json" >/dev/null && ok "check records the newest build" || no "check records the newest build" "$(cat "$STATE/check.json")"
"$BS" hook session-start </dev/null | jq -e '.systemMessage | contains("'$BT2'") and contains("builds-sync install")' >/dev/null \
  && ok "SessionStart shows the notice the last check left" || no "SessionStart shows the notice the last check left" "$("$BS" hook session-start </dev/null)"
beta publish "$TMP/b3.tar" --build-time $BT3 >/dev/null 2>&1 || no "beta publishes" "failed"
"$BS" check; jq -e --arg b $BT2 '.newest == $b' "$STATE/check.json" >/dev/null \
  && ok "a second check the same day does nothing" || no "a second check the same day does nothing" "$(cat "$STATE/check.json")"
"$BS" check --force; jq -e --arg b $BT3 '.newest == $b' "$STATE/check.json" >/dev/null \
  && ok "check --force checks at once" || no "check --force checks at once" "$(cat "$STATE/check.json")"
"$BS" install >/dev/null 2>&1
[ -z "$("$BS" hook session-start </dev/null)" ] && ok "no notice once the newest build is installed" \
  || no "no notice once the newest build is installed" "$("$BS" hook session-start </dev/null)"
git -C "$TMP/clone-a" remote set-url origin "$TMP/gone.git"
rm -f "$STATE/last-check"
"$BS" check >/dev/null 2>&1 && no "check against an unreachable remote fails" "exit 0" || ok "check against an unreachable remote fails"
[ "$(cat "$STATE/last-check" 2>/dev/null)" = "$(date +%F)" ] && ok "the stamp is written before the fetch" || no "the stamp is written before the fetch" "no stamp"
"$BS" check >/dev/null 2>&1 && ok "so the same day it is not tried again" || no "so the same day it is not tried again" "tried again"
git -C "$TMP/clone-a" remote set-url origin "$TMP/remote.git"
rm -f "$STATE/last-check"
"$BS" hook session-start </dev/null >/dev/null
for _ in $(seq 50); do [ -f "$STATE/last-check" ] && break; sleep 0.1; done
[ -f "$STATE/last-check" ] && ok "SessionStart starts the day's check in the background" || no "SessionStart starts the day's check in the background" "no stamp"

echo "lock"
python3 - "$STATE/lock" 3 <<'EOF' &
import fcntl, os, sys, time
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(fd, fcntl.LOCK_EX)
open(sys.argv[1] + ".held", "w").close()
time.sleep(float(sys.argv[2]))
EOF
HOLDER=$!
for _ in $(seq 50); do [ -f "$STATE/lock.held" ] && break; sleep 0.1; done
printf '{"id":"a6"}\n' >> "$DRAFTS"
BUILDS_SYNC_LOCK_TIMEOUT=0.5 "$BS" push >"$TMP/out" 2>&1; rc=$?
[ $rc = 75 ] && grep -q "holds" "$TMP/out" && ok "a push while another holds the lock waits, then gives up (exit 75)" \
  || no "a push while another holds the lock waits, then gives up (exit 75)" "rc=$rc $(cat "$TMP/out")"
"$BS" push >"$TMP/out" 2>&1 && grep -q "pushed live/alpha/voice-runtime" "$TMP/out" \
  && ok "a push waits for the lock and then goes through" || no "a push waits for the lock and then goes through" "$(cat "$TMP/out")"
wait "$HOLDER" 2>/dev/null; HOLDER=""; rm -f "$STATE/lock.held"
n0=$(segs alpha voice-runtime | wc -l)
printf '{"id":"a7"}\n' >> "$DRAFTS"
"$BS" push >"$TMP/p1" 2>&1 & p1=$!
"$BS" push >"$TMP/p2" 2>&1 & p2=$!
wait $p1; r1=$?; wait $p2; r2=$?
[ $r1 = 0 ] && [ $r2 = 0 ] && [ "$(segs alpha voice-runtime | wc -l)" = $((n0+1)) ] \
  && ok "two sessions ending together push the new records once" \
  || no "two sessions ending together push the new records once" "r1=$r1 r2=$r2 $(segs alpha voice-runtime | wc -l) vs $n0"
printf '{"id":"a8"}\n' >> "$DRAFTS"
t0=$(date +%s%3N); "$BS" hook session-end </dev/null; t1=$(date +%s%3N)
[ $(( t1-t0 )) -lt 1500 ] && ok "the SessionEnd hook returns at once" || no "the SessionEnd hook returns at once" "$(( t1-t0 )) ms"
for _ in $(seq 100); do [ "$("$BS" pending 2>/dev/null)" = "{}" ] && break; sleep 0.1; done
[ "$("$BS" pending)" = "{}" ] && [ "$(segs alpha voice-runtime | wc -l)" = $((n0+2)) ] \
  && ok "and the push it started lands" || no "and the push it started lands" "$("$BS" pending) $(cat "$STATE/last-push.log" 2>&1)"

echo "offline"
printf '{"id":"a9"}\n' >> "$DRAFTS"
git -C "$TMP/clone-a" remote set-url origin "$TMP/gone.git"
"$BS" push >"$TMP/out" 2>&1; rc=$?
[ $rc != 0 ] && grep -q "offline" "$TMP/out" && ok "an offline push fails and says so" || no "an offline push fails and says so" "rc=$rc $(cat "$TMP/out")"
p=$("$BS" pending); echo "$p" | jq -e '._commits == 1 and (has("voice-runtime") | not)' >/dev/null \
  && ok "it commits locally and the records are no longer pending" || no "it commits locally and the records are no longer pending" "$p"
git -C "$TMP/clone-a" remote set-url origin "$TMP/remote.git"
"$BS" push >/dev/null 2>&1 && [ "$("$BS" pending)" = "{}" ] && readlive voice-runtime | grep -q '"a9"' \
  && ok "the next push carries what the offline one committed" || no "the next push carries what the offline one committed" "$("$BS" pending)"

echo "uninstall"
printf '{"id":"a10"}\n' >> "$DRAFTS"
( . "$REPO/manifest.sh"; KEEP_STATE=0 KEEP_SETTINGS=1 pre_uninstall ) >"$TMP/out" 2>&1 \
  && no "pre_uninstall refuses while records are unpushed" "allowed" \
  || { grep -q "builds-sync push" "$TMP/out" && ok "pre_uninstall refuses while records are unpushed" || no "pre_uninstall refuses while records are unpushed" "$(cat "$TMP/out")"; }
( . "$REPO/manifest.sh"; KEEP_STATE=1 KEEP_SETTINGS=1 pre_uninstall ) >/dev/null 2>&1 \
  && ok "but not with --keep-state" || no "but not with --keep-state" "refused"
"$BS" push >/dev/null 2>&1
( . "$REPO/manifest.sh"; KEEP_STATE=0 KEEP_SETTINGS=1 pre_uninstall ) >/dev/null 2>&1 \
  && ok "nor once everything is pushed" || no "nor once everything is pushed" "refused"
for t in $(remote_files); do case "$t" in README.md|*.age) ;; *) echo "$t";; esac; done | grep -q . \
  && no "the remote holds nothing but README.md and .age files" "$(remote_files)" || ok "the remote holds nothing but README.md and .age files"

echo "python 3.8"
python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 8) else 1)' \
  && python3 -c 'import sys; compile(open(sys.argv[1]).read(), sys.argv[1], "exec")' "$REPO/skill/lib/builds_sync.py" && ok "the library compiles on $(python3 -V)" || no "the library compiles" "py_compile failed"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = 0 ]
