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

# Mining's dictionary is built, not committed: build it once in a checkout.
[ -s "$REPO/pylib/vdp/data/words.txt" ] || VDP_LOG_DIR="${TMPDIR:-/tmp}" "$REPO/tools/build-wordlist.sh" >/dev/null

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
check "pick-repos records repos and the owner's account" vdp pick-repos ws/new-repo ws/old-repo --me '{me-uuid}'
out=$(vdp extract all --gsd-root "$F/dev" 2>&1); rc=$?; EXTRACT_OUT=$out
[ $rc = 0 ] && ok "extract all" || no "extract all" "$out"

S="$ST/corpus/slack.jsonl"
items(){ jq -c 'select(any(.tags[]; .type=="item"))' "$1"; }
check "Slack: the owner's 6 messages and 2 agreement reactions are items" \
  test "$(items "$S" | wc -l)" = 8
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
  vdp import-transcripts "$F/other-machine" --machine other-box
check "Transcripts: imported prompts carry their machine" \
  q -s 'map(select(.source_fields.machine=="other-box"))|length==1' "$TR"

G="$ST/corpus/gsd.jsonl"
check "GSD: two STATE.md decisions, continuation lines kept" \
  q -s 'map(select(.source_fields.kind=="state-decision"))|length==2 and (.[1].text|contains("no secure store"))' "$G"
check "GSD: CONTEXT.md decisions, Claude's Discretion tagged" \
  q -s 'map(select(.tags|map(.type)|index("claude-discretion")))|length==1' "$G"
check "GSD: repos without .planning are ignored" bash -c "! grep -q no-gsd '$G'"

B="$ST/corpus/bitbucket.jsonl"
check "Bitbucket: a repo last updated before 2019 is skipped" bash -c "! grep -q old-repo '$B'"
check "Bitbucket: PRs the owner wasn't involved in are skipped" bash -c "! grep -q 'pr:3' '$B'"
check "Bitbucket: a PR the owner was only added to as a reviewer is skipped" bash -c "! grep -q 'pr:4' '$B'"
check "Bitbucket: PRs the owner wasn't in are never fetched one by one" \
  bash -c "! grep -q 'Bitbucket 404' <<< \"\$1\"" _ "$EXTRACT_OUT"
check "Bitbucket: a silent approval is an item" \
  q -s 'map(select(.source_fields.kind=="approval"))|length==1 and (.[0].tags|map(.type)|index("item"))' "$B"
check "Bitbucket: the owner's PR description and comment are items, others' are context" \
  q -s '[.[]|select(.tags|map(.type)|index("item"))|.source_fields.kind]|sort==["approval","comment","pr"]' "$B"
check "Bitbucket: the owner's reply keeps the PR and the comment it answers" \
  q -s 'map(select(.id|endswith(":c:22")))[0].context_ids==["bitbucket:ws/new-repo:pr:2","bitbucket:ws/new-repo:pr:2:c:21"]' "$B"
check "Bitbucket: an inline comment keeps the code under it" \
  q -s 'map(select(.id|endswith(":c:21")))[0].source_fields.inline.code|contains("+import json")' "$B"
check "Bitbucket: deleted comments are dropped" bash -c "! grep -q ':c:23' '$B'"
check "Bitbucket: a progress line per repo, with PRs seen, kept and calls" \
  bash -c "grep -q 'repo  1/2 ws/new-repo: 4 PRs seen, 2 kept, 1 added-only; [0-9]* calls' <<< \"\$1\"" _ "$EXTRACT_OUT"
check "Bitbucket: nothing is left saved once the extract is written" \
  bash -c "! ls '$ST/bitbucket-progress/'*.json 2>/dev/null"

cp "$B" "$TMP/bitbucket-before.jsonl"
vdp pick-repos ws/broken-repo >/dev/null
out=$(vdp extract bitbucket 2>&1) && no "Bitbucket: a run that fails partway fails" "it passed" \
  || ok "Bitbucket: a run that fails partway fails"
check "Bitbucket: the failed run leaves the corpus as it was" cmp -s "$B" "$TMP/bitbucket-before.jsonl"
check "Bitbucket: the repo finished before the failure is saved" \
  test -f "$ST/bitbucket-progress/ws__new-repo.json"
vdp pick-repos --remove ws/broken-repo >/dev/null
RERUN_OUT=$(vdp extract bitbucket 2>&1)
check "Bitbucket: the rerun takes the saved repo instead of fetching it" \
  bash -c "grep -q 'saved 1/2 ws/new-repo: 2 PRs kept' <<< \"\$1\"" _ "$RERUN_OUT"
check "Bitbucket: the rerun writes the same corpus" cmp -s "$B" "$TMP/bitbucket-before.jsonl"
check "Bitbucket: the saved repo is cleared after the rerun" \
  bash -c "! ls '$ST/bitbucket-progress/'*.json 2>/dev/null"

# forget before anonymise has built the map, each on its own copy of the state
fresh(){ rm -rf "$TMP/st-$1"; cp -a "$ST" "$TMP/st-$1"; echo "$TMP/st-$1"; }
gates(){ "$PY" -m vdp status | jq -r '.blocks_next_batch|join("\n")'; }
export -f gates; export PY
check "forget before anonymise: there is no map yet" test ! -e "$ST/anonymising-map.json"
F1=$(fresh person)
check "forget before anonymise: a Slack person by name" env VDP_STATE="$F1" "$PY" -m vdp forget "Tom Baker"
check "forget before anonymise: their Slack messages are gone" \
  bash -c "! grep -q '\"author\": \"UCOLTOMBB\"' '$F1/corpus/slack.jsonl'"
check "forget before anonymise: they are on the struck list" q '.struck_authors|index("UCOLTOMBB")' "$F1/inputs.json"
F2=$(fresh both)
check "forget before anonymise: a person in Slack and Bitbucket, by name" \
  env VDP_STATE="$F2" "$PY" -m vdp forget "Priya Raman"
check "forget: their Bitbucket comments go with their Slack messages" \
  bash -c "! grep -q -e '\"author\": \"bitbucket:{priya-uuid}\"' -e '\"author\": \"UCOLPRIYA\"' '$F2'/corpus/*.jsonl"
check "forget: both their ids are struck" \
  q '.struck_authors|(index("UCOLPRIYA") and index("bitbucket:{priya-uuid}"))' "$F2/inputs.json"
F3=$(fresh owner)
env VDP_STATE="$F3" "$PY" -m vdp forget "Alex Testperson" >/dev/null 2>&1 \
  && no "forget: the owner by name is refused" "it ran" || ok "forget: the owner by name is refused"
F4=$(fresh repo)
check "forget: a Bitbucket repo" env VDP_STATE="$F4" "$PY" -m vdp forget ws/new-repo
check "forget: every record of the repo's PRs is gone" bash -c "! grep -q 'ws/new-repo#' '$F4/corpus/bitbucket.jsonl'"
F5=$(fresh pr)
check "forget: one Bitbucket PR" env VDP_STATE="$F5" "$PY" -m vdp forget 'ws/new-repo#2'
env VDP_STATE="$F5" "$PY" -m vdp extract bitbucket >/dev/null 2>&1
check "forget: a forgotten PR stays out of a later extract" \
  bash -c "! grep -q 'ws/new-repo#2' '$F5/corpus/bitbucket.jsonl' && grep -q 'ws/new-repo#1' '$F5/corpus/bitbucket.jsonl'"

# A netrc Python refuses because others can read it; curl would read it.
mkdir -p "$TMP/nh" && cp "$F/test-netrc" "$TMP/nh/.netrc" && chmod 644 "$TMP/nh/.netrc"
F6=$(fresh netrc)
NOUT=$(env -u VDP_NETRC HOME="$TMP/nh" VDP_STATE="$F6" "$PY" -m vdp extract bitbucket 2>&1)
check "Bitbucket: a netrc others can read is reported as that, with the chmod" \
  bash -c "grep -q \"can't read ~/.netrc\" <<< \"\$1\" && grep -q 'chmod 600 ~/.netrc' <<< \"\$1\" && ! grep -q 'no ~/.netrc entry' <<< \"\$1\"" _ "$NOUT"

check "show bitbucket writes your items as text" vdp show bitbucket
V="$ST/views/bitbucket.txt"
check "show: the view is owner-only" bash -c "[ \"\$(stat -c %a '$V')\" = 600 ]"
check "show: a PR heading, your description, comment, reply and approval" \
  bash -c "grep -q '^ws/new-repo#2  \[MERGED\]  Switch to json logging' '$V' && grep -q 'your PR description' '$V' && grep -q 'replying to Priya Raman' '$V' && grep -q 'you approved' '$V'"
check "show: an inline comment shows its file, line and code" \
  bash -c "grep -q 'on src/app.py line 2' '$V' && grep -q '| +import json' '$V'"
check "show: other people's PRs without an item of yours are left out" bash -c "! grep -q 'ws/new-repo#3' '$V'"
check "show --repo writes that repo's view" \
  bash -c "\"$PY\" -m vdp show bitbucket --repo ws/new-repo >/dev/null && test -s '$ST/views/bitbucket-ws__new-repo.txt'"

