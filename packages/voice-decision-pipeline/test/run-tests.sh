#!/usr/bin/env bash
# Tests for voice-decision-pipeline.
#
# Redirects HOME and CLAUDE_DIR into a temp directory, so the real config is
# never touched, and runs every step on made-up data (test/fixtures.py): a
# Slack export, a Claude Code projects directory, a GSD repo and a fake
# Bitbucket API (test/fake_bitbucket.py). No real corpus is ever read.
#
#   ./test/run-tests.sh
#   VDP_TEST_HOME=<home built by setup> ./test/run-tests.sh
#
# Three groups:
#   installer   the kit's installer tests (installer-tests.sh)
#   behaviour   extraction, redaction, anonymising with the lists, mining,
#               the gates and review endpoints, forget — on the Python
#               module directly, spaCy switched off (VDP_NER=none)
#   real        the command itself on a real venv: spaCy finds names, the
#               index is embedded by embedding-lib, the stamp refuses a
#               mismatch. Needs VDP_TEST_HOME (a home `setup` built, because
#               building one is a 1.8 GB download) and embedding-lib set up.
#               Without them it fails, unless VDP_SKIP_REAL=1.
#
# Logs to /tmp/voice-decision-pipeline-tests.log.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${VDP_TEST_LOG:-/tmp/voice-decision-pipeline-tests.log}"
exec > >(tee "$LOG") 2>&1
echo "== voice-decision-pipeline tests, $(date -Is)"

REAL_HOME="$HOME"
EL_HOME_REAL="${EMBEDDING_LIB_HOME:-$REAL_HOME/.local/share/embedding-lib}"
TEST_HOME="${VDP_TEST_HOME:-}"
PY="${VDP_TEST_PY:-}"
[ -n "$PY" ] || { [ -x "$EL_HOME_REAL/venv/bin/python" ] && PY="$EL_HOME_REAL/venv/bin/python"; }
[ -n "$PY" ] || PY=python3
unset VDP_HOME VDP_STATE VDP_NER VDP_BITBUCKET_API VDP_NETRC VDP_LOG_DIR

TMP=$(mktemp -d)
FAKE_PID=""
cleanup() { [ -n "$FAKE_PID" ] && kill "$FAKE_PID" 2>/dev/null; rm -rf "$TMP"; }
trap cleanup EXIT
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

# The installer tests leave settings.json behind; the exclusion must be in it.
echo "installer, this package"
check "install registers the sandbox exclusion" \
  jq -e '.sandbox.excludedCommands | index("voice-decision-pipeline *")' "$CLAUDE_DIR/settings.json"

# --- behaviour --------------------------------------------------------------

echo "behaviour (python: $PY)"
F="$TMP/fixtures"; mkdir -p "$F"
"$PY" "$REPO/test/fixtures.py" "$F"
export VDP_STATE="$TMP/state" VDP_NER=none PYTHONPATH="$REPO/pylib" VDP_NETRC="$F/test-netrc"
ST="$VDP_STATE"
vdp(){ "$PY" -m vdp "$@"; }
mkdir -p "$CLAUDE_DIR/projects" && cp -r "$F/projects/." "$CLAUDE_DIR/projects/"

"$PY" "$REPO/test/fake_bitbucket.py" "$F/bitbucket-routes.json" > "$TMP/port" &
FAKE_PID=$!
for _ in $(seq 50); do [ -s "$TMP/port" ] && break; sleep 0.1; done
export VDP_BITBUCKET_API="http://127.0.0.1:$(cat "$TMP/port")/2.0"

vdp extract slack >/dev/null 2>&1 && no "extract refuses before init-inputs" "it ran" \
  || ok "extract refuses before init-inputs"
check "init-inputs copies build-inputs.json into state" vdp init-inputs "$F/build-inputs.json"
vdp init-inputs "$F/build-inputs.json" >/dev/null 2>&1 \
  && no "init-inputs refuses to overwrite" "it overwrote" || ok "init-inputs refuses to overwrite"
