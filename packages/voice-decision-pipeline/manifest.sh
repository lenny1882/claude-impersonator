# What this package installs. Sourced by install.sh and uninstall.sh.
#
# This is the command variant: an executable on PATH, optionally with data
# files and hook registrations that call it.

PKG="voice-decision-pipeline"
OWNS="voice-decision-pipeline"

FILES=(
  "bin/voice-decision-pipeline:$HOME/.local/bin/voice-decision-pipeline"
)
# The Python package and the lock. `voice-decision-pipeline setup` builds the
# venv beside it, in ~/.local/share/voice-decision-pipeline/, which
# reinstalls leave alone (only this directory is replaced) and uninstall.sh
# removes.
DIRS=(
  "pylib:$HOME/.local/share/voice-decision-pipeline/pylib"
)
STATE_DIRS=()

# ~/.claude is outside Claude Code's Bash sandbox, so the pipeline's
# commands are excluded from it (PLAN §2.2).
EXCLUDED=("voice-decision-pipeline *")

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
  "sandbox.excludedCommands: ${EXCLUDED[*]}"
)

# The venv download (about 1.8 GB: spaCy, en_core_web_trf and its CPU
# PyTorch) happens here, after a prompt unless install.sh was given --yes,
# as embedding-lib's does. embedding-lib has to be installed and set up
# first; setup says so if it isn't.
post_install() {
  local args=()
  [ "${ASSUME_YES:-0}" -eq 1 ] && args+=(--yes)
  "$HOME/.local/bin/$PKG" setup ${args[@]+"${args[@]}"}
}

# The real behaviour: spaCy finds both names in a made-up sentence, and the
# state directory, if it exists, is owner-only (PLAN §2.2). The installer
# tests skip post_install (KIT_SKIP_MACHINE_HOOKS=1), so there is no venv to
# probe there; they check the command runs instead.
verify_probe() {
  [ -x "$HOME/.local/bin/$PKG" ] || return 1
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) printf '  warn  %s is not on PATH\n' "$HOME/.local/bin" ;;
  esac
  jq -e '.sandbox.excludedCommands | index("voice-decision-pipeline *")' \
    "$CLAUDE_DIR/settings.json" >/dev/null || return 1
  local st="$CLAUDE_DIR/$PKG"
  if [ -d "$st" ] && [ -n "$(find "$st" -perm /077 -print -quit)" ]; then
    printf '  FAIL  %s holds files or directories that are not owner-only\n' "$st"
    return 1
  fi
  if [ "${KIT_SKIP_MACHINE_HOOKS:-0}" = 1 ]; then
    "$HOME/.local/bin/$PKG" paths >/dev/null
  else
    "$HOME/.local/bin/$PKG" check
  fi
}

# Live files can't be rebuilt from the sources: the anonymising map (whose
# numbers must never be reused), James's mining and batch decisions, and the
# inputs with his forget and pick-repos changes. Uninstall refuses while any
# exists, unless --keep-state, so nothing is removed (James, 9 Nov 2026).
# Then the sandbox exclusion is taken out: uninstall.sh's own settings step
# only knows about hooks, and a stale entry would let any later program of
# that name run unsandboxed. Skipped with --keep-settings.
LIVE_FILES=(anonymising-map.json mining-decisions.json review-state.json inputs.json)
pre_uninstall() {
  local st="$CLAUDE_DIR/$PKG" f live=()
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
# BUILD_OUTPUTS=(bin/voice-decision-pipeline)
# build() {
#   go build -ldflags "-X main.version=$1" -o bin/voice-decision-pipeline ./cmd/voice-decision-pipeline
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
# ~/.local/state/voice-decision-pipeline/update_available.log. Skipped when
# KIT_SKIP_MACHINE_HOOKS=1.
# update_available() {
#   notify-send "voice-decision-pipeline v$2 is available" "$3" 2>/dev/null || true
# }

# Optional. Run in the background at session start when Claude Code's version
# has changed since last time, with $1 the old version and $2 the new one.
# Output goes to ~/.local/state/voice-decision-pipeline/claude_updated.log. Skipped when
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
# pre_uninstall() {
#   systemctl --user stop "$PKG.service" 2>/dev/null || true
# }

# Optional. Runs in uninstall.sh after everything is removed, to undo a change
# outside $HOME that needs none of the package's files. Skipped when
# KIT_SKIP_MACHINE_HOOKS=1. Non-zero is reported; nothing is put back.
# post_uninstall() {
#   loginctl disable-linger "$USER"
# }
