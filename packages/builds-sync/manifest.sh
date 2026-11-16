# What this package installs. Sourced by install.sh and uninstall.sh.
#
# The skill variant with a command and hooks: a directory under
# ~/.claude/skills, the builds-sync command in ~/.local/bin, and SessionStart
# and SessionEnd entries that call it.

PKG="builds-sync"
OWNS="builds-sync"

# A skill directory, with the command copied to ~/.local/bin as
# repo-remote-control-session's rrc is. The library the pipeline and the
# runtimes load is lib/builds_sync.py inside the skill directory.
DIRS=(
  "skill:$CLAUDE_DIR/skills/builds-sync"
)
FILES=(
  "skill/bin/builds-sync:$HOME/.local/bin/builds-sync"
)
# Other directories uninstall.sh removes. Not for state: uninstall.sh already
# removes the skill's state/ (unless --keep-state) and ~/.local/share/builds-sync.
# The clone is not removed: it is wherever setup recorded, outside the package.
STATE_DIRS=()

# The command writes outside the sandbox's writable area (its state, the clone)
# and reaches the network, so it is excluded from the Bash sandbox, as rrc is.
EXCLUDED=("builds-sync *")
SESSION_START_CMD="~/.local/bin/builds-sync hook session-start"
SESSION_END_CMD="~/.local/bin/builds-sync hook session-end"

