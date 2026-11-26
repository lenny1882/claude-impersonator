#!/usr/bin/env bash
# Whether a subagent asked to draft a message for other people loads the
# voice-runtime skill (PLAN §3.6, §8.2). Runs in the monorepo's box
# (test/docker/box.sh), which must be up and logged in.
#
# voice-runtime is installed from this checkout with its own install.sh. No
# build is installed: the test is about the skill loading, and with no build
# the skill reports the voice model unavailable, which is expected here.
#
# Two parts, three runs each. In every run an outer `claude -p` session is
# told to have a general-purpose subagent draft a Slack message; a
# PreToolUse hook logs every tool call with its agent_id.
#   line     the box's ~/.claude/CLAUDE.md holds the §3.6 section. PASS
#            means the subagent itself called the Skill tool on voice-runtime.
#   control  no CLAUDE.md section. Not pass or fail: it reports whether the
#            skill's description alone made the subagent load it, which is
#            what the §3.6 section exists to cover.
#
#   test/docker/box.sh up      (once, from the repo root, then log in)
#   packages/voice-runtime/test/docker/skill-loading.sh [line|control]   (both if none given)
#
# Not covered: whether `/code-review --comment` words its comments through
# the skill. That posts to a real pull request, so it can't run in the box.
#
# About 6 runs of a session with one subagent on the box's logged-in
# account. Puts the box's settings.json and CLAUDE.md back and removes
# voice-runtime at the end.
#
# Where to run it: your own terminal, or ! in Claude Code. Claude's Bash tool
# can't reach the Docker socket.
#
# Logs to test/docker/results/<time>-skill-loading/run.log at the repo root,
# results/latest pointing at it; summary.txt there has one line per check,
# and <part>-<n>-hooks.jsonl every tool call the hook saw in that run.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/../../../../test/docker/lib.sh"
PART=${1:-all}
case $PART in line|control|all) ;; *) echo "usage: $0 [line|control]"; exit 2 ;; esac
start_log skill-loading
need_box

if ! as_dev 'claude auth status' >/dev/null 2>&1; then
  echo "claude isn't logged in in $BOX. In your own terminal:"
  echo "  docker exec -it -u $DEV $BOX bash -lc 'claude auth login'"
  echo "== finished: skill-loading, not run (no login)"
  exit 1
fi
echo "  $(as_dev 'claude --version' | head -1)"

