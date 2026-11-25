#!/usr/bin/env bash
# Whether Claude Code's auto mode lets a session start a one-off
# `claude -p --no-session-persistence` call from Bash, as the reworked
# voice-runtime drafts (PLAN §5, Reading; §8.6). Runs in the monorepo's box
# (test/docker/box.sh), which must be up and logged in.
#
# Two shapes, three runs each, from an outer `claude -p --permission-mode
# auto` session with the Bash sandbox on:
#   wrapped  a skill runs `voice-probe`, an excluded command that itself
#            runs `claude -p` (the shape voice-runtime will have)
#   direct   a skill runs `claude -p ...` itself from Bash (also excluded, so
#            only the classifier can refuse it)
# PASS means the call ran and returned PROBE-OK; FAIL means it was refused or
# failed, with the reason in the run's own file. It also checks that no
# session file was written, since every call uses --no-session-persistence.
#
#   test/docker/box.sh up      (once, from the repo root, then log in)
#   packages/voice-runtime/test/docker/claude-p-auto.sh
#
# About 12 small model calls on the box's logged-in account. Puts the box's
# settings.json back and removes the skills and the probe command at the end.
#
# Where to run it: your own terminal, or ! in Claude Code. Claude's Bash tool
# can't reach the Docker socket.
#
# Logs to test/docker/results/<time>-claude-p-auto/run.log at the repo root,
# results/latest pointing at it; summary.txt there has one line per check.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/../../../../test/docker/lib.sh"
start_log claude-p-auto
need_box

if ! as_dev 'claude auth status' >/dev/null 2>&1; then
  echo "claude isn't logged in in $BOX. In your own terminal:"
  echo "  docker exec -it -u $DEV $BOX bash -lc 'claude auth login'"
  echo "== finished: claude-p-auto, not run (no login)"
  exit 1
fi
echo "  $(as_dev 'claude --version' | head -1)"

WORK=$H/cp-probe
cleanup() {
  as_dev "[ -f ~/.claude/settings.json.cp-probe ] && mv ~/.claude/settings.json.cp-probe ~/.claude/settings.json
          rm -rf ~/.claude/skills/cp-wrapped ~/.claude/skills/cp-direct ~/.local/bin/voice-probe $WORK
          rm -rf ~/.claude/projects/*cp-probe*" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> setting up: two skills, the probe command, the sandbox with both excluded"
as_dev "mkdir -p ~/.claude ~/.local/bin $WORK ~/.claude/skills/cp-wrapped ~/.claude/skills/cp-direct
        [ -f ~/.claude/settings.json ] || echo '{}' > ~/.claude/settings.json
        cp ~/.claude/settings.json ~/.claude/settings.json.cp-probe
        jq '.sandbox = {enabled: true, allowUnsandboxedCommands: false,
                        excludedCommands: [\"voice-probe\", \"voice-probe *\", \"claude -p *\"]}' \
          ~/.claude/settings.json.cp-probe > ~/.claude/settings.json"
as_dev "cat > ~/.local/bin/voice-probe" <<'EOF'
#!/usr/bin/env bash
# Stands in for voice-runtime's draft step: a one-off model call, no session file.
exec claude -p "Reply with exactly: PROBE-OK" --no-session-persistence --tools "" </dev/null
EOF
as_dev "chmod +x ~/.local/bin/voice-probe"
as_dev "cat > ~/.claude/skills/cp-wrapped/SKILL.md" <<'EOF'
---
name: cp-wrapped
description: Draft a probe message. Use when asked to draft a probe message the wrapped way.
---
Run this exact command with the Bash tool, then report its output word for word:

    voice-probe
EOF
as_dev "cat > ~/.claude/skills/cp-direct/SKILL.md" <<'EOF'
---
name: cp-direct
description: Draft a probe message. Use when asked to draft a probe message the direct way.
---
Run this exact command with the Bash tool, then report its output word for word:

    claude -p "Reply with exactly: PROBE-OK" --no-session-persistence --tools "" </dev/null
EOF
before=$(as_dev 'find ~/.claude/projects -name "*.jsonl" 2>/dev/null | wc -l')

run() { # run <shape> <n>
  local f="$RESULTS/$1-$2.jsonl"
  as_dev "cd $WORK && timeout 300 claude -p --permission-mode auto --no-session-persistence \
          --output-format stream-json --verbose \
          'Use the cp-$1 skill to draft a probe message, the $1 way.' </dev/null" > "$f" 2>&1
  local rc=$?
  if grep -q 'PROBE-OK' <(grep '^{' "$f" | jq -r 'select(.type=="user") | .message.content[]? | select(.type=="tool_result") | .content | if type=="array" then .[].text else . end' 2>/dev/null); then
    result PASS "$1-$2" "the Bash call ran and returned PROBE-OK"
  else
    local why
    why=$(grep '^{' "$f" | jq -r 'select(.type=="user") | .message.content[]? | select(.type=="tool_result") | .content | if type=="array" then .[].text else . end' 2>/dev/null | tr '\n' ' ' | cut -c1-200)
    result FAIL "$1-$2" "not run (exit $rc): ${why:-no tool result; see $(basename "$f")}"
  fi
}

for n in 1 2 3; do
  echo "==> run $n"
  run wrapped "$n"
  run direct "$n"
done

after=$(as_dev 'find ~/.claude/projects -name "*.jsonl" 2>/dev/null | wc -l')
check no-session-file "no session file was written ($before before, $after after)" test "$before" -eq "$after"

echo "== finished: claude-p-auto, $PASSES passed, $FAILS failed (results in $RESULTS)"
