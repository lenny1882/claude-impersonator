#!/usr/bin/env bash
# Tests for voice-runtime.
#
# Redirects HOME and CLAUDE_DIR into a temp directory, so the real config is
# never touched, and uses made-up builds only (test/fixtures.py).
#
#   ./test/run-tests.sh
#   VR_SKIP_REAL=1 ./test/run-tests.sh     leave out the real-model group
#
# Three groups:
#   installer   the kit's installer tests (installer-tests.sh), plus this
#               package's sandbox exclusion and pre_uninstall refusal
#   behaviour   every subcommand against a stand-in embedding_lib
#               (fixtures.py fake-el: a hash-based embed and an identity()),
#               reached through EMBEDDING_LIB_HOME, so no model is needed.
#               Its Python is embedding-lib's venv (for numpy) or
#               VR_TEST_PY; without either it fails.
#   real        install and search with the real embedding-lib, when its
#               venv and model are on this machine. Skipped with
#               VR_SKIP_REAL=1; fails when they're missing otherwise.
#
# Logs to /tmp/voice-runtime-tests.log.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${VR_TEST_LOG:-/tmp/voice-runtime-tests.log}"
exec > >(tee "$LOG") 2>&1
echo "== voice-runtime tests, $(date -Is)"

REAL_HOME="$HOME"
EL_REAL="${EMBEDDING_LIB_HOME:-$REAL_HOME/.local/share/embedding-lib}"
PY="${VR_TEST_PY:-}"
[ -n "$PY" ] || { [ -x "$EL_REAL/venv/bin/python" ] && PY="$EL_REAL/venv/bin/python"; }
unset VOICE_RUNTIME_STATE EMBEDDING_LIB_HOME FAKE_EL_PYTHON FAKE_EL_FAIL FAKE_EL_MAX_TOKENS FAKE_EMBED_LOG FAKE_EL_API

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/home"; mkdir -p "$HOME"
export CLAUDE_DIR="$TMP/claude"; mkdir -p "$CLAUDE_DIR"
export KIT_SKIP_MACHINE_HOOKS=1   # pre_install and post_install change the real machine, not $HOME

pass=0; fail=0
ok(){ printf '  ok    %s\n' "$1"; pass=$((pass+1)); }
no(){ printf '  FAIL  %s\n    %s\n' "$1" "$2"; fail=$((fail+1)); }
check(){ # check <name> <command...>: passes when the command succeeds
  local name="$1"; shift
  if out=$("$@" 2>&1); then ok "$name"; else no "$name" "$(printf '%s' "$out" | tail -3)"; fi
}
q(){ jq -e "$@" >/dev/null 2>&1; }

. "$REPO/test/installer-tests.sh"

echo "installer, this package"
check "install registers the sandbox exclusion" \
  jq -e '.sandbox.excludedCommands | index("voice-runtime *")' "$CLAUDE_DIR/settings.json"

# pre_uninstall for real (KIT_SKIP_MACHINE_HOOKS=0): it touches only CLAUDE_DIR.
U="$TMP/uninst"; mkdir -p "$U/home" "$U/claude"
(
  export HOME="$U/home" CLAUDE_DIR="$U/claude"
  echo '{}' > "$CLAUDE_DIR/settings.json"
  "$REPO/install.sh" --yes >"$U/install.out" 2>&1 || { echo "install failed: $(tail -3 "$U/install.out")"; exit 1; }
  st="$CLAUDE_DIR/skills/voice-runtime/state"; mkdir -p "$st"
  echo '{"id":"x"}' > "$st/drafts.jsonl"
  if KIT_SKIP_MACHINE_HOOKS=0 "$REPO/uninstall.sh" --yes >"$U/u1.out" 2>&1; then
    echo "uninstall went ahead with drafts.jsonl present"; exit 1; fi
  grep -q 'drafts.jsonl' "$U/u1.out" || { echo "refusal doesn't name drafts.jsonl: $(cat "$U/u1.out")"; exit 1; }
  [ -x "$HOME/.local/bin/voice-runtime" ] && [ -f "$st/drafts.jsonl" ] || { echo "files removed after refusal"; exit 1; }
  KIT_SKIP_MACHINE_HOOKS=0 "$REPO/uninstall.sh" --yes --keep-state >"$U/u2.out" 2>&1 \
    || { echo "--keep-state uninstall failed: $(tail -3 "$U/u2.out")"; exit 1; }
  [ -f "$st/drafts.jsonl" ] || { echo "--keep-state lost drafts.jsonl"; exit 1; }
  [ ! -e "$HOME/.local/bin/voice-runtime" ] || { echo "--keep-state left the executable"; exit 1; }
  jq -e '(.sandbox.excludedCommands // []) | index("voice-runtime *") | not' "$CLAUDE_DIR/settings.json" >/dev/null \
    || { echo "exclusion left in settings.json"; exit 1; }
) >"$U/result" 2>&1 && ok "pre_uninstall refuses while drafts.jsonl exists; --keep-state uninstalls and keeps it" \
  || no "pre_uninstall refuses while drafts.jsonl exists; --keep-state uninstalls and keeps it" "$(cat "$U/result")"