settings_merge() {
  jq --arg ss "$SESSION_START_CMD" --arg se "$SESSION_END_CMD" \
     --argjson ours "$(printf '%s\n' "${EXCLUDED[@]}" | jq -R . | jq -s .)" '
    .hooks //= {}
    | .hooks.SessionStart = ((.hooks.SessionStart // []) + [
        { matcher: "startup", hooks: [{ type: "command", command: $ss }] }
      ])
    | .hooks.SessionEnd = ((.hooks.SessionEnd // []) + [
        { hooks: [{ type: "command", command: $se }] }
      ])
    | .sandbox //= {}
    | .sandbox.excludedCommands = (((.sandbox.excludedCommands // []) - $ours) + $ours)
  '
}

REGISTRATIONS=(
  "skills/builds-sync"
  "SessionStart (matcher: startup): $SESSION_START_CMD"
  "SessionEnd: $SESSION_END_CMD"
  "sandbox.excludedCommands: ${EXCLUDED[*]}"
)

# Asks once where the clone is (or clones it), and says what is still missing:
# age, age-keygen, the key. --yes skips the question; `builds-sync setup` asks
# later.
post_install() {
  local args=()
  [ "${ASSUME_YES:-0}" -eq 1 ] && args+=(--yes)
  "$HOME/.local/bin/$PKG" setup ${args[@]+"${args[@]}"}
}

verify_probe() {
  local f="$CLAUDE_DIR/skills/$PKG/SKILL.md" s="$CLAUDE_DIR/settings.json"
  [ -f "$f" ] && head -1 "$f" | grep -q '^---$' || return 1
  grep -q '^name:' "$f" && grep -q '^description:' "$f" || return 1
  [ -x "$HOME/.local/bin/$PKG" ] || return 1
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) printf '  warn  %s is not on PATH\n' "$HOME/.local/bin" ;;
  esac
  # The library loads from the install directory and reports its API.
  [ "$("$HOME/.local/bin/$PKG" api 2>/dev/null)" = 1 ] || return 1
  "$HOME/.local/bin/$PKG" --help | grep -q '^usage: builds-sync' || return 1
  jq -e --arg c "$SESSION_START_CMD" '[.hooks.SessionStart[]?.hooks[]?.command] | index($c)' "$s" >/dev/null || return 1
  jq -e --arg c "$SESSION_END_CMD" '[.hooks.SessionEnd[]?.hooks[]?.command] | index($c)' "$s" >/dev/null || return 1
  jq -e '.sandbox.excludedCommands | index("builds-sync *")' "$s" >/dev/null || return 1
  for exe in age age-keygen; do
    command -v "$exe" >/dev/null || printf '  warn  %s is not installed; builds-sync cannot encrypt or decrypt without it\n' "$exe"
  done
}

# Live-file records not yet pushed, or commits left unpushed, exist only on
# this machine; uninstalling would strand them. Refuse unless --keep-state.
pre_uninstall() {
  if [ "${KEEP_STATE:-0}" != 1 ] && [ -x "$HOME/.local/bin/$PKG" ]; then
    local p
    p=$("$HOME/.local/bin/$PKG" pending 2>/dev/null || echo '{}')
    if [ -n "$p" ] && [ "$p" != "{}" ]; then
      printf 'builds-sync has records or commits not yet pushed: %s.\n' "$p" >&2
      printf 'Run builds-sync push first, or uninstall with --keep-state.\n' >&2
      return 1
    fi
  fi
  strip_excluded
}

strip_excluded() {
  local s="$CLAUDE_DIR/settings.json" tmp
  [ "${KEEP_SETTINGS:-0}" = 1 ] && return 0
  [ -f "$s" ] && jq empty "$s" 2>/dev/null || return 0
  jq -e --argjson ours "$(printf '%s\n' "${EXCLUDED[@]}" | jq -R . | jq -s .)" \
    '(.sandbox.excludedCommands // []) | any(. as $e | $ours | index($e))' "$s" >/dev/null || return 0
  cp "$s" "$s.bak-$PKG"
  tmp=$(mktemp)
  jq --argjson ours "$(printf '%s\n' "${EXCLUDED[@]}" | jq -R . | jq -s .)" '
    .sandbox.excludedCommands -= $ours
    | if .sandbox.excludedCommands == [] then del(.sandbox.excludedCommands) else . end
  ' "$s" >"$tmp" && mv "$tmp" "$s"
  printf '  ok    removed %s from sandbox.excludedCommands\n' "${EXCLUDED[*]}"
}

# Optional. Run by the release workflow at the tag, in this directory, with $1
# the version, before the tarball is packed. Each path in BUILD_OUTPUTS is then
# added to the tarball — for files that are generated, not committed. Non-zero
# stops the release.
# BUILD_OUTPUTS=(bin/builds-sync)
# build() {
#   go build -ldflags "-X main.version=$1" -o bin/builds-sync ./cmd/builds-sync
# }

# Optional, both. Changes outside $HOME around a real install. pre_install
# runs before any file is placed — stop services running from the package's
# directory, which a reinstall deletes and copies again; non-zero stops the
# install with nothing placed. post_install runs after the files and settings,
# before verify_probe; non-zero fails the install. Each gets $1: "install" the
# first time, "reinstall" when the package's files were already there. Neither
# runs on --dry-run or when KIT_SKIP_MACHINE_HOOKS=1 (the tests set it). Both
# must be safe to run again.
# pre_install() {
#   [ "$1" = reinstall ] && systemctl --user stop "$PKG.service" 2>/dev/null
#   return 0
# }
# post_install() {
#   loginctl enable-linger "$USER" && systemctl --user restart "$PKG.service"
# }

# Optional. Runs when install.sh stops after pre_install has run, with $1 the
# mode and $2 the reason, so services pre_install stopped are not left down.
# Skipped when KIT_SKIP_MACHINE_HOOKS=1.
# install_failed() {
#   systemctl --user start "$PKG.service" 2>/dev/null || true
# }

# Optional, both. Run by update.sh with $1 the installed version and $2 the
# new one, from the new release's manifest.sh. pre_update runs before the new
# files are unpacked; non-zero stops the update with nothing changed.
# post_update runs after install.sh succeeds; use it to migrate from an older
# version. Skipped with --dry-run and when KIT_SKIP_MACHINE_HOOKS=1.
# pre_update() {
#   systemctl --user stop "$PKG.service" 2>/dev/null || true
# }
# post_update() {
#   case "$1" in 1.*) mv "$CLAUDE_DIR/$PKG/old.conf" "$CLAUDE_DIR/$PKG/new.conf" 2>/dev/null ;; esac
#   return 0
# }

# Optional. Run by lib/update-check.sh check, in the background, once for each
# newly found release, with $1 the installed version, $2 the new one and $3 the
# release URL. It cannot show anything in a session; output goes to
# ~/.local/state/builds-sync/update_available.log. Skipped when
# KIT_SKIP_MACHINE_HOOKS=1.
# update_available() {
#   notify-send "builds-sync v$2 is available" "$3" 2>/dev/null || true
# }

# Optional. Run in the background at session start when Claude Code's version
# has changed since last time, with $1 the old version and $2 the new one.
# Output goes to ~/.local/state/builds-sync/claude_updated.log. Skipped when
# KIT_SKIP_MACHINE_HOOKS=1.
# claude_updated() {
#   systemctl --user restart "$PKG.service" 2>/dev/null || true
# }

# install.sh registers lib/update-check.sh on SessionStart, to show a waiting
# release and run the daily check. Set this to 0 to leave that out.
# UPDATE_NOTICE=0

# Optional. Runs in uninstall.sh after everything is removed, to undo a change
# outside $HOME that needs none of the package's files. Skipped when
# KIT_SKIP_MACHINE_HOOKS=1. Non-zero is reported; nothing is put back.
# post_uninstall() {
#   loginctl disable-linger "$USER"
# }
