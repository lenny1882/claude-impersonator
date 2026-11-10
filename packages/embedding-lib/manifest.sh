# What this package installs. Sourced by install.sh and uninstall.sh.
#
# This is the command variant: an executable on PATH, optionally with data
# files and hook registrations that call it.

PKG="embedding-lib"
OWNS="embedding-lib"

FILES=(
  "bin/embedding-lib:$HOME/.local/bin/embedding-lib"
)
# The Python module, the lock and the pinned runtime. `embedding-lib setup`
# builds the bundled Python, the venv and the model beside it, in
# ~/.local/share/embedding-lib/, which reinstalls leave alone (only this
# directory is replaced) and uninstall.sh removes.
DIRS=(
  "pylib:$HOME/.local/share/embedding-lib/pylib"
)
# Other directories uninstall.sh removes. Not for state: uninstall.sh already
# removes the package's state (~/.claude/embedding-lib/, unless --keep-state) and
# ~/.local/share/embedding-lib. See reference/layout.md.
STATE_DIRS=()

# No hooks: nothing here runs on a Claude Code event.
REGISTRATIONS=()

# The download (about 1.9 GB: Python, libraries, model) happens here, after
# a prompt unless install.sh was given --yes (James, 10 Nov 2026).
# A reinstall or update that changes no pin downloads nothing.
# Without a terminal and without --yes, setup refuses and says so, and the
# install fails rather than finishing unable to embed.
post_install() {
  local args=()
  [ "${ASSUME_YES:-0}" -eq 1 ] && args+=(--yes)
  "$HOME/.local/bin/$PKG" setup ${args[@]+"${args[@]}"}
}

# The real behaviour: embed two related sentences and one unrelated, check
# the shape, the unit length and that the related pair is closer. The
# installer tests skip post_install (KIT_SKIP_MACHINE_HOOKS=1), so there is
# no environment to probe there; they check the command runs instead.
verify_probe() {
  [ -x "$HOME/.local/bin/$PKG" ] || return 1
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) printf '  warn  %s is not on PATH\n' "$HOME/.local/bin" ;;
  esac
  if [ "${KIT_SKIP_MACHINE_HOOKS:-0}" = 1 ]; then
    "$HOME/.local/bin/$PKG" paths >/dev/null
  else
    "$HOME/.local/bin/$PKG" check
  fi
}

# Optional. Run by the release workflow at the tag, in this directory, with $1
# the version, before the tarball is packed. Each path in BUILD_OUTPUTS is then
# added to the tarball — for files that are generated, not committed. Non-zero
# stops the release.
# BUILD_OUTPUTS=(bin/embedding-lib)
# build() {
#   go build -ldflags "-X main.version=$1" -o bin/embedding-lib ./cmd/embedding-lib
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
# ~/.local/state/embedding-lib/update_available.log. Skipped when
# KIT_SKIP_MACHINE_HOOKS=1.
# update_available() {
#   notify-send "embedding-lib v$2 is available" "$3" 2>/dev/null || true
# }

# Optional. Run in the background at session start when Claude Code's version
# has changed since last time, with $1 the old version and $2 the new one.
# Output goes to ~/.local/state/embedding-lib/claude_updated.log. Skipped when
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