# --- behaviour --------------------------------------------------------------

echo "behaviour (python: ${PY:-none})"
if [ -z "$PY" ] || ! "$PY" -c 'import numpy' 2>/dev/null; then
  no "a Python with numpy for the behaviour tests" "set VR_TEST_PY, or set up embedding-lib"
  printf '\n%d passed, %d failed\n' "$pass" "$fail"; exit 1
fi

export CLAUDE_DIR="$TMP/claude-b"; mkdir -p "$CLAUDE_DIR"
export VOICE_RUNTIME_HOME="$TMP/no-install"   # the checkout's pylib, not an installed copy
ST="$CLAUDE_DIR/skills/voice-runtime/state"
EL="$TMP/el"; mkdir -p "$EL/venv/bin"
"$PY" "$REPO/test/fixtures.py" fake-el "$EL"
printf '#!/bin/sh\nexec "%s" "$@"\n' "$PY" > "$EL/venv/bin/python"; chmod +x "$EL/venv/bin/python"
export EMBEDDING_LIB_HOME="$EL" FAKE_EMBED_LOG="$TMP/embedded.jsonl"
VR="$REPO/bin/voice-runtime"
B="$TMP/builds"
fx(){ "$PY" "$REPO/test/fixtures.py" build "$@"; }
BT1=20261101T090000Z; BT2=20261108T090000Z
fx "$B/a" "$BT1"; fx "$B/b" "$BT2" --variant b

# expect_refusal <name> <needle> <command...>: exit 3, one line, naming needle
expect_refusal(){
  local name="$1" needle="$2"; shift 2
  local out rc
  out=$("$@" 2>&1); rc=$?
  if [ "$rc" = 3 ] && [ "$(printf '%s\n' "$out" | wc -l)" = 1 ] && printf '%s' "$out" | grep -q -- "$needle"; then
    ok "$name"
  else no "$name" "exit $rc: $out"; fi
}

echo " before any build"
expect_refusal "guide refuses with no build" "no voice build is installed" \
  "$VR" guide --audience technical-team --purposes status
expect_refusal "search refuses with no build" "no voice build is installed" \
  "$VR" search --audience technical-team --purposes status --situation "deploy"
check "status says unusable, and why" \
  sh -c "'$VR' status | jq -e '.usable == false and (.refusal | test(\"no voice build\"))'"
[ ! -e "$ST" ] && ok "status creates no state" || no "status creates no state" "$(ls -la "$ST")"

echo " install-build"
: > "$FAKE_EMBED_LOG"
out=$("$VR" install-build "$B/a" --build-time "$BT1" 2>&1)
[ $? = 0 ] && printf '%s' "$out" | grep -q "7 exemplars, 7 embedded, 0 reused" \
  && ok "first install embeds every exemplar" || no "first install embeds every exemplar" "$out"
missing=""
for f in guide.json exemplars.json stats.json build.json index/vectors.npy index/ids.json index/identity.json index/hashes.json; do
  [ -f "$ST/builds/$BT1/$f" ] || missing="$missing $f"
done
[ -z "$missing" ] && ok "build files and index written" || no "build files and index written" "missing:$missing"
check "manifest names the build and each file's schema" \
  jq -e --arg bt "$BT1" '.schema_version == 1 and .build_time == $bt and .files == {"guide.json":1,"exemplars.json":1,"stats.json":1}' "$ST/manifest.json"
newest=$(find "$ST/builds/$BT1" -type f -printf '%T@\n' | sort -n | tail -1)
awk -v m="$(find "$ST/manifest.json" -printf '%T@')" -v n="$newest" 'BEGIN{exit !(m >= n)}' \
  && ok "manifest.json written after every build file" || no "manifest.json written after every build file" "manifest $(find "$ST/manifest.json" -printf '%T@'), newest build file $newest"
