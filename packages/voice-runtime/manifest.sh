# What this package installs. Sourced by install.sh and uninstall.sh.
#
# This is the skill variant: a directory under ~/.claude/skills, here with an
# executable in ~/.local/bin beside it, as builds-sync and rrc have. Skills
# need no settings.json entry; the sandbox exclusion below is the one.

PKG="voice-runtime"
OWNS="voice-runtime"

# The skill directory (SKILL.md; state/ lives inside it once a build is
# installed), the executable builds-sync and the skill call, and the Python
# module the executable runs, in ~/.local/share/voice-runtime/pylib as the
# pipeline's is. The skill holds no code: the executable is the one place a
# build is read.
DIRS=(
  "skill:$CLAUDE_DIR/skills/voice-runtime"
  "pylib:$HOME/.local/share/voice-runtime/pylib"
)
FILES=(
  "bin/voice-runtime:$HOME/.local/bin/voice-runtime"
)
# Other directories uninstall.sh removes. Not for state: uninstall.sh already
# removes the skill's state/ (unless --keep-state) and ~/.local/share/voice-runtime.
# See reference/layout.md.
STATE_DIRS=()

# ~/.claude is outside Claude Code's Bash sandbox, and save-draft and
# save-final write there from sessions in any repo (PLAN §5), so the command
# is excluded from it, as the pipeline's is.
EXCLUDED=("voice-runtime *")

# Added to whatever the other packages and the user have in
# sandbox.excludedCommands, once, leaving the rest of sandbox alone. Run
# twice, it changes nothing.
settings_merge() {
  jq --argjson ours "$(printf '%s\n' "${EXCLUDED[@]}" | jq -R . | jq -s .)" '
    .sandbox //= {}
    | .sandbox.excludedCommands = (((.sandbox.excludedCommands // []) - $ours) + $ours)
  '
}

REGISTRATIONS=(
  "skills/voice-runtime (no settings entry needed)"
  "sandbox.excludedCommands: ${EXCLUDED[*]}"
)

# The skill is well formed, the command runs and reads the state (status
# needs no build and no embedding-lib), the exclusion is in settings.json,
# and the state, if there is any, is owner-only.
verify_probe() {
  local f="$CLAUDE_DIR/skills/$PKG/SKILL.md" st="$CLAUDE_DIR/skills/$PKG/state"
  [ -f "$f" ] || return 1
  head -1 "$f" | grep -q '^---$' || return 1
  grep -q '^name:' "$f" && grep -q '^description:' "$f" || return 1
  [ -x "$HOME/.local/bin/$PKG" ] || return 1
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) printf '  warn  %s is not on PATH\n' "$HOME/.local/bin" ;;
  esac
  jq -e '.sandbox.excludedCommands | index("voice-runtime *")' \
    "$CLAUDE_DIR/settings.json" >/dev/null || return 1
  if [ -d "$st" ] && [ -n "$(find "$st" -perm /077 -print -quit)" ]; then
    printf '  FAIL  %s holds files or directories that are not owner-only\n' "$st"
    return 1
  fi
  "$HOME/.local/bin/$PKG" status | jq -e 'has("usable")' >/dev/null
}

# drafts.jsonl is live: every draft and the version the owner approved, which
# no build can regenerate (PLAN §3.8). Uninstall refuses while it exists,
# unless --keep-state, so nothing is removed (PLAN §5 Uninstall). The build
# itself is not live: builds-sync installs it again. Then the sandbox
# exclusion is taken out, since uninstall.sh's own settings step only knows
# about hooks; skipped with --keep-settings.
LIVE_FILES=(drafts.jsonl)
pre_uninstall() {
  local st="$CLAUDE_DIR/skills/$PKG/state" f live=()
  if [ "${KEEP_STATE:-0}" != 1 ]; then
    for f in "${LIVE_FILES[@]}"; do [ -e "$st/$f" ] && live+=("$f"); done
    if [ "${#live[@]}" -gt 0 ]; then
      printf '%s holds live files that cannot be rebuilt: %s.\n' "$st" "${live[*]}" >&2
      printf 'Uninstall with --keep-state, or remove them by hand first.\n' >&2
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
# BUILD_OUTPUTS=(bin/voice-runtime)
# build() {
#   go build -ldflags "-X main.version=$1" -o bin/voice-runtime ./cmd/voice-runtime
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
# ~/.local/state/voice-runtime/update_available.log. Skipped when
# KIT_SKIP_MACHINE_HOOKS=1.
# update_available() {
#   notify-send "voice-runtime v$2 is available" "$3" 2>/dev/null || true
# }

# Optional. Run in the background at session start when Claude Code's version
# has changed since last time, with $1 the old version and $2 the new one.
# Output goes to ~/.local/state/voice-runtime/claude_updated.log. Skipped when
# KIT_SKIP_MACHINE_HOOKS=1.
# claude_updated() {
#   systemctl --user restart "$PKG.service" 2>/dev/null || true
# }

# install.sh registers lib/update-check.sh on SessionStart, to show a waiting
# release and run the daily check. Set this to 0 to leave that out.
# UPDATE_NOTICE=0

# Optional. Runs in uninstall.sh before anything is removed, while the files
# are still installed: stop services started from the package's directory.
# Non-zero stops the uninstall with nothing removed. Skipped when
# KIT_SKIP_MACHINE_HOOKS=1 (the tests set it).
# (pre_uninstall is defined above.)

# Optional. Runs in uninstall.sh after everything is removed, to undo a change
# outside $HOME that needs none of the package's files. Skipped when
# KIT_SKIP_MACHINE_HOOKS=1. Non-zero is reported; nothing is put back.
# post_uninstall() {
#   loginctl disable-linger "$USER"
# }