# Mining: case decides nothing; an ordinary word is one in the
# bundled dictionary; source fields are read; junk and terms across three
# clients are left off; each other term carries a suggestion.
check "mining: no case rules, dictionary words, source fields, suggestions and order" "$PY" - <<'EOF'
from vdp.anonymise import mine, junk_term, dictionary
class Rep:
    class amap: entries = []
    norm = staticmethod(lambda s: s.lower())
TAGS = {"-": "ORG", "Zq": "ORG", "Delivery": "ORG", "eShop": "PRODUCT", "kwikpay": "PRODUCT",
        "Globalthing": "PRODUCT", "Pebblestack": "PRODUCT", "Cloudmuddle": "PRODUCT"}
class Ner:
    def ents(self, t):
        return [(i, i + len(w), l) for w, l in TAGS.items() for i in [t.find(w)] if i >= 0]
recs, n = [], 0
def add(text, conv, sf=None):
    global n; n += 1; recs.append({"id": f"r{n}", "conversation": conv, "text": text, "source_fields": sf or {}})
for _ in range(2): add("ping - Zq about eShop", "general")
for _ in range(3): add("the Delivery team", "general")
for _ in range(2): add("delivery is late", "general")
for _ in range(4): add("Wombatron build is red", "c-a")
for _ in range(3): add("Lighthouse scores dropped", "c-a")
for _ in range(3): add("pay with kwikpay", "general")
for _ in range(2): add("zorbix is slow", "c-a")
add("Zorbix is slow", "c-a")
for _ in range(3): add("", "c-a", {"questions": {"Ask Fennelworth?": "yes"}, "slack_ts": "Quuxol"})
for c in ("c-a", "c-b", "c-c"): add("Globalthing again", c); add("Globalthing again", c)
add("Pebblestack is down", "c-b"); add("Pebblestack again", "general")
add("Cloudmuddle is down", "c-b"); add("Cloudmuddle", "general"); add("Cloudmuddle", "general")
convs = {"c-a": "client-01", "c-b": "client-02", "c-c": "client-03"}
out = mine(recs, Rep(), Ner(), convs, {"ZORBIX": {"decision": "keep"}})
got = {c["term"]: c.get("suggest") for c in out}
want = {"Cloudmuddle": None, "kwikpay": None, "eShop": None,
        "Wombatron": "keep", "Fennelworth": "keep", "ZORBIX": "keep", "Pebblestack": "keep",
        "Delivery": "strike"}
assert got == want, got
assert [c["term"] for c in out] == list(want), [c["term"] for c in out]
assert next(c for c in out if c["term"] == "Wombatron")["client"] == "client-01"
assert "lighthouse" in dictionary() and "wombatron" not in dictionary()
out = mine(recs, Rep(), Ner(), convs)
assert "zorbix" in {c["term"] for c in out}, "the commonest spelling without a decision"
assert all(junk_term(t) for t in ("--", "x", "Zq", "*Foo*", "(Bar", "Foo\nBar", "12"))
assert not any(junk_term(t) for t in ("Foo Ltd.", "Bar (UK)", "Foo-Bar", "X10"))
EOF
check "mining skips fenced code, inline code, log lines and the inline field, and mines the prose around them" "$PY" - <<'EOF'
from vdp.anonymise import mine, mined_prose, Ner
class Rep:
    class amap: entries = []
    norm = staticmethod(lambda s: s.lower())
class NoNer:
    def ents(self, t): return []
recs, n = [], 0
def add(text, conv, sf=None):
    global n; n += 1; recs.append({"id": f"r{n}", "conversation": conv, "text": text, "source_fields": sf or {}})
for _ in range(3):
    add("see this:\n```\nval x = Fenzlotron()\n```", "c-a")
    add("call `Inkwomble.load()` first", "c-a")
    add("ERROR 2026-11-15 12:00:01 Traceback in Logrumbly", "c-a")
    add("fix this", "c-a", {"inline": {"path": "src/Pathnimble.kt", "code": "Codequaff()"}})
    add("the Proseworthy release", "c-a")
# A term in one client's prose and in two others' code is still one client's.
for c in ("c-b", "c-c"):
    for _ in range(2): add("```\nProseworthy.init()\n```", c)
convs = {"c-a": "client-01", "c-b": "client-02", "c-c": "client-03"}
got = {c["term"].lower(): c for c in mine(recs, Rep(), NoNer(), convs)}
for w in ("fenzlotron", "inkwomble", "logrumbly", "pathnimble", "codequaff"):
    assert w not in got, (w, sorted(got))
assert "proseworthy" in got and got["proseworthy"].get("suggest") == "keep", got.get("proseworthy")
assert got["proseworthy"]["clients"] == 1, got["proseworthy"]
t = "a `Foo` b"
assert mined_prose(t) == Ner.blank_code(t) and len(mined_prose(t)) == len(t) and "Foo" not in mined_prose(t)
EOF

# A single word only spaCy finds is a Names candidate.
# The spaCy cache is seeded with one tag, so this runs without the model.
F7=$(fresh spacyname)
"$PY" - "$F7" <<'EOF'
import hashlib, json, sys
t = "note to self: check Zephyrline caching"
with open(sys.argv[1] + "/spacy-cache.jsonl", "a") as f:
    f.write(json.dumps({"h": hashlib.sha1(t.encode()).hexdigest(), "e": [[20, 30, "PERSON"]]}) + "\n")
EOF
check "spaCy name: anonymise with one seeded tag" env VDP_STATE="$F7" "$PY" -m vdp anonymise
check "spaCy name: undecided, it is replaced only where spaCy tagged it" \
  bash -c "grep -q 'check person-01 caching' '$F7/anon/slack.jsonl' && grep -q 'The Zephyrline launch' '$F7/anon/slack.jsonl'"
check "spaCy name: it is a Names candidate, with its counts; a URL's lower case doesn't count" \
  q 'map(select(.key=="zephyrline"))|length==1 and .[0].tagged==1 and .[0].capitalised==5 and .[0].lower==0 and .[0].suggest=="name"' "$F7/name-candidates.json"
check "spaCy name: an undecided word holds batches" \
  env VDP_STATE="$F7" bash -c "gates | grep -q '1 single words spaCy took for a name are not marked'"
check "spaCy name: the leak check counts it as undecided, not as a leak" \
  q '.hits==0 and .undecided_names==1' "$F7/leak-report.json"
echo '{"zephyrline": {"decision": "name"}}' > "$F7/name-decisions.json"
check "spaCy name: a mark holds batches until anonymise runs again" \
  env VDP_STATE="$F7" bash -c "gates | grep -q 'names decided after the anonymised copies were made'"
env VDP_STATE="$F7" "$PY" -m vdp anonymise >/dev/null 2>&1
check "spaCy name: marked a name, it is replaced in every text, in any case; its private URL goes whole" \
  bash -c "! grep -q -i zephyrline '$F7/anon/slack.jsonl' && grep -q 'The person-01 launch needs the person-01 banner' '$F7/anon/slack.jsonl' && ! grep -q 'staging\\.' '$F7/anon/slack.jsonl' && grep -q '\\[url\\]' '$F7/anon/slack.jsonl'"
check "spaCy name: marked a name, the leak check is clean and no gate is left for it" \
  bash -c "jq -e '.hits==0 and .undecided_names==0' '$F7/leak-report.json' >/dev/null && ! VDP_STATE='$F7' gates | grep -q -e 'single words' -e 'names marked'"
echo '{"zephyrline": {"decision": "not"}}' > "$F7/name-decisions.json"
env VDP_STATE="$F7" "$PY" -m vdp anonymise >/dev/null 2>&1
check "spaCy name: marked not a name, it is left everywhere, where spaCy tagged it too" \
  bash -c "grep -q 'check Zephyrline caching' '$F7/anon/slack.jsonl' && grep -q 'The Zephyrline launch' '$F7/anon/slack.jsonl' && ! grep -q 'person-01' '$F7/anon/slack.jsonl'"
check "spaCy name: marked not a name, the leak check doesn't search for it" \
  bash -c "jq -e '.hits==0' '$F7/leak-report.json' >/dev/null && ! grep -q -i zephyrline '$F7/leak-report.json'"
echo '{"Zephyrline": {"decision": "keep"}}' > "$F7/mining-decisions.json"
echo '{"zephyrline": {"decision": "name"}}' > "$F7/name-decisions.json"
env VDP_STATE="$F7" "$PY" -m vdp anonymise >/dev/null 2>&1
check "spaCy name: once kept on the mining page it is a product, not a person" \
  bash -c "grep -q 'The product-01 launch' '$F7/anon/slack.jsonl' && ! grep -q 'person-01' '$F7/anon/slack.jsonl'"