check "ids.json follows exemplars.json order" \
  sh -c "[ \"\$(jq -c '[.exemplars[].id]' '$ST/builds/$BT1/exemplars.json')\" = \"\$(jq -c . '$ST/builds/$BT1/index/ids.json')\" ]"
check "embedded text is answered, blank line, text" \
  grep -qxF '"how is the staging deploy looking\n\nthe deploy pipeline is green again, migration ran fine on staging"' "$FAKE_EMBED_LOG"
check "an empty answered embeds the text alone" \
  grep -qxF '"tests pass locally now, could someone review the branch before lunch"' "$FAKE_EMBED_LOG"
loose=$(find "$ST" \( -type d -perm /077 \) -o \( -type f -perm /177 \) | head -3)
[ -z "$loose" ] && ok "state is owner-only (dirs 700, files 600)" || no "state is owner-only (dirs 700, files 600)" "$loose"
[ -z "$(find "$ST/builds" -maxdepth 1 -name '.*' ! -name . )" ] && ok "no staging left behind" || no "no staging left behind" "$(ls -a "$ST/builds")"

echo " a failed install leaves the current build in use"
fx "$B/c" 20261109T090000Z --variant b
"$PY" - "$B/c/exemplars.json" <<'EOF'
import json, sys
p = sys.argv[1]; d = json.load(open(p))
d["exemplars"][0]["hash"] = "f" * 64   # forces at least one embed
json.dump(d, open(p, "w"))
EOF
FAKE_EL_FAIL=1 "$VR" install-build "$B/c" --build-time 20261109T090000Z >/dev/null 2>&1
rc=$?
[ "$rc" != 0 ] && q --arg bt "$BT1" '.build_time == $bt' "$ST/manifest.json" \
  && [ ! -e "$ST/builds/20261109T090000Z" ] && [ -d "$ST/builds/$BT1" ] \
  && ok "manifest and current build untouched when embedding fails" \
  || no "manifest and current build untouched when embedding fails" "exit $rc; $(cat "$ST/manifest.json"); $(ls -a "$ST/builds")"
[ -z "$(find "$ST/builds" -maxdepth 1 -name '.*' ! -name . )" ] && ok "failed install cleans its staging" || no "failed install cleans its staging" "$(ls -a "$ST/builds")"

echo " reuse by hash"
: > "$FAKE_EMBED_LOG"
out=$("$VR" install-build "$B/b" --build-time "$BT2" 2>&1)
printf '%s' "$out" | grep -q "8 exemplars, 2 embedded, 6 reused" \
  && ok "second build embeds only the changed and new pairs" || no "second build embeds only the changed and new pairs" "$out"
[ "$(wc -l < "$FAKE_EMBED_LOG")" = 2 ] && grep -q 'retry logic in the queue worker today' "$FAKE_EMBED_LOG" \
  && grep -q 'flaky test' "$FAKE_EMBED_LOG" \
  && ok "the two embedded are the changed and the new one" || no "the two embedded are the changed and the new one" "$(cat "$FAKE_EMBED_LOG")"
[ ! -e "$ST/builds/$BT1" ] && [ -d "$ST/builds/$BT2" ] && ok "previous build deleted" || no "previous build deleted" "$(ls -a "$ST/builds")"
check "manifest now names the second build" jq -e --arg bt "$BT2" '.build_time == $bt' "$ST/manifest.json"
check "reused rows equal a fresh embed of the same text" "$PY" - "$ST/builds/$BT2" <<'EOF'
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.environ["EMBEDDING_LIB_HOME"], "pylib"))
import embedding_lib as el
d = sys.argv[1]
ex = json.load(open(os.path.join(d, "exemplars.json")))["exemplars"]
v = np.load(os.path.join(d, "index", "vectors.npy"))
for e, row in zip(ex, v):
    t = e["answered"] + "\n\n" + e["text"] if e["answered"] else e["text"]
    assert np.allclose(el.embed([t])[0], row), e["id"]
EOF