check "struck conversation names become ids" q '.struck_conversations == ["CSTRUCKXX"]' "$ST/inputs.json"
check "pick-repos records repos and James's account" vdp pick-repos ws/new-repo ws/old-repo --me '{me-uuid}'
out=$(vdp extract all --gsd-root "$F/dev" 2>&1); rc=$?
[ $rc = 0 ] && ok "extract all" || no "extract all" "$out"

S="$ST/corpus/slack.jsonl"
items(){ jq -c 'select(any(.tags[]; .type=="item"))' "$1"; }
check "Slack: James's 5 messages and 2 agreement reactions are items" \
  test "$(items "$S" | wc -l)" = 7
check "Slack: a custom agreement emoji listed in the inputs counts" \
  q -s 'map(select(.text|startswith("Morning")))[0].tags|map(.type)|index("reaction:bigthumb")' "$S"
check "Slack: the struck conversation is left out" \
  bash -c "! grep -q CSTRUCKXX '$S'"
check "Slack: channel joins are dropped" bash -c "! grep -q 'has joined' '$S'"
check "Slack: the bot message is context, tagged bot, never an item" \
  q -s 'map(select(.text=="Build 412 failed on main")) | length==1 and (.[0].tags|map(.type)|index("bot")) and ((.[0].tags|map(.type)|index("item"))|not)' "$S"
check "Slack: a +1 with a skin tone makes an item tagged reaction:+1" \
  q -s 'map(select(.text=="Shall we move standup to 10?")) | .[0].tags|map(.type)|index("reaction:+1")' "$S"
check "Slack: a joy reaction is not an item" \
  q -s 'map(select(.text=="lunch?"))|all(.[]; (.tags|map(.type)|index("item"))|not)' "$S"