check "anonymise" vdp anonymise
check "leak check: the fixtures' anonymised copies are clean" q '.hits==0 and .terms_checked>10' "$ST/leak-report.json"
check "anon: a first name in lower case, a dictionary key and a reaction name are replaced" "$PY" - <<'EOF'
from vdp import inputs
from vdp.anonmap import Map
from vdp.anonymise import Ner, Replacer
rep = Replacer(inputs.load(), Map.load(), Ner())
assert rep.apply("thanks priya")[0] == "thanks colleague-01", rep.apply("thanks priya")
assert rep.deep({"Ask Priya Raman?": "yes"}) == {"Ask colleague-01?": "yes"}, rep.deep({"Ask Priya Raman?": "yes"})
assert rep.replace_plain("priya-wave") == "colleague-01-wave", rep.replace_plain("priya-wave")
EOF
check "anon: a first name two people share becomes their role, and the leak check searches for it" "$PY" - <<'EOF'
import json, os, shutil
from vdp import inputs, leaks
from vdp.anonmap import Map
from vdp.anonymise import Ner, Replacer
d = inputs.load()
exp = os.path.join(os.environ["VDP_STATE"], "..", "shared-export")
shutil.rmtree(exp, ignore_errors=True)
shutil.copytree(d["slack_export"], exp)
users = json.load(open(os.path.join(exp, "users.json")))
users.append({"id": "UCOLPRIYK", "team_id": "T0HOME", "name": "priya.kapoor", "real_name": "Priya Kapoor",
              "profile": {"real_name": "Priya Kapoor", "first_name": "Priya", "last_name": "Kapoor"}})
json.dump(users, open(os.path.join(exp, "users.json"), "w"))
d["slack_export"] = exp
rep = Replacer(d, Map(), Ner())
got = rep.apply("Priya, ask Priya Kapoor")[0]
assert got.startswith("colleague, ask colleague-"), got
assert leaks.terms(d, Map()).get("priya") == "shared first name", leaks.terms(d, Map()).get("priya")
EOF
check "anon: a client listed as one word, written as two and tagged by spaCy as a person, is that client" "$PY" - <<'EOF'
from vdp import inputs, leaks
from vdp.anonmap import Map
from vdp.anonymise import Ner, Replacer
d = inputs.load()
d["anonymiser_additions_candidates"] = {"names": ["Acme Corp", "Globexco"]}
amap = Map()
amap.ensure("spacy:globexco", kind="person", role="person", origin="spacy", aliases=["Globex Co"])
rep = Replacer(d, amap, Ner())
client = amap.get("client:globexco")["pseudonym"]
assert rep.apply("ship it to Globex Co today")[0] == f"ship it to {client} today", rep.apply("ship it to Globex Co today")
assert rep.apply("globex-co and GLOBEX CO")[0] == f"{client} and {client}", rep.apply("globex-co and GLOBEX CO")
EOF
check "anon: a URL on a host that isn't public becomes [url]; a public one stays, names in it replaced" "$PY" - <<'EOF'
from vdp import inputs
from vdp.anonmap import Map
from vdp.anonymise import Ner, Replacer
rep = Replacer(inputs.load(), Map.load(), Ner())
cases = {
    "call https://api.quillford.example.com/v1/orders?id=9.": "call [url].",
    "see <https://int.quillford.co.uk/x|the API>": "see <[url]|the API>",
    "hit api.quillford.io/v2 and 10.1.2.3:8080/health": "hit [url] and [url]",
    "read https://docs.flutter.dev/ui and pub.dev/packages/http": "read https://docs.flutter.dev/ui and pub.dev/packages/http",
    "ask on https://github.com/acme-corp/repo": "ask on https://github.com/client-01/repo",
    "edit main.dart, settings.local.json and model.pt": "edit main.dart, settings.local.json and model.pt",
    "done.It works; mail ops" + "@" + "acme.example.com": "done.It works; mail [email]",
    "local http://localhost:3000/a": "local http://localhost:3000/a",
}
for t, want in cases.items():
    got, marks = rep.apply(t)
    assert got == want, (t, got)
got, marks = rep.apply("call https://api.quillford.example.com/v1 now")
assert [m["kind"] for m in marks] == ["url"], marks
EOF
check "anon: a client added by hand, with its identifier, is one pseudonym; removing it takes it off" "$PY" - <<'EOF'
from vdp import inputs
from vdp.anonmap import Map
from vdp.anonymise import Ner, Replacer, add_client, added_clients, remove_client
d = inputs.load()
d["anonymiser_additions_candidates"] = {"names": ["Globexco"]}
add_client("Marrowfield Retail", ["MR", "marrowfield-retail", "x", "Marrowfield Retail"])
assert added_clients()["marrowfieldretail"]["aliases"] == ["MR", "marrowfield-retail"], added_clients()
add_client("Globexco", ["GBX"])
amap = Map()
rep = Replacer(d, amap, Ner())
mr = amap.get("client:marrowfield retail")["pseudonym"]
gb = amap.get("client:globexco")["pseudonym"]
assert rep.apply("Marrowfield Retail, MR and mr")[0] == f"{mr}, {mr} and {mr}", rep.apply("Marrowfield Retail, MR and mr")
assert rep.apply("Globexco is GBX")[0] == f"{gb} is {gb}", rep.apply("Globexco is GBX")
remove_client("marrowfieldretail")
remove_client("globexco")
rep = Replacer(d, amap, Ner())
assert rep.apply("MR and GBX")[0] == "MR and GBX", rep.apply("MR and GBX")
assert rep.apply("Globexco")[0] == gb, "the list's own name stays"
assert "added_aliases" not in amap.get("client:globexco"), amap.get("client:globexco")
assert added_clients() == {}
EOF
check "anon: a kept product written with a spaced hyphen is replaced in each spelling" "$PY" - <<'EOF'
from vdp import inputs
from vdp.anonmap import Map
from vdp.anonymise import Ner, Replacer
amap = Map()
amap.ensure("product:quillford - depot", kind="product", role="product", origin="mining",
            aliases=["Quillford - Depot"])
rep = Replacer(inputs.load(), amap, Ner())
p = amap.get("product:quillford - depot")["pseudonym"]
for text in ("see Quillford - Depot now", "see quillford-depot now", "see QuillfordDepot now",
             "see Quillford Depot now"):
    assert rep.apply(text)[0] == f"see {p} now", (text, rep.apply(text))
EOF
check "leak check: only what is sent is searched, dictionary keys included" "$PY" - <<'EOF'
import json
from vdp import leaks, inputs, state
from vdp.anonmap import Map
with open(state.anon_file("gsd")) as f:
    keep = f.read()
with open(state.anon_file("gsd"), "a") as f:
    f.write(json.dumps({"id": "x2", "source": "priya", "tags": [{"type": "priya"}], "text": "clean",
                        "source_fields": {}}) + "\n")
r = leaks.scan(inputs.load(), Map.load())
assert r["hits"] == 0, r
with open(state.anon_file("gsd"), "a") as f:
    f.write(json.dumps({"id": "x3", "text": "clean", "source_fields": {"answers": {"Ask Priya Raman?": "yes"}}}) + "\n")
r = leaks.scan(inputs.load(), Map.load())
assert [t["term"] for t in r["terms"]] == ["priya raman"], r
with open(state.anon_file("gsd"), "w") as f:
    f.write(keep)
leaks.scan(inputs.load(), Map.load())
EOF
check "the command runs Python unbuffered, so progress lines reach the log as they happen" \
  grep -q 'PYTHONUNBUFFERED=1 exec "$VPY" -m vdp' "$REPO/bin/voice-decision-pipeline"
A="$ST/anon/slack.jsonl"
check "anon: no real name, handle, email, phone or client name is left" \
  bash -c "! grep -q -i -e 'Priya' -e 'Raman' -e 'Gregor' -e 'Whitfield' -e 'Alex' -e 'acme' -e '7700 900123' -e 'gregor@' '$ST'/anon/*.jsonl"
check "anon: mentions become @pseudonyms" grep -q "@colleague-01 can you send me the log" "$A"
check "anon: a unique first name becomes the person's pseudonym" grep -q "colleague-01, also ping client-contact-01" "$A"
check "anon: an ordinary first name (Tom) is left to spaCy, not the list" \
  bash -c "! grep -q 'colleague-02' <(jq -r .text '$A' | grep -v '^colleague')"
check "anon: a URL on a client's host goes whole, client name and all" bash -c "! grep -q 'staging\\.' '$A' && grep -q '\\[url\\]' '$A'"
check "anon: a group DM's name has every handle replaced, a short one too" \
  q -s 'map(.source_fields.conversation_name|select(.!=null and startswith("mpdm-")))|unique==["mpdm-self-01--colleague-01--colleague-02-1"]' "$A"
check "anon: authors are pseudonyms" q -s 'map(.author)|unique|sort==["bot","client-contact-01","colleague-01","colleague-02","self-01"]' "$A"
check "anon: record ids are opaque" bash -c "! grep -q -e 'slack:' -e 'ws/new-repo' '$ST'/anon/*.jsonl"
check "anon: replacements are marked at their place in the new text" \
  q -s 'map(select(.text|startswith("Looking.")))[0] as $r | $r.replacements|map($r.text[.start:.end])|index("@colleague-01")' "$A"