echo " search"
s(){ "$VR" search "$@"; }
out=$(s --audience technical-team --purposes status --situation "staging deploy migration")
q '.k == 3 and (.exemplars | length) == 3' <<<"$out" && ok "k defaults to build.json's exemplar_count" || no "k defaults to build.json's exemplar_count" "$out"
q '.exemplars[0].id == "ex-001"' <<<"$out" && ok "closest first" || no "closest first" "$(jq -c '[.exemplars[].id]' <<<"$out")"
q '[.exemplars[].id] | index("ex-005") | not' <<<"$out" && ok "only the asked audience" || no "only the asked audience" "$out"
q '[.exemplars[:2][] | .matched] == ["purpose","purpose"] and .exemplars[2].matched == "audience"' <<<"$out" \
  && ok "purpose matches first, then filled from the same audience" || no "purpose matches first, then filled from the same audience" "$(jq -c '[.exemplars[] | [.id,.matched]]' <<<"$out")"
q '[.exemplars[:2][] | .purposes | index("status")] | all' <<<"$out" && ok "purpose matches carry the purpose" || no "purpose matches carry the purpose" "$out"
out=$(s --audience technical-team --purposes push-back,thank --situation "cache" --k 5)
q '(.exemplars | length) == 5 and ([.exemplars[] | select(.matched == "purpose")] | length) == 2' <<<"$out" \
  && ok "any of several purposes; --k overrides" || no "any of several purposes; --k overrides" "$(jq -c '[.exemplars[] | [.id,.matched]]' <<<"$out")"
out=$(s --audience technical-team --purposes ask --situation "x" --k 1)
q '(.exemplars | length) == 1 and .exemplars[0].matched == "purpose"' <<<"$out" && ok "--k 1 gives one" || no "--k 1 gives one" "$out"
out=$(s --audience clients --purposes decline --situation "export this sprint" --k 10)
q '(.exemplars | length) == 2 and ([.exemplars[].id] | sort) == ["ex-005","ex-006"]' <<<"$out" \
  && ok "fewer than k when the audience has fewer" || no "fewer than k when the audience has fewer" "$out"
out=$(s --audience jira --purposes status --situation "x")
q '.exemplars == []' <<<"$out" && ok "jira has no exemplars" || no "jira has no exemplars" "$out"
out=$(s --audience nobody --purposes status --situation x 2>&1); rc=$?
[ "$rc" = 1 ] && printf '%s' "$out" | grep -q "unknown audience" && ok "unknown audience is a usage error (exit 1)" || no "unknown audience is a usage error (exit 1)" "exit $rc: $out"
out=$(s --audience technical-team --purposes gossip --situation x 2>&1); rc=$?
[ "$rc" = 1 ] && printf '%s' "$out" | grep -q "unknown purpose" && ok "unknown purpose is a usage error (exit 1)" || no "unknown purpose is a usage error (exit 1)" "exit $rc: $out"

echo " guide"
out=$("$VR" guide --audience technical-team --purposes status,ask)
first=$(printf '%s\n' "$out" | grep -n -m1 'RULE' | cut -d: -f2-)
printf '%s' "$first" | grep -q OWN-RULE && ok "the owner's own rules come first" || no "the owner's own rules come first" "$first"
missing=""
for r in GENERAL-RULE TECH-RULE TECH-STATUS-RULE TECH-ASK-RULE COMBINE-RULE "median 14 words" "never or almost never writes" "hope this helps" "How to draft" "DRAFT-SYSTEM"; do
  printf '%s' "$out" | grep -q "$r" || missing="$missing [$r]"