WORK=$H/skill-probe
LOG=$H/skill-probe.jsonl
cleanup() {
  as_dev "[ -f ~/.claude/settings.json.skill-probe ] && mv ~/.claude/settings.json.skill-probe ~/.claude/settings.json
          if [ -f ~/.claude/CLAUDE.md.skill-probe ]; then mv ~/.claude/CLAUDE.md.skill-probe ~/.claude/CLAUDE.md
          elif [ -f ~/.claude/CLAUDE.md.skill-probe-none ]; then rm -f ~/.claude/CLAUDE.md ~/.claude/CLAUDE.md.skill-probe-none; fi
          rm -rf ~/.claude/skills/voice-runtime ~/.local/bin/voice-runtime ~/.local/share/voice-runtime
          rm -rf ~/.local/bin/skill-probe ~/pkg/voice-runtime $WORK $LOG ~/.claude/projects/*skill-probe*" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> setting up: voice-runtime from this checkout, the probe hook on PreToolUse"
as_dev "mkdir -p ~/.claude ~/.local/bin $WORK
        [ -f ~/.claude/settings.json ] || echo '{}' > ~/.claude/settings.json
        cp ~/.claude/settings.json ~/.claude/settings.json.skill-probe
        if [ -f ~/.claude/CLAUDE.md ]; then cp ~/.claude/CLAUDE.md ~/.claude/CLAUDE.md.skill-probe
        else touch ~/.claude/CLAUDE.md.skill-probe-none; fi"
copy_package voice-runtime
if ! as_dev "cd ~/pkg/voice-runtime && ./install.sh --yes" > "$RESULTS/install.log" 2>&1; then
  result FAIL install "voice-runtime's install.sh failed; see install.log"
  echo "== finished: skill-loading, $PASSES passed, $FAILS failed (results in $RESULTS)"
  exit 1
fi
echo "  installed: $(as_dev 'voice-runtime status' 2>&1 | head -1 | cut -c1-120)"
as_dev "cat > ~/.local/bin/skill-probe" <<EOF
#!/usr/bin/env bash
# Logs every PreToolUse input; decides nothing.
cat >> $LOG; printf '\n' >> $LOG
exit 0
EOF
as_dev "chmod +x ~/.local/bin/skill-probe
        jq --arg c \"\$HOME/.local/bin/skill-probe\" \
          '.hooks = {PreToolUse: [{matcher: \"*\", hooks: [{type: \"command\", command: \$c}]}]}' \
          ~/.claude/settings.json > ~/.claude/settings.json.tmp && mv ~/.claude/settings.json.tmp ~/.claude/settings.json"

# The §3.6 section, word for word.
SECTION='# Drafts for other people use the voice skill

Before drafting anything I will send to other people — a Slack message or
reply, a PR description, a PR review comment, a Jira comment, an email —
load the `voice-runtime` skill and draft by it, in the main session and in
subagents alike. For those drafts the skill'"'"'s guide wins over the writing
rules in this file; those rules still govern everything you write to me.'

set_claude_md() { # set_claude_md line|control
  as_dev "if [ -f ~/.claude/CLAUDE.md.skill-probe ]; then cp ~/.claude/CLAUDE.md.skill-probe ~/.claude/CLAUDE.md
          else rm -f ~/.claude/CLAUDE.md; fi"
  if [ "$1" = line ]; then
    printf '\n%s\n' "$SECTION" | as_dev "cat >> ~/.claude/CLAUDE.md"
  fi
}

PROMPT='Use the Agent tool to have a general-purpose subagent draft a Slack message to the project team saying the staging deploy moves from Thursday to Friday because the database migration needs another day of testing. Do not draft it yourself. Reply with the draft the subagent returns.'

skill_calls() { # skill_calls <hooks file> main|sub: count of Skill calls on voice-runtime
  local who='(.agent_id // "") == ""'
  [ "$2" = sub ] && who='(.agent_id // "") != ""'
  grep '^{' "$1" | jq -c "select(.tool_name==\"Skill\" and ((.tool_input | tostring) | test(\"voice-runtime\")) and $who)" 2>/dev/null | wc -l
}

run() { # run <part> <n>
  local f="$RESULTS/$1-$2.jsonl" h="$RESULTS/$1-$2-hooks.jsonl"
  as_dev "rm -f $LOG"
  as_dev "cd $WORK && timeout 600 claude -p --permission-mode bypassPermissions --no-session-persistence \
          --output-format stream-json --verbose '$PROMPT' </dev/null" > "$f" 2>&1
  local rc=$?
  as_dev "cat $LOG 2>/dev/null" > "$h"
  local agent sub main vr
  agent=$(grep '^{' "$h" | jq -c 'select(.tool_name=="Agent" or .tool_name=="Task")' 2>/dev/null | wc -l)
  sub=$(skill_calls "$h" sub); main=$(skill_calls "$h" main)
  vr=$(grep '^{' "$h" | jq -c 'select(.tool_name=="Bash" and (.agent_id // "") != "" and ((.tool_input.command // "") | test("voice-runtime")))' 2>/dev/null | wc -l)
  echo "  $1-$2: exit $rc, subagent launches $agent, Skill voice-runtime: subagent $sub, main $main; subagent voice-runtime commands $vr"
  if [ "$1" = line ]; then
    if [ "$agent" -lt 1 ]; then
      result FAIL "$1-$2" "the main session launched no subagent; see $(basename "$f")"
    elif [ "$sub" -ge 1 ]; then
      result PASS "$1-$2" "the subagent loaded voice-runtime"
    else
      result FAIL "$1-$2" "the subagent didn't load voice-runtime (main loaded it $main times)"
    fi
  else
    echo "  INFO  $1-$2  without the section the subagent loaded voice-runtime $sub times (launches: $agent)" \
      | tee -a "$RESULTS/summary.txt"
  fi
}

for part in line control; do
  [ "$PART" = all ] || [ "$PART" = "$part" ] || continue
  echo "==> $part: CLAUDE.md $( [ $part = line ] && echo 'with' || echo 'without' ) the §3.6 section"
  set_claude_md "$part"
  for n in 1 2 3; do run "$part" "$n"; done
done

echo "== finished: skill-loading, $PASSES passed, $FAILS failed (results in $RESULTS)"