check "anon: a Bitbucket person is matched to the same Slack person" \
  q -s 'map(select(.source_fields.kind=="comment" and (.text|startswith("Why json"))))[0].author=="colleague-01"' "$ST/anon/bitbucket.jsonl"
check "mining: a non-dictionary term concentrated in one client's channel is a candidate" \
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
check "the mining page has its three sections and Decided as tabs" \
  bash -c "curl -sf '${URL}mining' | grep -q 'data-tab=hand' && curl -sf '${URL}mining' | grep -q 'data-tab=keep' && curl -sf '${URL}mining' | grep -q 'data-tab=strike' && curl -sf '${URL}mining' | grep -q 'data-tab=decided'"
check "the mining page marks a kept term as decided, so it leaves its section" \
  bash -c "curl -sf '${URL}mining' | grep -q \"data-term='Zephyrline' data-section='[a-z]*' data-decision='keep'\""
check "a batch can't be drawn until anonymise reruns after the decision" \
  test "$(post api/draw '{"source":"slack"}')" = 409
vdp anonymise >/dev/null 2>&1
check "a kept term is replaced as product-NN" bash -c "grep -q 'product-01 ready Friday' '$A' && ! grep -q -i zephyrline '$A'"
check "a kept term mining no longer lists is under Earlier runs, with its decision, not under Decided" \
  bash -c "jq -e 'map(select(.term|ascii_downcase==\"zephyrline\"))|length==0' '$ST/mining-candidates.json' >/dev/null && curl -sf '${URL}mining' | grep -q \"data-tab=earlier\" && curl -sf '${URL}mining' | grep -q \"data-term='Zephyrline' data-section='earlier' data-decision='keep'\""
vdp sendable slack; [ $? = 5 ] && ok "slack is not sendable before a batch is approved" \
  || no "slack is not sendable before a batch is approved" "sendable said yes"
check "a batch of items is drawn" test "$(post api/draw '{"source":"slack"}')" = 200
check "the batch holds only items, each with its context" \
  q '.items|length==8 and all(.[]; .item.tags|map(.type)|index("item"))' "$ST/batches/slack-001.json"
check "the batch page highlights replacements" bash -c "curl -sf '${URL}batch?source=slack' | grep -q \"<mark title='person'>\""
check "a second batch can't be drawn while one is open" test "$(post api/draw '{"source":"slack"}')" = 409
check "stopping before any approval is refused" test "$(post api/stop '{"source":"slack"}')" = 409
check "approving the batch" test "$(post api/decide '{"name":"slack-001","status":"approved"}')" = 200
check "slack is sendable once its first batch is approved" vdp sendable slack
vdp sendable bitbucket; [ $? = 5 ] && ok "approval is per source: bitbucket still isn't sendable" \
  || no "approval is per source: bitbucket still isn't sendable" "it is"
check "stopping a source after an approval" test "$(post api/stop '{"source":"slack"}')" = 200
check "a stopped source draws no more batches" test "$(post api/draw '{"source":"slack"}')" = 409
check "a bitbucket batch is drawn" test "$(post api/draw '{"source":"bitbucket"}')" = 200
sleep 1; vdp anonymise >/dev/null 2>&1
check "a batch drawn before the last anonymise can't be approved" \
  test "$(post api/decide '{"name":"bitbucket-001","status":"approved"}')" = 409
check "its page says it can only be rejected" \
  bash -c "curl -sf '${URL}batch?source=bitbucket' | grep -q 'can only be rejected'"
check "it can be rejected" test "$(post api/decide '{"name":"bitbucket-001","status":"rejected"}')" = 200
check "clients: the page has the add form" bash -c "curl -sf '${URL}clients' | grep -q 'Add client'"
check "clients: a name shorter than 2 characters is refused" \
  test "$(post api/clients '{"add":{"name":"Q","aliases":[]}}')" = 400
check "clients: adding one is saved, with its identifier" \
  bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d '{\"add\":{\"name\":\"Marrowfield Retail\",\"aliases\":[\"MR\",\"\"]}}' '${URL}api/clients')\" = 200 ] && jq -e '.marrowfieldretail.aliases==[\"MR\"]' '$ST/added-clients.json' >/dev/null"
check "clients: the page and home page list it" \
  bash -c "curl -sf '${URL}clients' | grep -q 'Marrowfield Retail' && curl -sf '$URL' | grep -q '1 added'"
check "clients: a batch waits for anonymise after an added client" \
  "$PY" -c "from vdp import batches; g = batches.gates(); assert any('clients added' in x for x in g), g"
check "clients: removing it is saved" \
  bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d '{\"remove\":\"marrowfieldretail\"}' '${URL}api/clients')\" = 200 ] && jq -e '.=={}' '$ST/added-clients.json' >/dev/null"
check "clients: with it removed, that gate is gone" \
  "$PY" -c "from vdp import batches; g = batches.gates(); assert not any('clients added' in x for x in g), g"

check "audiences: the page lists the group DM with no audience, not the self-DM" \
  bash -c "p=\$(curl -sf '${URL}audiences'); grep -q 'mpdm-alex.testperson--priya.raman--tom-1' <<< \"\$p\" && ! grep -q DSELFNOTE <<< \"\$p\""
check "audiences: the home page counts it" bash -c "curl -sf '$URL' | grep -q '1 without an audience'"
check "audiences: the Slack items in it carry no audience yet" \
  q -s 'map(select(.conversation=="GMPIMTRIO" and .author=="UOWNERAAA"))|length==1 and .[0].audience==null' "$S"
check "audiences: an unknown audience is refused" test "$(post api/audience '{"GMPIMTRIO":"everyone"}')" = 400
check "audiences: picking one is saved" test "$(post api/audience '{"GMPIMTRIO":"project team"}')" = 200
check "audiences: the inputs keep the hand-written rule beside the choice" \
  q '.conversations|map(select(.id=="GMPIMTRIO"))[0]|.audience=="project team" and (.audience_rule|startswith("senior/management if")) and .audience_set_on=="mapping page"' "$ST/inputs.json"
check "audiences: batches wait for the Slack extract to run again" \
  bash -c "gates | grep -q 'audiences changed since the Slack extract'"
vdp extract slack >/dev/null 2>&1
check "audiences: the re-extracted items carry the chosen audience" \
  q -s 'map(select(.conversation=="GMPIMTRIO" and .author=="UOWNERAAA"))[0].audience=="project team"' "$S"
check "audiences: then batches wait for anonymise" \
  bash -c "gates | grep -q 'audiences changed since the anonymised copies were built'"
vdp anonymise >/dev/null 2>&1
check "audiences: after anonymise no audience gate is left" bash -c "! gates | grep -q audiences"
check "audiences: the page still lists it, with the choice pressed, so it can be changed" \
  bash -c "curl -sf '${URL}audiences' | grep -q \"data-a='project team' aria-pressed=true\""
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
vdp forget UOWNERAAA >/dev/null 2>&1 && no "forgetting the owner is refused" "it ran" || ok "forgetting the owner is refused"
vdp forget "Nobody Atall" >/dev/null 2>&1 && no "forgetting an unknown name is refused" "it ran" \
  || ok "forgetting an unknown name is refused"
check "leak check: a real name left in an anonymised copy is found" "$PY" - <<EOF
import json
from vdp import leaks, inputs, state
from vdp.anonmap import Map
with open(state.anon_file("gsd"), "a") as f:
    f.write(json.dumps({"id": "x1", "text": "ask Priya Raman", "source_fields": {"t": "tom"}}) + "\\n")
r = leaks.scan(inputs.load(), Map.load())
got = {t["term"]: t for t in r["terms"]}
assert "priya raman" in got and got["priya raman"]["kind"] == "person name", r
assert got["priya raman"]["examples"][0]["id"] == "x1", r
assert "tom" in got and got["tom"]["kind"] == "slack handle", r
EOF
check "leak check: the review page lists the term" \
  "$PY" -c "from vdp import review; p = review.leaks_page(); assert 'priya raman' in p and 'x1' in p, p"
check "leak check: a word before a pseudonym that spells a product's name with it is no leak" "$PY" - <<'EOF'
import json
from vdp import leaks, inputs, state
from vdp.anonmap import Map
amap = Map.load()
amap.ensure("product:other", kind="product", role="product", origin="mining", aliases=["Otherthing"])
amap.ensure("product:brindle product", kind="product", role="product", origin="mining",
            aliases=["Brindle Product"])
p = amap.get("product:other")["pseudonym"]
assert p.startswith("product-"), p
with open(state.anon_file("gsd"), "a") as f:
    f.write(json.dumps({"id": "x2", "text": f"the brindle {p} build"}) + "\n")
r = leaks.scan(inputs.load(), amap)
assert "brindle product" not in {t["term"] for t in r["terms"]}, r
with open(state.anon_file("gsd"), "a") as f:
    f.write(json.dumps({"id": "x3", "text": "the Brindle Product build"}) + "\n")