done
[ -z "$missing" ] && ok "guide holds general, audience, purpose, combination rules and the stats" || no "guide holds general, audience, purpose, combination rules and the stats" "missing:$missing"
printf '%s' "$out" | grep -q 'CLIENT-RULE\|JIRA-RULE' && no "guide leaves out other audiences" "$out" || ok "guide leaves out other audiences"
out=$("$VR" guide --audience technical-team --purposes status)
printf '%s' "$out" | grep -q 'COMBINE-RULE\|TECH-ASK-RULE' && no "one purpose: no combinations, no other purpose's rules" "$out" || ok "one purpose: no combinations, no other purpose's rules"
out=$("$VR" guide --audience jira --purposes status)
printf '%s' "$out" | grep -q JIRA-RULE && ! printf '%s' "$out" | grep -q TECH-RULE && ok "jira gets the Jira section" || no "jira gets the Jira section" "$out"
out=$("$VR" guide --audience technical-team --purposes status)
printf '%s' "$out" | grep -qE "messages to technical-team holding each: spaced dash [0-9]+[^0-9 ], exclamation mark [0-9]+[^0-9 ]" && ok "guide gives the audience's share of messages holding each mark of style" || no "guide gives the audience's share of messages holding each mark of style" "$out"
printf '%s' "$out" | grep -q 'CLIENT-NOTE\|How to write it\|Words the rules quote' && no "an audience without drafting notes gets none, nor quoted-word shares" "$out" || ok "an audience without drafting notes gets none, nor quoted-word shares"
out=$("$VR" guide --audience clients --purposes decline)
o1=$(printf '%s\n' "$out" | grep -n -m1 'OWN-RULE' | cut -d: -f1); o2=$(printf '%s\n' "$out" | grep -n -m1 'OWN-AUD-ONLY' | cut -d: -f1)
[ -n "$o1" ] && [ -n "$o2" ] && [ "$o2" = $((o1 + 1)) ] && ok "an audience's own rules follow the owner's rules for all" || no "an audience's own rules follow the owner's rules for all" "$out"
out=$("$VR" guide --audience technical-team --purposes status)
printf '%s' "$out" | grep -q OWN-AUD-ONLY && no "another audience's own rules are left out" "$out" || ok "another audience's own rules are left out"
out=$("$VR" guide --audience clients --purposes decline)
note=$(printf '%s\n' "$out" | grep -n -m1 'CLIENT-NOTE' | cut -d: -f1); rule=$(printf '%s\n' "$out" | grep -n -m1 'CLIENT-RULE' | cut -d: -f1)
[ -n "$note" ] && [ -n "$rule" ] && [ "$note" -lt "$rule" ] && printf '%s' "$out" | grep -qE '"kindly" [0-9.]+[^0-9. ]' && ok "clients get their drafting notes before the rules, and the quoted words' shares" || no "clients get their drafting notes before the rules, and the quoted words' shares" "$out"
out=$("$VR" guide --audience technical-team --purposes status)
ds=$(printf '%s\n' "$out" | grep -n -m1 'DRAFT-SYSTEM' | cut -d: -f1); own=$(printf '%s\n' "$out" | grep -n -m1 'OWN-RULE' | cut -d: -f1)
[ -n "$ds" ] && [ -n "$own" ] && [ "$ds" -lt "$own" ] && printf '%s' "$out" | grep -q '^## How to draft' && ok "guide gives the build's drafter prompt first, under How to draft" || no "guide gives the build's drafter prompt first, under How to draft" "$out"
cur=$(jq -r .build_time "$ST/manifest.json"); cp "$ST/builds/$cur/stats.json" "$TMP/stats.purposes"
jq '.drafting.purposes = ["status", "gossip"]' "$TMP/stats.purposes" > "$ST/builds/$cur/stats.json"
g=$("$VR" guide --audience technical-team --purposes gossip 2>&1); grc=$?
d=$("$VR" guide --audience technical-team --purposes decline 2>&1); drc=$?
cp "$TMP/stats.purposes" "$ST/builds/$cur/stats.json"
[ "$grc" = 0 ] && [ "$drc" = 1 ] && printf '%s' "$d" | grep -q 'purposes are: status, gossip' && ok "a build's own purpose list is the one guide accepts" || no "a build's own purpose list is the one guide accepts" "exit $grc/$drc: $d"
out=$("$VR" audiences)
printf '%s\n' "$out" | grep -q '^clients: a client channel' && printf '%s\n' "$out" | grep -q '^jira: a Jira comment' && ok "audiences lists the build's audiences and where a draft goes for each" || no "audiences lists the build's audiences and where a draft goes for each" "$out"
cp "$ST/builds/$cur/stats.json" "$TMP/stats.render"
jq 'del(.drafting.render)' "$TMP/stats.render" > "$ST/builds/$cur/stats.json"
out=$("$VR" guide --audience technical-team --purposes status 2>&1); rc=$?
cp "$TMP/stats.render" "$ST/builds/$cur/stats.json"
[ "$rc" = 3 ] && printf '%s' "$out" | grep -q 'carries no drafting wording' && ok "a build without the drafting wording is refused" || no "a build without the drafting wording is refused" "exit $rc: $out"
cp "$ST/builds/$cur/stats.json" "$TMP/stats.aud"
jq '.drafting.audiences = [{"slug": "clients", "corpus": true, "routing": []}, {"slug": "partners", "corpus": true, "routing": ["a partner channel"]}]' "$TMP/stats.aud" > "$ST/builds/$cur/stats.json"
p=$("$VR" guide --audience partners --purposes status 2>&1); prc=$?
t=$("$VR" guide --audience technical-team --purposes status 2>&1); trc=$?
cp "$TMP/stats.aud" "$ST/builds/$cur/stats.json"
[ "$prc" = 0 ] && [ "$trc" = 1 ] && printf '%s' "$t" | grep -q 'audiences are: clients, partners' && ok "a build's own audience list is the one guide accepts" || no "a build's own audience list is the one guide accepts" "exit $prc/$trc: $t"
out=$(EMBEDDING_LIB_HOME="$TMP/no-el" "$VR" guide --audience clients --purposes decline 2>&1)
printf '%s' "$out" | grep -q CLIENT-DECLINE-RULE && ok "guide runs on the system python3 without embedding-lib" || no "guide runs on the system python3 without embedding-lib" "$out"

