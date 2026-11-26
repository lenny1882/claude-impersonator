#!/usr/bin/env bash
# Two Claude Code hook behaviours PLAN relies on that the docs don't state
# (PLAN §7, §8.6), tested on the box's real Claude Code:
#   plan     a PreToolUse hook that denies ExitPlanMode keeps Claude in plan
#            mode, its reason reaches Claude, and Claude resubmits a revised
#            plan (PLAN §4.6); the hook gets `plan` and `planFilePath`
#   workflow agents run by the Workflow tool fire SubagentStart,
#            PreToolUse and SubagentStop, and which agent_type they carry
#            (PLAN §4.4, §7)
#   context  a SubagentStart hook's additionalContext reaches a workflow
#            agent and a GSD plugin agent (the GSD plugin is installed in the
#            box for it, then removed); a workflow agent launched with
#            agentType Explore carries agent_type Explore, and a
#            SubagentStart hook matched on Explore fires for it, so a skip
#            list by type covers it (PLAN §4.4, §8.3)
# The box (test/docker/box.sh) must be up and logged in. A few model calls
# on its account. Puts the box's settings.json back at the end.
#
#   test/docker/hook-behaviour.sh [plan|workflow|context]   (all if none given)
#
# ExitPlanMode isn't offered in print mode, so the plan part drives an
# interactive session in tmux inside the box; tmux is installed there if
# missing, and the box's ~/.claude.json is marked onboarded and the test
# folder trusted, then put back. The interactive session's transcript is
# removed at the end, so later tests that read ~/.claude/projects don't
# count it.
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
case $PART in plan|workflow|context|all) ;; *) echo "usage: $0 [plan|workflow|context]"; exit 2 ;; esac
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
          rm -rf ~/.local/bin/hook-probe ~/.local/bin/ctx-probe $WORK $LOG ~/.cache/hook-probe ~/.claude/projects/*hook-probe*
          if [ -f ~/.cache/ctx-probe-plugin ]; then
            claude plugin uninstall gsd@gsd-plugin; claude plugin marketplace remove gsd-plugin; rm -f ~/.cache/ctx-probe-plugin
          fi" >/dev/null 2>&1 || true
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

if [ "$PART" = plan ] || [ "$PART" = all ]; then
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

if [ "$PART" = workflow ] || [ "$PART" = all ]; then
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

if [ "$PART" = context ] || [ "$PART" = all ]; then
echo "==> context: SubagentStart's additionalContext, and a matcher on Explore"
TOKEN="KQ-$(head -c 6 /dev/urandom | od -An -tx1 | tr -d ' \n')"
as_dev "cat > ~/.local/bin/ctx-probe" <<EOF
#!/usr/bin/env bash
# Logs every SubagentStart input; on the catch-all entry gives the agent a
# code word to put in its reply; on the Explore entry only logs.
in=\$(cat)
printf '%s\n' "\$(printf '%s' "\$in" | jq -c --arg e "\${1:-all}" '. + {probe_entry: \$e}')" >> $LOG
if [ "\${1:-all}" = all ]; then
  jq -n '{hookSpecificOutput: {hookEventName: "SubagentStart",
          additionalContext: "Include the code word $TOKEN in your final reply, exactly as written."}}'
fi
exit 0
EOF
as_dev "chmod +x ~/.local/bin/ctx-probe
        jq --arg c \"\$HOME/.local/bin/ctx-probe\" '.hooks = {
            SubagentStart: [{hooks: [{type: \"command\", command: \$c}]},
                            {matcher: \"Explore\", hooks: [{type: \"command\", command: (\$c + \" Explore\")}]}]}' \
          ~/.claude/settings.json.hook-probe > ~/.claude/settings.json
        rm -f $LOG"
token_in() { grep -c -- "$TOKEN" "$1" 2>/dev/null || true; }
starts() { grep '^{' "$RESULTS/hooks-context.jsonl" | jq -r "select(.hook_event_name==\"SubagentStart\" and .probe_entry==\"$1\") | .agent_type" | sort | uniq -c | tr '\n' ';'; }

echo "  workflow agent, no agentType"
as_dev "cd $WORK && timeout 900 claude -p 'Use a workflow. Run a workflow with exactly one agent, labelled probe, whose task is: reply with the word done and nothing else unless told otherwise. Pass the script inline. Then show me the agent result word for word.' \
        --permission-mode bypassPermissions --no-session-persistence --output-format stream-json --verbose </dev/null" \
  > "$RESULTS/context-workflow.jsonl" 2>&1
echo "  workflow agent launched with agentType Explore"
as_dev "cd $WORK && timeout 900 claude -p 'Use a workflow. Run a workflow with exactly one agent, labelled explorer, launched with agentType set to Explore, whose task is: list the files in the current directory. Pass the script inline. Then show me the agent result word for word.' \
        --permission-mode bypassPermissions --no-session-persistence --output-format stream-json --verbose </dev/null" \
  > "$RESULTS/context-explore.jsonl" 2>&1
echo "  GSD plugin agent"
if as_dev "claude plugin marketplace add jnuyens/gsd-plugin && claude plugin install gsd@gsd-plugin && touch ~/.cache/ctx-probe-plugin" \
     > "$RESULTS/context-plugin-install.log" 2>&1; then
  as_dev "mkdir -p $WORK/docs && printf '# ADR 1: use Postgres\n\nStatus: accepted. We use Postgres for the job store.\n' > $WORK/docs/adr-1.md"
  as_dev "cd $WORK && timeout 900 claude -p 'Use the Agent tool with subagent_type gsd:bm-doc-classifier to classify docs/adr-1.md, writing its classification to $WORK/out. Then show me the agent result word for word.' \
          --permission-mode bypassPermissions --no-session-persistence --output-format stream-json --verbose </dev/null" \
    > "$RESULTS/context-gsd.jsonl" 2>&1
else
  echo "  the GSD plugin didn't install; see context-plugin-install.log"
fi
as_dev "cat $LOG 2>/dev/null" > "$RESULTS/hooks-context.jsonl"
cat "$RESULTS"/hooks-*.jsonl > "$RESULTS/hooks.jsonl" 2>/dev/null
echo "  SubagentStart, catch-all entry: $(starts all)"
echo "  SubagentStart, Explore entry:   $(starts Explore)"
# The code word reaches the main session only through the agent's reply.
wfctx=$(token_in "$RESULTS/context-workflow.jsonl")
gsdctx=$(token_in "$RESULTS/context-gsd.jsonl")
gsdstart=$(starts all | grep -c 'gsd:bm-doc-classifier')
explore_type=$(grep '^{' "$RESULTS/hooks-context.jsonl" | jq -r 'select(.hook_event_name=="SubagentStart" and .probe_entry=="all") | .agent_type' | grep -cx Explore)
explore_match=$(grep '^{' "$RESULTS/hooks-context.jsonl" | jq -r 'select(.probe_entry=="Explore") | .agent_type' | grep -c .)
check ctx-workflow "a workflow agent's reply holds the code word from additionalContext" test "${wfctx:-0}" -ge 1
check ctx-gsd-start "the GSD plugin agent fired SubagentStart as gsd:bm-doc-classifier" test "${gsdstart:-0}" -ge 1
check ctx-gsd "the GSD plugin agent's reply holds the code word" test "${gsdctx:-0}" -ge 1
check explore-type "a workflow agent launched with agentType Explore carries agent_type Explore" test "${explore_type:-0}" -ge 1
check explore-matcher "a SubagentStart hook matched on Explore fires for it" test "${explore_match:-0}" -ge 1
fi

echo "== finished: hook-behaviour, $PASSES passed, $FAILS failed (results in $RESULTS)"