r = leaks.scan(inputs.load(), amap)
got = {t["term"]: t for t in r["terms"]}
assert [e["id"] for e in got["brindle product"]["examples"]] == ["x3"], r
assert "Brindle Product" in got["brindle product"]["examples"][0]["text"], r
EOF
check "leak check: a URL on a host that isn't public is a leak; a public one isn't" "$PY" - <<'EOF'
import json
from vdp import leaks, inputs, state
from vdp.anonmap import Map
with open(state.anon_file("gsd"), "a") as f:
    f.write(json.dumps({"id": "x4", "text": "GET https://api.quillford.example.com/v1 and https://pub.dev/x"}) + "\n")
r = leaks.scan(inputs.load(), Map.load())
got = {t["term"]: t for t in r["terms"]}
assert got["api.quillford.example.com"]["kind"] == "private URL host", r
assert got["api.quillford.example.com"]["examples"][0]["id"] == "x4", r
assert "pub.dev" not in got, r
EOF
check "leak check: a public host holding a pseudonym is sent that way and isn't a leak" "$PY" - <<'EOF'
import json
from vdp import leaks, inputs, state
from vdp.anonmap import Map
amap = Map.load()
p = amap.ensure("product:other", kind="product", role="product", origin="mining",
                aliases=["Otherthing"])["pseudonym"]
with open(state.anon_file("gsd"), "a") as f:
    f.write(json.dumps({"id": "x8", "text": f"see https://docs.{p}.com/start and {p}.stripe.com/a"}) + "\n")
r = leaks.scan(inputs.load(), amap)
assert not [t for t in r["terms"] if "x8" in [e["id"] for e in t["examples"]]], r
EOF
check "leak page: each snippet names the real term behind every pseudonym in it" "$PY" - <<'EOF'
import json
from vdp import leaks, inputs, review, state
from vdp.anonmap import Map
amap = Map.load()
p = amap.ensure("product:other", kind="product", role="product", origin="mining",
                aliases=["Otherthing"])["pseudonym"]
amap.save()
with open(state.anon_file("gsd"), "a") as f:
    # A fixture name from the term list, so the page has a hit to show.
    name = next(k for k, v in sorted(leaks.terms(inputs.load(), amap).items()) if v == "person name")
    f.write(json.dumps({"id": "x9", "text": f"ask {name} about {p}"}) + "\n")
leaks.scan(inputs.load(), amap)
page = review.leaks_page()
assert f"{p} is <b>Otherthing</b>" in page, page
assert review.pseudonym_terms(f"{p} and {p}, self-01", amap)[0] == (p, "Otherthing")
EOF
check "leak check: a name after a newline or a tab is found; a public host after a newline isn't a leak" "$PY" - <<'EOF'
import json
from vdp import leaks, inputs, state
from vdp.anonmap import Map
# The fixtures' own names, taken from the term list rather than spelled here.
t = leaks.terms(inputs.load(), Map.load())
name = next(k for k, v in sorted(t.items()) if v == "person name" and " " in k)
handle = next(k for k, v in sorted(t.items()) if v == "slack handle")
def counts():
    r = leaks.scan(inputs.load(), Map.load())
    return r, {x["term"]: x["count"] for x in r["terms"]}
_, before = counts()
with open(state.anon_file("gsd"), "a") as f:
    f.write(json.dumps({"id": "x5", "text": "first line\n" + name.title() + " said"}) + "\n")
    f.write(json.dumps({"id": "x6", "text": "see\t" + name, "source_fields": {"t": "a\n" + handle}}) + "\n")
    f.write(json.dumps({"id": "x7", "text": "docs at\npub.dev/x and\nhttps://pub.dev/y"}) + "\n")
r, after = counts()
assert after.get(name, 0) - before.get(name, 0) == 2, (name, before, after)
assert after.get(handle, 0) - before.get(handle, 0) == 1, (handle, before, after)
assert not any("pub.dev" in x["term"] for x in r["terms"]), r
assert leaks.unescape_blank(json.dumps("a\nb\u0001c")) == '"a  b      c"', leaks.unescape_blank(json.dumps("a\nb\u0001c"))
EOF
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

# --- voice --------------------------------------------------------------------

echo "voice"
VST="$TMP/vstate"; VBIN="$TMP/vbin"; VPYL="$TMP/vpylib"
mkdir -p "$VST" "$VBIN" "$VPYL"
"$PY" "$REPO/test/voice_fixtures.py" "$VST" "$VBIN" "$VPYL"
# Every voice step, and every voice page, once on empty state and once on
# state with nothing labelled yet: each either works or refuses with one
# line, never a traceback. Most other tests run a step only after the steps
# before it, so this is what covers a step run first.
VE="$TMP/vempty"; mkdir -p "$VE"
"$PY" - "$VST" "$TMP/vfresh" <<'EOF'
import shutil, sys
shutil.copytree(sys.argv[1], sys.argv[2])
EOF
for st in "$VE" "$TMP/vfresh"; do
  name=$([ "$st" = "$VE" ] && echo "empty state" || echo "state starting with nothing labelled")
  for step in "label" "label --second" "label --new-sample" "holdout" "holdout --fresh" "rules" "guide" \
              "validate" "pairs" "pairs --more clients" "build" "publish" "status"; do
    out=$(VDP_STATE="$st" VDP_CLAUDE="$VBIN/claude" BUILDS_SYNC_HOME="$TMP/no-builds-sync" \
          PYTHONPATH="$REPO/pylib:$VPYL" "$PY" -m vdp voice $step 2>&1); rc=$?
    if printf '%s' "$out" | grep -q Traceback || { [ "$rc" != 0 ] && [ "$(printf '%s\n' "$out" | wc -l)" -gt 3 ]; }; then
      no "voice $step on $name works or refuses in one line" "exit $rc: $(printf '%s' "$out" | tail -2)"
    else ok "voice $step on $name works or refuses in one line (exit $rc)"; fi
  done
  # On the second state the steps above ran in order on approved sources,
  # so by now it holds labels, a guide, drafts and a build.
  want=$([ "$st" = "$VE" ] && echo '.newest_build==null' || echo '.newest_build!=null')
  check "voice status on $name prints its JSON" \
    bash -c "VDP_STATE='$st' PYTHONPATH='$REPO/pylib:$VPYL' '$PY' -m vdp voice status | jq -e 'has(\"publish_blocked_by\") and $want' >/dev/null"
  RP=$(VDP_STATE="$st" PYTHONPATH="$REPO/pylib:$VPYL" "$PY" -m vdp review --port 0 --no-browser > "$TMP/vr-empty.out" 2>&1 & echo $!)
  for _ in $(seq 50); do grep -q 'http://127' "$TMP/vr-empty.out" 2>/dev/null && break; sleep 0.1; done
  EU=$(grep -o 'http://127.0.0.1:[0-9]*/' "$TMP/vr-empty.out")
  for pg in "" voice voice/labels voice/disagree voice/pairs voice/judge voice/report leaks; do
    code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$EU$pg")
    case "$code" in 200|400) ok "page /$pg on $name answers ($code)" ;;
      *) no "page /$pg on $name answers" "HTTP $code: $(tail -2 "$TMP/vr-empty.out")" ;; esac
  done
  kill "$RP" 2>/dev/null; wait "$RP" 2>/dev/null
done
rm -rf "$TMP/vfresh"
if ! "$PY" -c 'import numpy' 2>/dev/null; then
  no "voice tests" "$PY has no numpy; run them with embedding-lib's venv python (VDP_TEST_PY)"
else
vv(){ VDP_STATE="$VST" VDP_CLAUDE="$VBIN/claude" PYTHONPATH="$REPO/pylib:$VPYL" "$PY" -m vdp voice "$@"; }
vpy(){ VDP_STATE="$VST" PYTHONPATH="$REPO/pylib:$VPYL" "$PY" - ; }
echo '{"slack":{"batches":[],"approved":0,"stopped":false}}' > "$VST/review.held.json"
cp "$VST/review-state.json" "$VST/review.ok.json"; cp "$VST/review.held.json" "$VST/review-state.json"
vv label >/dev/null 2>&1 && no "voice label refuses before a source's first batch is approved" "it sent" \
  || ok "voice label refuses before a source's first batch is approved"
cp "$VST/review.ok.json" "$VST/review-state.json"
check "voice label: the stand-in claude was never called while held" test ! -e "$VST/labels/labeller.jsonl"
cp "$VST/leak-report.json" "$VST/leak-report.clean.json"
cat > "$VST/leak-report.json" <<'EOF'
{"terms_checked": 3, "undecided_names": 0, "hits": 3, "terms": [{"term": "group.com", "kind": "private URL host", "count": 3, "examples": [{"source": "bitbucket", "id": "x", "text": "group.com.client-01.app"}]}]}
EOF
out=$(vv label 2>&1); rc=$?
[ $rc != 0 ] && printf '%s' "$out" | grep -q "leak check has 1 term(s) not fixed or cleared (private URL host 3x)" \
  && ! printf '%s' "$out" | grep -q "group.com" \
  && ok "voice label refuses on an uncleared leak hit, naming its kind and count, never the term" \
  || no "voice label refuses on an uncleared leak hit, naming its kind and count, never the term" "exit $rc: $out"