echo " refusals"
expect_refusal "search without embedding-lib refuses" "embedding-lib is not installed" \
  env EMBEDDING_LIB_HOME="$TMP/no-el" "$VR" search --audience technical-team --purposes status --situation x
expect_refusal "search refuses an embedding-lib API it wasn't written for" "API is 2" \
  env FAKE_EL_API=2 "$VR" search --audience technical-team --purposes status --situation x
expect_refusal "search refuses an index from another embedding setup" 'python: index "3.14.10", here "3.14.99"' \
  env FAKE_EL_PYTHON=3.14.99 "$VR" search --audience technical-team --purposes status --situation x
check "status reports the identity mismatch" \
  sh -c "FAKE_EL_PYTHON=3.14.99 '$VR' status | jq -e '.usable == false and (.refusal | test(\"another embedding-lib setup\"))'"
fx "$B/bad-guide" 20261110T090000Z --schema guide.json=2
expect_refusal "install-build refuses an unknown schema, naming file, found and accepted" \
  "guide.json has schema version 2; this voice-runtime accepts 1" \
  "$VR" install-build "$B/bad-guide" --build-time 20261110T090000Z
fx "$B/bad-listed" 20261110T090000Z --listed stats.json=3
expect_refusal "install-build refuses a build.json listing an unknown schema" \
  "build.json lists stats.json at schema version 3; this voice-runtime accepts 1" \
  "$VR" install-build "$B/bad-listed" --build-time 20261110T090000Z
fx "$B/bad-build" 20261110T090000Z --schema build.json=9
expect_refusal "install-build refuses an unknown build.json schema" \
  "build.json has schema version 9; this voice-runtime accepts 1" \
  "$VR" install-build "$B/bad-build" --build-time 20261110T090000Z
q --arg bt "$BT2" '.build_time == $bt' "$ST/manifest.json" && [ ! -e "$ST/builds/20261110T090000Z" ] \
  && ok "refused installs change nothing" || no "refused installs change nothing" "$(ls -a "$ST/builds")"
out=$("$VR" install-build "$B/a" --build-time 20261231T000000Z 2>&1); rc=$?
[ "$rc" = 1 ] && printf '%s' "$out" | grep -q "but --build-time is" && ok "build_time must match --build-time" || no "build_time must match --build-time" "exit $rc: $out"
cp "$ST/builds/$BT2/stats.json" "$TMP/stats.keep"
jq '.schema_version = 2' "$TMP/stats.keep" > "$ST/builds/$BT2/stats.json"
expect_refusal "guide refuses an installed file of an unknown schema" "stats.json has schema version 2; this voice-runtime accepts 1" \
  "$VR" guide --audience technical-team --purposes status
check "search doesn't read stats.json, so doesn't refuse over it" \
  sh -c "'$VR' search --audience technical-team --purposes status --situation x | jq -e '.exemplars | length == 3'"
cp "$TMP/stats.keep" "$ST/builds/$BT2/stats.json"
cp "$ST/manifest.json" "$TMP/manifest.keep"
jq '.schema_version = 4' "$TMP/manifest.keep" > "$ST/manifest.json"
expect_refusal "an unknown manifest schema refuses" "manifest.json has schema version 4; this voice-runtime accepts 1" \
  "$VR" guide --audience technical-team --purposes status
jq '.files["guide.json"] = 5' "$TMP/manifest.keep" > "$ST/manifest.json"
expect_refusal "a manifest listing an unknown file schema refuses" "manifest.json lists guide.json at schema version 5" \
  "$VR" guide --audience technical-team --purposes status
cp "$TMP/manifest.keep" "$ST/manifest.json"; chmod 600 "$ST/manifest.json"

