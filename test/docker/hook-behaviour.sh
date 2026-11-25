#!/usr/bin/env bash
# Two Claude Code hook behaviours PLAN relies on that the docs don't state
# (PLAN §7, §8.6), tested on the box's real Claude Code:
#   plan     a PreToolUse hook that denies ExitPlanMode keeps Claude in plan
#            mode, its reason reaches Claude, and Claude resubmits a revised
#            plan (PLAN §4.6); the hook gets `plan` and `planFilePath`
#   workflow agents run by the Workflow tool fire SubagentStart,
#            PreToolUse and SubagentStop, and which agent_type they carry
#            (PLAN §4.4, §7)
# The box (test/docker/box.sh) must be up and logged in. A few model calls
# on its account. Puts the box's settings.json back at the end.
#
#   test/docker/hook-behaviour.sh [plan|workflow]   (both if none given)
#
# ExitPlanMode isn't offered in print mode, so the plan part drives an
# interactive session in tmux inside the box; tmux is installed there if
# missing, and the box's ~/.claude.json is marked onboarded and the test
# folder trusted, then put back.
#
# Where to run it: your own terminal, or ! in Claude Code. Claude's Bash tool
# can't reach the Docker socket.
#
# Logs to test/docker/results/<time>-hook-behaviour/run.log, results/latest
# pointing at it; summary.txt there has one line per check, and hooks.jsonl
# every hook input the probe saw.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/lib.sh"
PART=${1:-all}
case $PART in plan|workflow|all) ;; *) echo "usage: $0 [plan|workflow]"; exit 2 ;; esac
start_log hook-behaviour
need_box

if ! as_dev 'claude auth status' >/dev/null 2>&1; then
  echo "claude isn't logged in in $BOX. In your own terminal:"
  echo "  docker exec -it -u $DEV $BOX bash -lc 'claude auth login'"
  echo "== finished: hook-behaviour, not run (no login)"
  exit 1
fi
echo "  $(as_dev 'claude --version' | head -1)"

WORK=$H/hook-probe
LOG=$H/hook-probe.jsonl
cleanup() {
  as_dev "tmux -L hookprobe kill-server 2>/dev/null
          [ -f ~/.claude.json.hook-probe ] && mv ~/.claude.json.hook-probe ~/.claude.json
          [ -f ~/.claude/settings.json.hook-probe ] && mv ~/.claude/settings.json.hook-probe ~/.claude/settings.json
          rm -rf ~/.local/bin/hook-probe $WORK $LOG ~/.cache/hook-probe" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> setting up: the probe hook on SubagentStart, PreToolUse and SubagentStop"
as_dev "mkdir -p ~/.claude ~/.local/bin $WORK ~/.cache/hook-probe && rm -f $LOG ~/.cache/hook-probe/*
        [ -f ~/.claude/settings.json ] || echo '{}' > ~/.claude/settings.json
        cp ~/.claude/settings.json ~/.claude/settings.json.hook-probe"
as_dev "cat > ~/.local/bin/hook-probe" <<EOF
#!/usr/bin/env bash
# Logs every hook input; denies the first ExitPlanMode, allows the next.
in=\$(cat)
printf '%s\n' "\$in" >> $LOG
tool=\$(printf '%s' "\$in" | jq -r '.tool_name // empty')
if [ "\$tool" = ExitPlanMode ]; then
  if [ ! -e ~/.cache/hook-probe/denied ]; then
    touch ~/.cache/hook-probe/denied
    jq -n '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny",
            permissionDecisionReason: "Add a final line to the plan reading exactly REVISED-PLAN, then call ExitPlanMode again."}}'
  else
    jq -n '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "allow"}}'
  fi