check "the stand-in claude was never called while the leak hit stood" test ! -e "$VST/labels/labeller.jsonl"
check "a term cleared by hand no longer stops sending; found more times, it does again" vpy <<'EOF'
from vdp import leaks, state, voice
leaks.set_cleared("group.com", True, 3)
assert leaks.gate() is None, leaks.gate()
voice.require_sendable()
r = leaks.load(); r["terms"][0]["count"] = 4; r["hits"] = 4
state.write_json(leaks.report_file(), r)
assert "1 term(s)" in leaks.gate()
assert leaks.outstanding(r, by_count=False) == []
leaks.set_cleared("group.com", False)
assert leaks.cleared() == {}
EOF
rm -f "$VST/leak-report.json"
out=$(vv label 2>&1); rc=$?
[ $rc != 0 ] && printf '%s' "$out" | grep -q "leak check hasn't run yet" \
  && ok "voice label refuses before any leak check has run" || no "voice label refuses before any leak check has run" "exit $rc: $out"
cp "$VST/leak-report.clean.json" "$VST/leak-report.json"
export FAKE_CLAUDE_COUNT="$TMP/claude-count"; echo 0 > "$FAKE_CLAUDE_COUNT"
FAKE_CLAUDE_LIMIT=3 vv label > "$TMP/vlabel1.out" 2>&1; rc=$?
[ $rc = 6 ] && grep -q "usage limit after 40 items" "$TMP/vlabel1.out" \
  && ok "a usage limit stops the pass cleanly (exit 6) after the finished batches" \
  || no "a usage limit stops the pass cleanly (exit 6) after the finished batches" "exit $rc: $(tail -2 "$TMP/vlabel1.out")"
for t in "You've hit your 5-hour limit · resets 4am (UTC)" "You've hit your weekly limit · resets Mon 9am"; do
  echo 0 > "$FAKE_CLAUDE_COUNT"
  FAKE_CLAUDE_LIMIT=1 FAKE_CLAUDE_LIMIT_TEXT="$t" VDP_CLAUDE="$VBIN/claude" vpy > "$TMP/vlimit.out" 2>&1 <<'PYEOF'
from vdp import model
try:
    model.call("labeller", "s", "p", {"type": "object"}, log=print)
except model.UsageLimit:
    print("stopped")
PYEOF
  name="\"${t%% ·*}\" stops the pass as a usage limit, with no retry"
  [ "$(cat "$TMP/vlimit.out")" = stopped ] && [ "$(cat "$FAKE_CLAUDE_COUNT")" = 1 ] \
    && ok "$name" || no "$name" "$(cat "$FAKE_CLAUDE_COUNT") calls: $(cat "$TMP/vlimit.out")"
done
check "the stopped pass kept its two finished batches" test "$(wc -l < "$VST/labels/labeller.jsonl")" = 40
check "the rerun resumes after them and labels every voice item" \
  bash -c "VDP_STATE='$VST' VDP_CLAUDE='$VBIN/claude' PYTHONPATH='$REPO/pylib:$VPYL' '$PY' -m vdp voice label | grep -q '50 of 90 items to send' && test \$(wc -l < '$VST/labels/labeller.jsonl') = 90"
check "each label line names its model and prompt version" \
  bash -c "head -1 '$VST/labels/labeller.jsonl' | jq -e '.model==\"claude-sonnet-5-5\" and (.prompt|length)==12' >/dev/null"
check "the second model's blind pass labels them all with Opus" \
  bash -c "VDP_STATE='$VST' VDP_CLAUDE='$VBIN/claude' PYTHONPATH='$REPO/pylib:$VPYL' '$PY' -m vdp voice label --second >/dev/null && jq -s -e 'length==90 and all(.[]; .model==\"claude-opus-5-5\")' '$VST/labels/second.jsonl' >/dev/null"
check "every disagreement is recorded with both models' labels" \
  bash -c "jq -s -e 'length>0 and all(.[]; (.second|index(\"thank\")) and (.labeller|index(\"thank\")|not))' '$VST/labels/disagreements.jsonl' >/dev/null"
check "the disagreement rate is measured per purpose" vpy <<'EOF'
from vdp import labels
r = labels.disagreement_rates()
assert r["thank"]["differ"] == r["thank"]["either"] > 0 and r["ask"]["differ"] == 0, r
EOF
check "the disagreement page puts each model on A or B per item, the same way on every load" vpy <<'EOF'
import re
from vdp import labels, state, voicereview
ids = [f"r{n:04d}" for n in range(200)]
on_a = [voicereview.sides(i)[0] for i in ids]
assert 70 < on_a.count("labeller") < 130, on_a.count("labeller")
assert [voicereview.sides(i)[0] for i in ids] == on_a
assert all(set(voicereview.sides(i)) == {"labeller", "second"} for i in ids)
h = voicereview.disagree_page()
ds = {x["id"]: x for x in state.read_jsonl(state.path("labels", "disagreements.jsonl"))}
rows = re.findall(r"<tr id='i-([^']+)'>.*?A: <b>([^<]*)</b> · B: <b>([^<]*)</b>.*?"
                  r"onclick=\"dg\('[^']+','(\w+)'\)\">A right.*?onclick=\"dg\('[^']+','(\w+)'\)\">B right", h, re.S)
assert rows
for i, ta, tb, pa, pb in rows:
    sa, sb = voicereview.sides(i)
    assert (pa, pb) == (sa, sb), (i, pa, pb)
    assert ta == ", ".join(ds[i][sa]) and tb == ", ".join(ds[i][sb]), (i, ta, tb)
EOF
check "the disagreement-grade sample is kept, and label --new-sample draws it afresh with earlier grades kept" vpy <<'EOF'
import subprocess, sys, os
from vdp import labels, state
f = labels.disagree_grades_file()
g = state.read_json(f, None)
old_ids = list(g["ids"])
assert old_ids, g
# a file from before rounds were recorded, with one grade in it
g = {"ids": old_ids, "answers": {old_ids[0]: {"pick": "neither", "purposes": ["other"]}}}
state.write_json(f, g)
labels.write_disagreements()
assert state.read_json(f, None) == g, "drawn once: a plain rebuild keeps the sample"
assert labels.disagree_result() == {"drawn": True, "round": 1, "size": len(old_ids), "answered": 1, "done": len(old_ids) == 1}
assert labels.corrections()[old_ids[0]] == ["other"]
env = dict(os.environ, VDP_CLAUDE=os.path.join(os.path.dirname(os.environ["VDP_STATE"]), "vbin", "claude"))
subprocess.run([sys.executable, "-m", "vdp", "voice", "label", "--new-sample"], env=env, check=True, capture_output=True)
d = state.read_json(f, None)
cur = {x["id"] for x in labels.disagreements()}
assert d["round"] == 2 and d["answers"] == {} and d["prompt"] == labels.prompt_version(), d
assert d["ids"] and set(d["ids"]) <= cur and len(d["ids"]) == min(len(cur), labels.DISAGREE_SAMPLE)
assert d["previous"] == [{"round": 1, "prompt": None, "ids": old_ids, "answers": g["answers"]}]
assert old_ids[0] not in labels.corrections(), "an earlier round's grade no longer stands in for the labels"
assert state.read_json(labels.check_file(), None)["prompt"] == labels.prompt_version(), "the label check is drawn too"
EOF
check "labelling notes in the state change the prompt version, so a rerun is traceable" vpy <<'EOF'
from vdp import labels
v = labels.prompt_version()
open(labels.notes_file(), "w").write("Thanks at the end of a status is still status.")
assert labels.prompt_version() != v and "Thanks at the end" in labels.system_prompt()
EOF
check "label --redo sends again only the items either model gave that purpose" \
  bash -c "VDP_STATE='$VST' VDP_CLAUDE='$VBIN/claude' PYTHONPATH='$REPO/pylib:$VPYL' '$PY' -m vdp voice label --redo thank | grep -q '== label labeller: 10 of 90 items'"
check "a redo run again under the same prompt resumes: nothing already redone is sent again" \
  bash -c "VDP_STATE='$VST' VDP_CLAUDE='$VBIN/claude' PYTHONPATH='$REPO/pylib:$VPYL' '$PY' -m vdp voice label --redo thank | grep -q '== label labeller: 0 of 90 items'"
check "the second model's redo sends the same items, though the labeller's redo changed its labels" vpy <<'EOF'
import json, os
from vdp import labels
os.environ["VDP_CLAUDE"] = os.environ.get("VDP_CLAUDE") or os.path.join(os.path.dirname(os.environ["VDP_STATE"]), "vbin", "claude")
pv = labels.prompt_version()
redone = [i for i, r in labels.read("labeller").items() if r.get("prompt") == pv]
assert len(redone) == 10, len(redone)
with open(labels.labels_file("labeller"), "a") as f:
    for i in redone:
        f.write(json.dumps({"id": i, "purposes": ["status"], "prompt": pv, "model": "x"}) + "\n")
