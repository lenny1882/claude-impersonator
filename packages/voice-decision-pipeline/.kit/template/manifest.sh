# What this package installs. Sourced by install.sh and uninstall.sh.
#
# This is the command variant: an executable on PATH, optionally with data
# files and hook registrations that call it.

PKG="voice-decision-pipeline"
OWNS="voice-decision-pipeline"

FILES=(
  "bin/voice-decision-pipeline:$HOME/.local/bin/voice-decision-pipeline"
)
DIRS=()
# Other directories uninstall.sh removes. Not for state: uninstall.sh already
# removes the package's state (~/.claude/voice-decision-pipeline/, unless --keep-state) and
# ~/.local/share/voice-decision-pipeline. See reference/layout.md.
STATE_DIRS=()

# EDIT, or delete if nothing calls this from a hook. claude-notify registers
# Notification and Stop hooks that shell out to the installed command.
settings_merge() {
  jq --arg cmd "~/.local/bin/$PKG" '
    .hooks //= {}
    | .hooks.Notification = ((.hooks.Notification // []) + [
        { hooks: [{ type: "command", command: ($cmd + " play notification"), async: true }] }
      ])
  '
}

REGISTRATIONS=(
  "Notification"
)

verify_probe() {
  [ -x "$HOME/.local/bin/$PKG" ] || return 1
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) return 0 ;;
    *) printf '  warn  %s is not on PATH\n' "$HOME/.local/bin"; return 0 ;;
  esac
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