check "Slack: an unthreaded message keeps its 2-hour window, not later messages" \
  q -s 'INDEX(.text) as $by | ($by["Morning, the build for Acme Corp is red again"].id) as $before
        | ($by["Far later message, outside every window"].id // "absent") as $far
        | (map(select(.text|startswith("```")))[0].id) as $after
        | (map(select(.text|startswith("Looking.")))[0].context_ids) as $c
        | ($c|index($before)) and ($c|index($after)) and (($c|index($far))|not)' "$S"
check "Slack: a thread parent keeps its replies as context" \
  q -s 'INDEX(.text) as $by | (map(select(.text|startswith("Fixed it.")))[0].context_ids) == [$by["Thanks, all green now"].id]' "$S"
check "Slack: credentials are redacted before storing" \
  bash -c "grep -q 'password=\[REDACTED:password\]' '$S' && grep -q '\[REDACTED:aws-access-key\]' '$S' && ! grep -q hunter2 '$S' && ! grep -q AKIAABCD '$S'"
check "Slack: the self-DM is an item tagged no-voice with no audience" \
  q -s 'map(select(.conversation=="DSELFNOTE"))[0] | (.tags|map(.type)|index("no-voice")) and .audience==null' "$S"
check "Slack: audiences come from the inputs" \
  q -s 'map(select(.conversation=="GCLIENTAC"))[0].audience=="clients"' "$S"
check "Slack: code and log spans are tagged" \
  q -s 'map(select(.text|startswith("```")))[0].tags|map(.type)|index("code")' "$S"
check "Slack: real names are kept in the stored corpus" grep -q "Gregor Whitfield" "$S"

TR="$ST/corpus/transcripts.jsonl"
check "Transcripts: a typed prompt keeps Claude's preceding reply and tool calls" \
  q -s 'map(select(.text|startswith("Use pytest")))|length==1' "$TR"
check "Transcripts: an AskUserQuestion answer is an item with its question" \
  q -s 'map(select(.tags|map(.type)|index("ask-user")))[0].source_fields.answers["Which database for the cache?"]=="Postgres"' "$TR"
check "Transcripts: the tool calls before a prompt are summarised" \
  q -s 'map(select(.text|startswith("/gsd:quick")))[0].source_fields.tool_calls|map(select(startswith("Edit: ")))|length==1' "$TR"
check "Transcripts: task notifications, meta, sidechain and subagent prompts are dropped" \
  bash -c "! grep -q -e 'task-notification' -e 'Base directory' -e 'sidechain prompt' -e 'subagent prompt' '$TR'"
check "Transcripts: a slash command is kept, tagged command, its token redacted" \
  bash -c "grep -q '/gsd:quick fix the token \[REDACTED:anthropic-key\]' '$TR'"
check "Transcripts: never voice" q -s 'all(.[]; .tags|map(.type)|index("no-voice"))' "$TR"
check "import-transcripts adds another machine's sessions" \
  vdp import-transcripts "$F/other-machine" --machine endeavour
check "Transcripts: imported prompts carry their machine" \
  q -s 'map(select(.source_fields.machine=="endeavour"))|length==1' "$TR"

G="$ST/corpus/gsd.jsonl"
check "GSD: two STATE.md decisions, continuation lines kept" \
  q -s 'map(select(.source_fields.kind=="state-decision"))|length==2 and (.[1].text|contains("no secure store"))' "$G"
check "GSD: CONTEXT.md decisions, Claude's Discretion tagged" \
  q -s 'map(select(.tags|map(.type)|index("claude-discretion")))|length==1' "$G"
check "GSD: repos without .planning are ignored" bash -c "! grep -q no-gsd '$G'"

B="$ST/corpus/bitbucket.jsonl"
check "Bitbucket: a repo last updated before 2019 is skipped" bash -c "! grep -q old-repo '$B'"
check "Bitbucket: PRs James wasn't involved in are skipped" bash -c "! grep -q 'pr:3' '$B'"
check "Bitbucket: a silent approval is an item" \
  q -s 'map(select(.source_fields.kind=="approval"))|length==1 and (.[0].tags|map(.type)|index("item"))' "$B"
check "Bitbucket: James's PR description and comment are items, others' are context" \
  q -s '[.[]|select(.tags|map(.type)|index("item"))|.source_fields.kind]|sort==["approval","comment","pr"]' "$B"
check "Bitbucket: James's reply keeps the PR and the comment it answers" \
  q -s 'map(select(.id|endswith(":c:22")))[0].context_ids==["bitbucket:ws/new-repo:pr:2","bitbucket:ws/new-repo:pr:2:c:21"]' "$B"
check "Bitbucket: an inline comment keeps the code under it" \
  q -s 'map(select(.id|endswith(":c:21")))[0].source_fields.inline.code|contains("+import json")' "$B"
check "Bitbucket: deleted comments are dropped" bash -c "! grep -q ':c:23' '$B'"

check "anonymise" vdp anonymise
A="$ST/anon/slack.jsonl"
check "anon: no real name, handle, email, phone or client name is left" \
  bash -c "! grep -q -i -e 'Priya' -e 'Raman' -e 'Gregor' -e 'Whitfield' -e 'Jamie' -e 'acme' -e '7700 900123' -e 'gregor@' '$ST'/anon/*.jsonl"
check "anon: mentions become @pseudonyms" grep -q "@colleague-01 can you send me the log" "$A"
check "anon: a unique first name becomes the person's pseudonym" grep -q "colleague-01, also ping client-contact-01" "$A"
check "anon: an ordinary first name (Tom) is left to spaCy, not the list" \
  bash -c "! grep -q 'colleague-02' <(jq -r .text '$A' | grep -v '^colleague')"
check "anon: client names inside URLs are replaced" grep -q "staging.client-01.com" "$A"
check "anon: authors are pseudonyms" q -s 'map(.author)|unique|sort==["bot","client-contact-01","colleague-01","colleague-02","self-01"]' "$A"
check "anon: record ids are opaque" bash -c "! grep -q -e 'slack:' -e 'ws/new-repo' '$ST'/anon/*.jsonl"
check "anon: replacements are marked at their place in the new text" \
  q -s 'map(select(.text|startswith("Looking.")))[0] as $r | $r.replacements|map($r.text[.start:.end])|index("@colleague-01")' "$A"
check "anon: a Bitbucket person is matched to the same Slack person" \
  q -s 'map(select(.source_fields.kind=="comment" and (.text|startswith("Why json"))))[0].author=="colleague-01"' "$ST/anon/bitbucket.jsonl"
check "mining: a capitalised term concentrated in one client's channel is a candidate" \
  q 'map(select(.term=="Zephyrline" and (.kinds|index("concentrated"))))|length==1' "$ST/mining-candidates.json"
check "map: one pseudonym per role, numbered from 01" \
  q '[.entries[].pseudonym]|sort==["client-01","client-contact-01","colleague-01","colleague-02","self-01"]' "$ST/anonymising-map.json"

vdp batch slack >/dev/null 2>&1 && no "batch refuses while mining candidates are undecided" "it drew one" \
  || ok "batch refuses while mining candidates are undecided"

python_review(){ "$PY" -m vdp review --port 0 --no-browser > "$TMP/review.out" 2>&1 & echo $!; }
RPID=$(python_review)
for _ in $(seq 50); do grep -q 'http://127' "$TMP/review.out" 2>/dev/null && break; sleep 0.1; done
URL=$(grep -o 'http://127.0.0.1:[0-9]*/' "$TMP/review.out")
post(){ curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d "$2" "$URL$1"; }
check "review page serves the home page" bash -c "curl -sf '$URL' | grep -q 'Mining'"
check "review page refuses a cross-origin POST" \
  test "$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Origin: http://evil.example' -d '{}' "${URL}api/mining")" = 403
check "keeping a mining term is saved" test "$(post api/mining '{"Zephyrline":"keep"}')" = 200
check "the keep is in mining-decisions.json" q '.Zephyrline.decision=="keep"' "$ST/mining-decisions.json"
check "a batch can't be drawn until anonymise reruns after the decision" \
  test "$(post api/draw '{"source":"slack"}')" = 409
vdp anonymise >/dev/null 2>&1
check "a kept term is replaced as product-NN" bash -c "grep -q 'product-01 ready Friday' '$A' && ! grep -q -i zephyrline '$A'"
vdp sendable slack; [ $? = 5 ] && ok "slack is not sendable before a batch is approved" \
  || no "slack is not sendable before a batch is approved" "sendable said yes"
check "a batch of items is drawn" test "$(post api/draw '{"source":"slack"}')" = 200
check "the batch holds only items, each with its context" \
  q '.items|length==7 and all(.[]; .item.tags|map(.type)|index("item"))' "$ST/batches/slack-001.json"
check "the batch page highlights replacements" bash -c "curl -sf '${URL}batch?source=slack' | grep -q \"<mark title='person'>\""
check "a second batch can't be drawn while one is open" test "$(post api/draw '{"source":"slack"}')" = 409
check "stopping before any approval is refused" test "$(post api/stop '{"source":"slack"}')" = 409
check "approving the batch" test "$(post api/decide '{"name":"slack-001","status":"approved"}')" = 200
check "slack is sendable once its first batch is approved" vdp sendable slack
vdp sendable bitbucket; [ $? = 5 ] && ok "approval is per source: bitbucket still isn't sendable" \
  || no "approval is per source: bitbucket still isn't sendable" "it is"
check "stopping a source after an approval" test "$(post api/stop '{"source":"slack"}')" = 200
check "a stopped source draws no more batches" test "$(post api/draw '{"source":"slack"}')" = 409
kill "$RPID" 2>/dev/null

check "forget a person by name" vdp forget "Gregor Whitfield"
check "forget: their messages are gone from corpus and anon copies" \
  bash -c "! grep -q UCLIGREGR '$S' && ! grep -q client-contact-01 <(jq -r .author '$A')"
check "forget: they are on the struck list" q '.struck_authors|index("UCLIGREGR")' "$ST/inputs.json"
check "forget: their map entry is kept, so mentions are still replaced" \
  q '.entries|map(select(.real_id=="UCLIGREGR"))|length==1' "$ST/anonymising-map.json"
vdp extract slack >/dev/null 2>&1
check "forget: a later extraction still skips them" bash -c "! grep -q '\"author\": \"UCLIGREGR\"' '$S'"
check "forget a conversation by id" vdp forget DPRIYADMX
check "forget: the conversation is struck" q '.struck_conversations|index("DPRIYADMX")' "$ST/inputs.json"
vdp forget UJAMESAAA >/dev/null 2>&1 && no "forgetting James is refused" "it ran" || ok "forgetting James is refused"
vdp forget "Nobody Atall" >/dev/null 2>&1 && no "forgetting an unknown name is refused" "it ran" \
  || ok "forgetting an unknown name is refused"
check "state is owner-only" bash -c "[ -z \"\$(find '$ST' -perm /077 -print -quit)\" ]"
check "status reports owner-only state and per-source review" \
  bash -c "\"$PY\" -m vdp status | jq -e '.not_owner_only==[] and .sources.slack.sendable and (.sources.bitbucket.sendable|not)' >/dev/null"

check "redaction: each credential kind" "$PY" - <<'EOF'
from collections import Counter
from vdp.textutil import redact
c = Counter()
s = redact("""xoxb-123456789012-abcdefABCDEF
ghp_abcdefghijklmnopqrstuvwxyz0123456789
eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U
aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA
-----END RSA PRIVATE KEY-----
api_key: "abc123"
https://hooks.slack.com/services/T000/B000/XXXXXXXX""", c)
want = {"slack-token", "github-token", "jwt", "aws-secret-key", "private-key", "password", "slack-webhook"}
assert want <= set(c), c
for leaked in ("xoxb-1234", "ghp_abc", "eyJhbGci", "wJalrXUt", "MIIEow", "abc123", "XXXXXXXX"):
    assert leaked not in s, (leaked, s)
assert redact("the password field is required") == "the password field is required"
EOF

# --- real -------------------------------------------------------------------

echo "real"
if [ -z "$TEST_HOME" ]; then
  if [ "${VDP_SKIP_REAL:-0}" = 1 ]; then echo "  skip  real (VDP_SKIP_REAL=1)"
  else no "real-environment tests" "set VDP_TEST_HOME to a home built by 'voice-decision-pipeline setup' (or VDP_SKIP_REAL=1)"; fi
else
  BIN="$REPO/bin/voice-decision-pipeline"
  export EMBEDDING_LIB_HOME="$EL_HOME_REAL" VDP_HOME="$TEST_HOME" VDP_LOG_DIR="$TMP/logs"
  mkdir -p "$TMP/logs"
  unset VDP_NER PYTHONPATH
  check "check: spaCy finds both names in the made-up sentence" "$BIN" check
  check "every command logs to its own file" bash -c "'$BIN' status >/dev/null && '$BIN' anonymise >/dev/null && test -s '$TMP/logs/voice-decision-pipeline-anonymise.log'"
  check "spaCy: anonymise with the real model" \
    bash -c "grep -q 'ok    anon/slack.jsonl' '$TMP/logs/voice-decision-pipeline-anonymise.log'"
  check "spaCy: nothing identifying is left after the model's pass" \
    bash -c "! grep -q -i -e 'Priya' -e 'Raman' -e 'Gregor' -e 'Whitfield' -e 'Jamie' -e 'acme' '$ST'/anon/*.jsonl"
  check "spaCy: its tags are cached, so a rerun tags nothing new" \
    bash -c "! '$BIN' anonymise | grep -q 'ner '"
  check "index: embedded by embedding-lib, with its identity" "$BIN" index
  check "index: one row per voice item, identity recorded" \
    bash -c "jq -e 'length>0' '$ST/index/ids.json' >/dev/null && jq -e '.model==\"BAAI/bge-base-en-v1.5\"' '$ST/index/identity.json' >/dev/null"
  check "index: transcripts, GSD records, approvals and the self-DM are not in it" \
    bash -c "! grep -q -e transcripts: -e gsd: -e approval -e DSELFNOTE '$ST/index/ids.json'"
  cp "$TEST_HOME/.venv-stamp" "$TMP/stamp"
  echo "3.0.0 different" > "$TEST_HOME/.venv-stamp"
  "$BIN" status >/dev/null 2>&1; rc=$?
  cp "$TMP/stamp" "$TEST_HOME/.venv-stamp"
  [ $rc = 4 ] && ok "a venv built for another embedding-lib Python is refused (exit 4)" \
    || no "a venv built for another embedding-lib Python is refused (exit 4)" "exit $rc"
  EMBEDDING_LIB_HOME="$TMP/nowhere" "$BIN" status >/dev/null 2>&1; rc=$?
  [ $rc = 4 ] && ok "without embedding-lib every command refuses (exit 4)" \
    || no "without embedding-lib every command refuses (exit 4)" "exit $rc"
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = 0 ]