with open(labels.labels_file("second"), "a") as f:
    for i in redone:
        f.write(json.dumps({"id": i, "purposes": ["status"], "prompt": "older", "model": "x"}) + "\n")
out = []
assert labels.run("second", redo={"thank"}, log=out.append) == 0
assert any("== label second: 10 of 90 items" in l for l in out), out
assert {i for i, r in labels.read("second").items() if r.get("prompt") == pv} == set(redone)
EOF
check "a redo naming an unknown purpose is refused before anything is sent" \
  bash -c "VDP_STATE='$VST' VDP_CLAUDE='$VBIN/claude' PYTHONPATH='$REPO/pylib:$VPYL' '$PY' -m vdp voice label --redo thanks 2>&1 | grep -q 'unknown purpose thanks'"
check "the label-check sample spreads across audiences, and grading it is a gate" vpy <<'EOF'
from vdp import labels, voice, voicebuild
d = labels.draw_sample()
aud = {it["id"]: it["audience"] for it in voice.load()}
assert len(d["ids"]) == 90 and len({aud[i] for i in d["ids"]}) == 5, len(d["ids"])
assert any("label check" in g for g in voicebuild.gates())
for i in d["ids"][:7]:
    d["answers"][i] = {"verdict": "wrong", "purposes": ["other"]}
for i in d["ids"][7:]:
    d["answers"][i] = {"verdict": "right", "purposes": []}
from vdp import state
state.write_json(labels.check_file(), d)
c = labels.check_result()
assert c["done"] and not c["passed"], c   # 7 of 90 is over 6 of 120's rate
for i in d["ids"][:3]:
    d["answers"][i] = {"verdict": "right", "purposes": []}
state.write_json(labels.check_file(), d)
assert labels.check_result()["passed"]
assert labels.final()[d["ids"][3]] == ["other"], "the owner's correction wins"
EOF
check "holdout: 10% per audience, drawn once, fresh only on request" vpy <<'EOF'
from vdp import pool
h = pool.holdout(log=lambda *a: None)
assert h["run"] == 1 and len(h["ids"]) == 10, h
assert pool.holdout(log=lambda *a: None)["ids"] == h["ids"]
EOF
check "the pool leaves out holdouts, 3-word messages and code, and stores [code]" vpy <<'EOF'
from vdp import pool, voice
ex = pool.exemplars()
held = pool.held()
assert not held & {e["id"] for e in ex}
assert not any(e["text"] in ("ok",) for e in ex)
assert not any("Traceback" in e["text"] for e in ex)
assert all(len(e["hash"]) == 64 for e in ex)
assert voice.without_code("see `x = 1` and\n```\ncode\n```\ndone", [
    {"type": "code", "start": 4, "end": 11}, {"type": "code", "start": 16, "end": 28}]) == "see [code] and\n[code]\ndone"
EOF
check "stats and the never-say list are local, measured on the anonymised copies" vpy <<'EOF'
from vdp import voicestats
s = voicestats.build(log=lambda *a: None)
assert set(s["audiences"]) == {"clients", "project-team", "technical-team", "senior", "one-to-one"}, s["audiences"].keys()
ns = {x["phrase"]: x for x in s["never_say"]}
assert ns["kind regards"]["self"] == 0 and ns["kind regards"]["reference"] == "generic"
assert "much appreciated" not in ns or ns["much appreciated"]["self"] / 90 <= 0.001
EOF
check "voice rules creates the own-rules file once" bash -c "VDP_STATE='$VST' PYTHONPATH='$REPO/pylib:$VPYL' '$PY' -m vdp voice rules | grep -q created && VDP_STATE='$VST' PYTHONPATH='$REPO/pylib:$VPYL' '$PY' -m vdp voice rules | grep -q 'already exists'"
cat >> "$VST/own-rules.md" <<'EOF'
EOF
"$PY" - "$VST/own-rules.md" <<'EOF'
import sys
p = sys.argv[1]
s = open(p).read().replace("## All drafts\n", "## All drafts\n\n- Never write \"Hope this helps\".\n- Sign off with nothing,\n  not even a name.\n")
s = s.replace("## Jira\n", "## Jira\n\n- Name the ticket's status first.\n")
open(p, "w").write(s)
EOF
check "voice guide writes rules per audience and purpose, and across them" \
  bash -c "VDP_STATE='$VST' VDP_CLAUDE='$VBIN/claude' PYTHONPATH='$REPO/pylib:$VPYL' '$PY' -m vdp voice guide >/dev/null && jq -e '(.audiences|length)==5 and (.audiences.clients.purposes|has(\"ask\")) and (.combinations|length)==1' '$VST/voice/corpus-guide.json' >/dev/null"
check "the owner's rules come first, word for word, and win; their Jira section is Jira's guide" vpy <<'EOF'
from vdp import guide, state
g = guide.assemble("x")
assert g["own_rules"] == ['Never write "Hope this helps".', "Sign off with nothing, not even a name."], g["own_rules"]
assert g["jira"] == ["Name the ticket's status first."], g["jira"]
t = guide.render(g, state.read_json(state.path("voice", "stats.json")), "clients", ["ask", "status"])
assert t.startswith("self-01's own rules (these win") and "Combining purposes" in t and "When the purpose is ask" in t
j = guide.render(g, {}, "jira", ["status"])
assert "Jira comments" in j and "Writing to" not in j
EOF
check "voice validate drafts each holdout with 3, 5 and 8 exemplars and the judge scores them" \
  bash -c "VDP_STATE='$VST' VDP_CLAUDE='$VBIN/claude' PYTHONPATH='$REPO/pylib:$VPYL' '$PY' -m vdp voice validate >/dev/null && test \$(wc -l < '$VST/validation/drafts.jsonl') = 30 && test \$(wc -l < '$VST/validation/judge.jsonl') = 30"
check "drafts used the closest exemplars of the right count, holdouts never among them" vpy <<'EOF'
import json
from vdp import pool, state, validate
held = pool.held()
for r in state.read_jsonl(state.path("validation", "drafts.jsonl")):
    assert r["text"] == f"draft with {r['k']} examples", r
    assert len(r["exemplars"]) == r["k"] and not held & set(r["exemplars"])
assert validate.best_count() == 5
EOF
check "a rerun of validate sends nothing more" \
  bash -c "VDP_STATE='$VST' VDP_CLAUDE='$VBIN/claude' PYTHONPATH='$REPO/pylib:$VPYL' '$PY' -m vdp voice validate | grep -q '0 of 10 held-back'"
check "the exemplar search fills a thin cell from the same audience" vpy <<'EOF'
import numpy as np
from vdp import validate
ex = [{"id": str(i), "audience": "clients" if i < 4 else "senior", "purposes": ["ask"] if i == 0 else ["status"]}
      for i in range(6)]
m = np.eye(6, dtype="float32")
got = validate.search(ex, m, m[2], "clients", ["ask"], 3)
assert [e["id"] for e in got] == ["0", "2", "1"] or [e["id"] for e in got][0] == "0", got
assert all(e["audience"] == "clients" for e in got)
EOF
check "voice pairs makes 2 blind pairs per audience here (12 where there are enough), the key apart" \
  bash -c "VDP_STATE='$VST' PYTHONPATH='$REPO/pylib:$VPYL' '$PY' -m vdp voice pairs >/dev/null && jq -e '.k==5 and (.pairs|length)==10' '$VST/validation/pairs.json' >/dev/null && jq -e 'length==10' '$VST/validation/pairs-key.json' >/dev/null && ! grep -q '\"real\"' '$VST/validation/pairs.json'"
check "the judge review lists the worst and random drafts once per run" \
  jq -e '.k==5 and (.items|length)==10 and (.items[0].why=="worst")' "$VST/validation/judge-review.json"
check "the pass is worked out from the owner's answers: picks, grades and the per-audience rule" vpy <<'EOF'
from vdp import state, validate
pr = state.read_json(validate.pairs_file())
key = state.read_json(validate.key_file())
for i, p in enumerate(pr["pairs"]):
    pick = "cant" if i % 2 else ("B" if key[p["pair"]] == "A" else "A")
    validate.answer("pair", p["pair"], pick=pick, audience=p["audience"], purposes=p["purposes"])
    validate.answer("pair", p["pair"], grade=4, audience=p["audience"], purposes=p["purposes"])
r = validate.report()
assert r["answered"] == 10 and r["counts"]["all"] == {"cant": 5, "wrong": 5}, r["counts"]
assert r["blind_ok"] and r["grades_ok"] and r["passed"] and not r["more_pairs_for"], r
for p in pr["pairs"]:
    validate.answer("pair", p["pair"], pick=key[p["pair"]])
r = validate.report()
assert not r["blind_ok"] and not r["passed"] and len(r["more_pairs_for"]) == 0, r
assert r["counts"]["aud:clients"]["right"] == 2
lines = [l for l in open(validate.answers_file())]
assert all(set(__import__("json").loads(l)) <= {"run", "kind", "ref", "ts", "pick", "grade", "audience", "purposes"} for l in lines)
for p in pr["pairs"]:
    validate.answer("pair", p["pair"], pick="cant")