echo " identity change"
: > "$FAKE_EMBED_LOG"
out=$(FAKE_EL_PYTHON=3.14.99 "$VR" install-build "$B/b" --build-time "$BT2" 2>&1)
printf '%s' "$out" | grep -q "8 exemplars, 8 embedded, 0 reused (embedding-lib identity changed)" \
  && ok "a changed identity re-embeds every exemplar, even of the same build" || no "a changed identity re-embeds every exemplar, even of the same build" "$out"
check "search works again under the new identity" \
  sh -c "FAKE_EL_PYTHON=3.14.99 '$VR' search --audience technical-team --purposes status --situation x | jq -e '.exemplars | length == 3'"
expect_refusal "and refuses under the old one" "another embedding-lib setup" \
  "$VR" search --audience technical-team --purposes status --situation x
[ -d "$ST/builds/$BT2" ] && [ "$(ls -A "$ST/builds")" = "$BT2" ] && ok "reinstalling the current build leaves one copy" || no "reinstalling the current build leaves one copy" "$(ls -a "$ST/builds")"
export FAKE_EL_PYTHON=3.14.99

echo " the 512-token limit"
fx "$B/long" 20261111T090000Z
"$PY" - "$B/long/exemplars.json" <<'EOF'
import hashlib, json, sys
p = sys.argv[1]; d = json.load(open(p))
e = d["exemplars"][0]
e["answered"] = " ".join("w%d" % i for i in range(30))
e["hash"] = hashlib.sha256((e["answered"] + "\n\n" + e["text"]).encode()).hexdigest()
json.dump(d, open(p, "w"))
EOF
: > "$FAKE_EMBED_LOG"
FAKE_EL_MAX_TOKENS=25 "$VR" install-build "$B/long" --build-time 20261111T090000Z >/dev/null 2>&1
line=$(grep 'w29' "$FAKE_EMBED_LOG" | head -1)
"$PY" -c '
import json, sys
t = json.loads(sys.argv[1]); a, b = t.split("\n\n")
ws = a.split()
assert ws[-1] == "w29" and ws[0] != "w0", ws[:3]
assert len(t.split()) + 2 <= 25, len(t.split())
assert len(t.split()) + 3 > 25    # no more was dropped than needed
assert b.startswith("the deploy pipeline")
' "$line" 2>/dev/null && ok "a long pair loses words from the start of answered, only as many as needed" \
  || no "a long pair loses words from the start of answered, only as many as needed" "$line"
"$VR" install-build "$B/b" --build-time "$BT2" >/dev/null 2>&1