fi
exit 0
EOF
as_dev "chmod +x ~/.local/bin/hook-probe
        jq --arg c \"\$HOME/.local/bin/hook-probe\" '.hooks = {
            SubagentStart: [{hooks: [{type: \"command\", command: \$c}]}],
            SubagentStop:  [{hooks: [{type: \"command\", command: \$c}]}],
            PreToolUse:    [{matcher: \"*\", hooks: [{type: \"command\", command: \$c}]}]}' \
          ~/.claude/settings.json.hook-probe > ~/.claude/settings.json"

if [ "$PART" != workflow ]; then
echo "==> plan: an interactive session in tmux; the hook denies the first ExitPlanMode"
in_box "command -v tmux >/dev/null || { apt-get update -qq && apt-get install -y -qq tmux >/dev/null; }"
as_dev "cp ~/.claude.json ~/.claude.json.hook-probe 2>/dev/null || echo '{}' > ~/.claude.json.hook-probe
        jq --arg d $WORK '.hasCompletedOnboarding = true | .projects[\$d].hasTrustDialogAccepted = true' \
          ~/.claude.json.hook-probe > ~/.claude.json
        rm -f $LOG ~/.cache/hook-probe/denied
        tmux -L hookprobe new-session -d -s plan -x 200 -y 50 -c $WORK \
          \"claude --permission-mode plan 'Plan how to create a file hello.txt containing the word hi in this directory. Write a short plan, then call ExitPlanMode. If it is rejected, do what the reason says and call ExitPlanMode again.'\""
for _ in $(seq 1 100); do
  c=$(as_dev "grep -cE '\"tool_name\": ?\"ExitPlanMode\"' $LOG 2>/dev/null" || true)
  [ "${c:-0}" -ge 2 ] && break
  sleep 3
done
as_dev "tmux -L hookprobe capture-pane -p -t plan -S -200" > "$RESULTS/plan-pane.txt" 2>&1
as_dev "tmux -L hookprobe kill-server" >/dev/null 2>&1
as_dev "cat $LOG 2>/dev/null" > "$RESULTS/hooks-plan.jsonl"
epm() { grep '^{' "$RESULTS/hooks-plan.jsonl" | jq -c 'select(.hook_event_name=="PreToolUse" and .tool_name=="ExitPlanMode")'; }
n=$(epm | wc -l)
fields=$(epm | head -1 | jq -r '(.tool_input.plan | type == "string" and length > 0) and (.tool_input.planFilePath | type == "string")' 2>/dev/null)
revised=$(epm | sed -n 2p | jq -r '.tool_input.plan // empty' 2>/dev/null | grep -c REVISED-PLAN)
check plan-fields "the hook got the plan text and planFilePath" test "$fields" = true
check plan-resubmit "after the deny Claude called ExitPlanMode again ($n calls)" test "$n" -ge 2
check plan-reason "the second plan follows the deny reason (REVISED-PLAN)" test "$revised" -ge 1
fi

if [ "$PART" != plan ]; then
echo "==> workflow: one workflow agent running Bash"
as_dev "rm -f $LOG"
as_dev "cd $WORK && timeout 900 claude -p 'Use a workflow. Run a workflow with exactly one agent, labelled probe, whose task is: run the shell command true with the Bash tool, then reply done. Pass the script inline.' \
        --permission-mode bypassPermissions --no-session-persistence --output-format stream-json --verbose </dev/null" \
  > "$RESULTS/workflow.jsonl" 2>&1
as_dev "cat $LOG 2>/dev/null" > "$RESULTS/hooks-workflow.jsonl"
cat "$RESULTS"/hooks-*.jsonl > "$RESULTS/hooks.jsonl" 2>/dev/null
ev() { grep '^{' "$RESULTS/hooks-workflow.jsonl" | jq -r "select(.hook_event_name==\"$1\") | (.agent_type // \"-\")" | sort -u | tr '\n' ' '; }
used=$(grep '^{' "$RESULTS/workflow.jsonl" | jq -r 'select(.type=="assistant") | .message.content[]? | select(.type=="tool_use") | .name' | sort -u | tr '\n' ' ')
echo "  tools the main session used: $used"
echo "  agent_type on SubagentStart: $(ev SubagentStart)"
echo "  agent_type on PreToolUse:    $(ev PreToolUse)"
echo "  agent_type on SubagentStop:  $(ev SubagentStop)"
wfused=$(printf '%s' "$used" | grep -cw Workflow)
starts=$(ev SubagentStart | tr -d ' -'); stops=$(ev SubagentStop | tr -d ' -')
agentbash=$(grep '^{' "$RESULTS/hooks-workflow.jsonl" | jq -c 'select(.hook_event_name=="PreToolUse" and .tool_name=="Bash" and (.agent_type // "") != "")' 2>/dev/null | wc -l)
check workflow-ran "the main session used the Workflow tool" test "$wfused" -ge 1
check wf-start "a workflow agent fired SubagentStart" test -n "$starts"
check wf-pretool "a workflow agent fired PreToolUse on Bash, with an agent_type" test "$agentbash" -ge 1
check wf-stop "a workflow agent fired SubagentStop" test -n "$stops"
fi

echo "== finished: hook-behaviour, $PASSES passed, $FAILS failed (results in $RESULTS)"