validate.answer("pair", pr["pairs"][0]["pair"], grade=1)
assert not validate.report()["grades_ok"]
validate.answer("pair", pr["pairs"][0]["pair"], grade=5)
assert validate.report()["passed"]
EOF
check "voice build: guide, exemplars, stats and build.json in a tarball, leak-checked" \
  bash -c "VDP_STATE='$VST' PYTHONPATH='$REPO/pylib:$VPYL' '$PY' -m vdp voice build >/dev/null && t=\$(ls '$VST'/voice/builds/*/build-*.tar) && tar -tf \"\$t\" | sort | tr '\n' ' ' | grep -q 'voice-runtime/build.json voice-runtime/exemplars.json voice-runtime/guide.json voice-runtime/stats.json'"
check "build.json names the exemplar count and embedding identity" vpy <<'EOF'
import json, tarfile, glob
from vdp import state
t = sorted(glob.glob(state.path("voice", "builds", "*", "build-*.tar")))[-1]
b = json.load(tarfile.open(t).extractfile("voice-runtime/build.json"))
assert b["exemplar_count"] == 5 and b["embedding_identity"]["model"] == "fake-hash" and b["files"]["guide.json"] == 1, b
EOF
check "a real name in a built file stops the build before anything is written" vpy <<'EOF'
import glob, os
from vdp import state, voicebuild
before = len(glob.glob(state.path("voice", "builds", "*")))
p = voicebuild.guide.rules_file()
open(p, "a").write("\n## All drafts\n\n- Copy Robin Madeup and zarnwick on client mail.\n")
try:
    voicebuild.build(log=lambda *a: None)
    raise AssertionError("built")
except SystemExit as e:
    assert "leak check" in str(e), e
r = state.read_json(state.path("voice", "build-leak-report.json"))
assert {t["term"] for t in r["terms"]} >= {"robin madeup", "zarnwick"}, r
assert len(glob.glob(state.path("voice", "builds", "*"))) == before
s = open(p).read().replace("- Copy Robin Madeup and zarnwick on client mail.\n", "")
open(p, "w").write(s)
EOF
check "publish goes through builds-sync's library once the gates pass" vpy <<'EOF'
import os, sys, json
from vdp import state, voicebuild
home = state.path("fake-bs")
os.makedirs(os.path.join(home, "pylib"), exist_ok=True)
open(os.path.join(home, "pylib", "builds_sync.py"), "w").write(
    "BUILDS_SYNC_API = 1\nCALLS = []\ndef publish_build(t, bt):\n"
    "    open(t + '.published', 'w').write(bt)\n    return '/fake/repo'\n")
os.environ["BUILDS_SYNC_HOME"] = home
assert voicebuild.gates() == [], voicebuild.gates()
bt = voicebuild.publish(log=lambda *a: None)
_, tar = voicebuild.newest()
assert open(tar + ".published").read() == bt
EOF
check "publish refuses while validation hasn't passed" vpy <<'EOF'
from vdp import state, validate, voicebuild
pr = state.read_json(validate.pairs_file())
validate.answer("pair", pr["pairs"][0]["pair"], grade=1)
try:
    voicebuild.publish(log=lambda *a: None)
    raise AssertionError("published")
except SystemExit as e:
    assert "validation run 1 hasn't passed (grades failed)" in str(e), e
validate.answer("pair", pr["pairs"][0]["pair"], grade=5)
EOF
RPIDV=$(VDP_STATE="$VST" PYTHONPATH="$REPO/pylib:$VPYL" "$PY" -m vdp review --port 0 --no-browser > "$TMP/vreview.out" 2>&1 & echo $!)
for _ in $(seq 50); do grep -q 'http://127' "$TMP/vreview.out" 2>/dev/null && break; sleep 0.1; done
VURL=$(grep -o 'http://127.0.0.1:[0-9]*/' "$TMP/vreview.out")
vpost(){ curl -s -w '\n%{http_code}' -X POST -H 'Content-Type: application/json' -d "$2" "$VURL$1"; }
check "the review home links the voice build" bash -c "curl -sf '$VURL' | grep -q \"href='/voice'\""
for pg in voice voice/labels voice/disagree voice/pairs voice/judge voice/report; do
  check "the $pg page serves" bash -c "curl -sf '$VURL$pg' | grep -q '<h1>'"
  check "/$pg shows values, not template placeholders" bash -c "curl -sf '$VURL$pg' | '$PY' -c '
import re,sys
h=re.sub(r\"(?s)<(script|style)\\b.*?</\\1>\",\"\",sys.stdin.read())
left=re.findall(r\"\\{[A-Za-z_][^{}<>]*\\}\",h)
sys.exit(\"placeholders: \"+\" \".join(left[:5]) if left else 0)'"
  # Every button that takes a pressed state has a style for it, so a click shows.
  check "every pressable button on /$pg shows when pressed" bash -c "curl -sf '$VURL$pg' | '$PY' -c '
import re,sys
h=sys.stdin.read()
styled=set(re.findall(r\"button\\.([\\w-]+)\\[aria-pressed=true\\]\",h))
bad=[c for c in re.findall(r\"<button class=(\\x27[^\\x27]*\\x27|\\S+)[^>]*aria-pressed\",h)
     if not styled & set(c.strip(\"\\x27\").split())]
sys.exit(1 if bad else 0)'"
done
P1=$(jq -r '.pairs[0].pair' "$VST/validation/pairs.json")
check "a pick is saved at once and tells which side was real" \
  bash -c "out=\$(curl -sf -X POST -H 'Content-Type: application/json' -d '{\"pair\":\"$P1\",\"pick\":\"A\"}' '${VURL}api/voice/pair') && echo \"\$out\" | jq -e '.real==\"A\" or .real==\"B\"' >/dev/null && tail -1 '$VST/validation-answers.jsonl' | jq -e '.ref==\"$P1\" and .pick==\"A\"' >/dev/null"
check "a grade is saved at once" \
  bash -c "curl -sf -X POST -H 'Content-Type: application/json' -d '{\"ref\":\"$P1\",\"grade\":5}' '${VURL}api/voice/pair-grade' >/dev/null && tail -1 '$VST/validation-answers.jsonl' | jq -e '.grade==5' >/dev/null"
check "a label-check verdict is saved" \
  bash -c "I=\$(jq -r '.ids[0]' '$VST/label-check.json'); curl -sf -X POST -H 'Content-Type: application/json' -d \"{\\\"id\\\":\\\"\$I\\\",\\\"verdict\\\":\\\"right\\\"}\" '${VURL}api/voice/label-check' >/dev/null && jq -e --arg i \"\$I\" '.answers[\$i].verdict==\"right\"' '$VST/label-check.json' >/dev/null"
cp "$VST/leak-report.json" "$VST/leak-report.clean.json"
cat > "$VST/leak-report.json" <<'EOF'
{"terms_checked": 3, "undecided_names": 0, "hits": 3, "terms": [{"term": "group.com", "kind": "private URL host", "count": 3, "examples": [{"source": "bitbucket", "id": "x", "text": "group.com.client-01.app"}]}]}
EOF
check "the leak page offers to clear a hit by hand" bash -c "curl -sf '${VURL}leaks' | grep -q 'Cleared by hand</button>'"
check "clearing a hit on the leak page is saved with its count" \
  bash -c "curl -sf -X POST -H 'Content-Type: application/json' -d '{\"term\":\"group.com\",\"cleared\":true}' '${VURL}api/leak-clear' >/dev/null && jq -e '.\"group.com\".count==3' '$VST/leak-cleared.json' >/dev/null"
check "a cleared hit is shown as cleared, with Undo, and the home line says all are cleared" \
  bash -c "curl -sf '${VURL}leaks' | grep -q '<b>cleared by hand</b>' && curl -sf '${VURL}leaks' | grep -q '>Undo</button>' && curl -sf '$VURL' | grep -q 'all cleared by hand'"
check "clearing a term not in the report is refused" \
  test "$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d '{"term":"nothing.example","cleared":true}' "${VURL}api/leak-clear")" = 400
check "Undo takes the mark off" \
  bash -c "curl -sf -X POST -H 'Content-Type: application/json' -d '{\"term\":\"group.com\",\"cleared\":false}' '${VURL}api/leak-clear' >/dev/null && jq -e '.==({})' '$VST/leak-cleared.json' >/dev/null"
cp "$VST/leak-report.clean.json" "$VST/leak-report.json"
check "the voice pages refuse a cross-origin POST" \
  test "$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Origin: http://evil.example' -d '{}' "${VURL}api/voice/pair")" = 403
kill "$RPIDV" 2>/dev/null; wait "$RPIDV" 2>/dev/null
unset FAKE_CLAUDE_COUNT
fi

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
    bash -c "! grep -q -i -e 'Priya' -e 'Raman' -e 'Gregor' -e 'Whitfield' -e 'Alex' -e 'acme' '$ST'/anon/*.jsonl"
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