echo " drafts"
printf 'can you have a look at the branch today\n' > "$TMP/draft.txt"
id=$("$VR" save-draft --audience technical-team --purposes ask,status --destination 'bitbucket:web-app#42' --text-file "$TMP/draft.txt")
D="$ST/drafts.jsonl"
check "save-draft writes the contract's line" jq -e --arg id "$id" --arg bt "$BT2" --arg host "$(hostname)" '
  (keys == (["audience","build_time","destination","host","id","kind","purposes","schema_version","status","text","ts"]))
  and .id == $id and .kind == "draft" and .status == "drafted" and .audience == "technical-team"
  and .purposes == ["ask","status"] and .destination == "bitbucket:web-app#42"
  and .text == "can you have a look at the branch today" and .build_time == $bt
  and .host == $host and .schema_version == 1
  and (.ts | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"))' "$D"
[[ "$id" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$ ]] && ok "draft id is a uuid4" || no "draft id is a uuid4" "$id"
[ "$(stat -c %a "$D")" = 600 ] && ok "drafts.jsonl is mode 600" || no "drafts.jsonl is mode 600" "$(stat -c %a "$D")"
printf 'can you have a look at the branch today please\n' > "$TMP/final.txt"
check "save-final prints id and status" sh -c "[ \"\$('$VR' save-final --id '$id' --text-file '$TMP/final.txt')\" = '$id approved' ]"
check "save-final appends a final line carrying the draft's fields" jq -se --arg id "$id" --arg bt "$BT2" '
  length == 2 and .[1].id == $id and .[1].kind == "final" and .[1].status == "approved"
  and .[1].text == "can you have a look at the branch today please"
  and .[1].audience == "technical-team" and .[1].purposes == ["ask","status"]
  and .[1].destination == "bitbucket:web-app#42" and .[1].build_time == $bt
  and .[0].text == "can you have a look at the branch today"' "$D"
id2=$("$VR" save-draft --audience clients --purposes decline --destination 'slack:client-03' --text-file "$TMP/draft.txt")
"$VR" save-final --id "$id2" --text-file "$TMP/draft.txt" --status discarded >/dev/null
check "a discarded final" jq -se --arg id "$id2" 'last | .id == $id and .kind == "final" and .status == "discarded" and .destination == "slack:client-03"' "$D"
out=$("$VR" save-final --id "$(python3 -c "import uuid; print(uuid.uuid4())")" --text-file "$TMP/draft.txt" 2>&1); rc=$?
[ "$rc" = 1 ] && printf '%s' "$out" | grep -q "no draft with id" && ok "save-final refuses an unknown id" || no "save-final refuses an unknown id" "exit $rc: $out"
out=$("$VR" save-draft --audience clients --purposes decline --destination 'email:someone' --text-file "$TMP/draft.txt" 2>&1); rc=$?
[ "$rc" = 1 ] && ok "save-draft refuses an unknown destination" || no "save-draft refuses an unknown destination" "exit $rc: $out"
: > "$TMP/empty.txt"
out=$("$VR" save-draft --audience clients --purposes decline --destination other --text-file "$TMP/empty.txt" 2>&1); rc=$?
[ "$rc" = 1 ] && ok "save-draft refuses an empty text" || no "save-draft refuses an empty text" "exit $rc: $out"
check "jira and other destinations accepted" sh -c "'$VR' save-draft --audience jira --purposes status --destination jira:ABC-12 --text-file '$TMP/draft.txt' >/dev/null && '$VR' save-draft --audience senior --purposes status --destination other --text-file '$TMP/draft.txt' >/dev/null"
[ "$(jq -s 'length' "$D")" = 6 ] && ok "every save is one appended line" || no "every save is one appended line" "$(wc -l < "$D")"
out=$(EMBEDDING_LIB_HOME="$TMP/no-el" "$VR" save-draft --audience senior --purposes thank --destination other --text-file "$TMP/draft.txt" 2>&1)
[ $? = 0 ] && ok "save-draft runs on the system python3 without embedding-lib" || no "save-draft runs on the system python3 without embedding-lib" "$out"
check "status counts drafts and says usable" sh -c "'$VR' status | jq -e --arg bt '$BT2' '.usable and .build_time == \$bt and .drafts == 5 and .exemplars == 8'"
loose=$(find "$ST" \( -type d -perm /077 \) -o \( -type f -perm /177 \) | head -3)
[ -z "$loose" ] && ok "state still owner-only after every command" || no "state still owner-only after every command" "$loose"

# --- real -------------------------------------------------------------------

echo "real (embedding-lib at $EL_REAL)"
unset FAKE_EL_PYTHON FAKE_EMBED_LOG
if [ "${VR_SKIP_REAL:-0}" = 1 ]; then
  echo "  skip  real (VR_SKIP_REAL=1)"
elif [ ! -x "$EL_REAL/venv/bin/python" ] || ! ls "$EL_REAL"/hf/hub/models--BAAI--bge-base-en-v1.5/snapshots/*/model.safetensors >/dev/null 2>&1; then
  no "real-environment tests" "embedding-lib isn't set up at $EL_REAL (or set VR_SKIP_REAL=1)"
else
  export EMBEDDING_LIB_HOME="$EL_REAL" VOICE_RUNTIME_STATE="$TMP/real-state"
  out=$("$VR" install-build "$B/a" --build-time "$BT1" 2>&1)
  printf '%s' "$out" | grep -q "7 exemplars, 7 embedded" && ok "installs with the real model" || no "installs with the real model" "$out"
  check "index identity is embedding-lib's own" sh -c "jq -e '.model == \"BAAI/bge-base-en-v1.5\" and .dimension == 768' '$TMP/real-state/builds/$BT1/index/identity.json'"
  out=$("$VR" search --audience technical-team --purposes push-back,ask --situation "should we add caching in front of the slow reports query" --k 2)
  q '.exemplars[0].id == "ex-003"' <<<"$out" && ok "real search puts the cache message first" || no "real search puts the cache message first" "$(jq -c '[.exemplars[] | [.id,.score]]' <<<"$out")"
  out=$("$VR" install-build "$B/b" --build-time "$BT2" 2>&1)
  printf '%s' "$out" | grep -q "2 embedded, 6 reused" && ok "real reinstall reuses rows by hash" || no "real reinstall reuses rows by hash" "$out"
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = 0 ]
