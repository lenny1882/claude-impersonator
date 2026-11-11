#!/usr/bin/env bash
# Installer for voice-decision-pipeline.
#
#   ./install.sh           install
#   ./install.sh --link    symlink instead of copying, for working on the repo
#   ./install.sh --yes     no prompts
#   ./install.sh --dry-run show what would change to settings.json, write nothing
#
# Re-running is safe and is how you upgrade.
#
# What gets installed is declared in manifest.sh — this file is machinery and
# rarely needs editing.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="$(head -1 "$REPO/VERSION" | tr -d '[:space:]')"
CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
SETTINGS="$CLAUDE_DIR/settings.json"
LIB_DIR="$HOME/.local/share/voice-decision-pipeline"

LINK=0; ASSUME_YES=0; DRY=0
for a in "$@"; do
  case "$a" in
    --link)    LINK=1 ;;
    --yes|-y)  ASSUME_YES=1 ;;
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

say()  { printf '%s\n' "$*"; }
ok()   { printf '  ok    %s\n' "$*"; }
warn() { printf '  warn  %s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }

FILES=(); DIRS=(); STATE_DIRS=(); REGISTRATIONS=()
# shellcheck source=manifest.sh
. "$REPO/manifest.sh"

say "== $PKG v$VERSION"
say "   repo: $REPO"

step "Checking prerequisites"
missing=()
for c in jq; do command -v "$c" >/dev/null 2>&1 || missing+=("$c"); done
if [ "${#missing[@]}" -gt 0 ]; then
  say "  Missing: ${missing[*]} — install and re-run: sudo apt install ${missing[*]}"
  exit 1
fi
ok "jq present"

# GSD's session-start migration deletes any hook whose command contains "gsd-",
# which once made a registration vanish between sessions with no error.
case "$PKG" in
  *gsd-*) warn "the package name contains 'gsd-'. GSD's own session-start migration"
          warn "removes hooks matching that, and the registration will disappear."
          warn "Rename it." ;;
esac

# pre_install and post_install are for changes outside $HOME — stopping the
# package's systemd user services before their files are replaced, then
# loginctl enable-linger and starting them again. Both get MODE as $1:
# "install" when none of this package's files were there, "reinstall" when
# some were (an update, or the same version run again). A dry run never runs
# either. Test harnesses set KIT_SKIP_MACHINE_HOOKS=1, because their installs
# go into a throwaway HOME while these hooks change the real machine.
MODE=install
for entry in ${FILES[@]+"${FILES[@]}"} ${DIRS[@]+"${DIRS[@]}"}; do
  if [ -e "${entry#*:}" ] || [ -L "${entry#*:}" ]; then MODE=reinstall; break; fi
done

# install_failed runs when the install stops after pre_install — a failing
# post_install or verify_probe, a missing file, settings.json that will not
# parse, or any other error. It gets MODE and the reason, so a package can
# restart the services pre_install stopped instead of leaving them down.
# Nothing has changed before this point, so an earlier stop does not call it.
REASON=""; ARMED=0
on_exit() {
  local rc=$1
  trap - EXIT
  if [ "$rc" -ne 0 ] && [ "$ARMED" -eq 1 ] && declare -F install_failed >/dev/null; then
    step "After a failed install"
    if [ "${KIT_SKIP_MACHINE_HOOKS:-0}" = 1 ]; then
      ok "install_failed skipped (KIT_SKIP_MACHINE_HOOKS=1)"
    elif install_failed "$MODE" "${REASON:-install.sh exited with status $rc}"; then
      ok "install_failed"
    else
      warn "install_failed in manifest.sh failed too"
    fi
  fi
  exit "$rc"
}
trap 'on_exit $?' EXIT

if [ "$DRY" -eq 1 ]; then
  for h in pre_install post_install; do
    declare -F "$h" >/dev/null && ok "$h skipped (dry run)"
  done
elif declare -F pre_install >/dev/null; then
  step "Before installing"
  if [ "${KIT_SKIP_MACHINE_HOOKS:-0}" = 1 ]; then
    ok "pre_install skipped (KIT_SKIP_MACHINE_HOOKS=1)"
  elif pre_install "$MODE"; then
    ok "pre_install"
  else
    say "  pre_install in manifest.sh failed — nothing installed."; exit 1
  fi
fi
[ "$DRY" -eq 1 ] || ARMED=1

# A skill keeps its state in state/ inside its installed directory. The rm -rf
# below would delete it on every install and upgrade, so it is set aside first
# and put back after. With --link the directory is the checkout's and state/
# already lives there, ignored by git, so a reinstall over the same link leaves
# it alone.
place() { # place <source> <destination>
  local src="$REPO/$1" dst="$2" keep=""
  [ -e "$src" ] || { warn "missing $src"; return 1; }
  mkdir -p "$(dirname "$dst")"
  if [ -d "$dst/state" ] && [ "$(cd "$dst/state" && pwd -P)" != "$(cd "$src" && pwd -P)/state" ]; then
    keep=$(mktemp -d "$(dirname "$dst")/.$(basename "$dst").state.XXXXXX")
    if [ -L "$dst" ]; then cp -a "$dst/state" "$keep/state"; else mv "$dst/state" "$keep/state"; fi
  fi
  rm -rf "$dst"
  if [ "$LINK" -eq 1 ]; then ln -s "$src" "$dst"; else cp -r "$src" "$dst"; fi
  if [ -n "$keep" ]; then
    rm -rf "$dst/state"; mv "$keep/state" "$dst/state"; rmdir "$keep"
    ok "$dst (state/ kept)"
  else
    ok "$dst"
  fi
}

if [ "$DRY" -eq 0 ]; then
  step "Installing files"
  for entry in ${FILES[@]+"${FILES[@]}"}; do place "${entry%%:*}" "${entry#*:}"; done
  for entry in ${DIRS[@]+"${DIRS[@]}"};  do place "${entry%%:*}" "${entry#*:}"; done
  for entry in ${FILES[@]+"${FILES[@]}"}; do chmod +x "${entry#*:}" 2>/dev/null || true; done
  if [ -f "$REPO/lib/update-check.sh" ]; then
    mkdir -p "$LIB_DIR"; rm -f "$LIB_DIR/update-check.sh"
    if [ "$LINK" -eq 1 ]; then ln -s "$REPO/lib/update-check.sh" "$LIB_DIR/update-check.sh"
    else cp "$REPO/lib/update-check.sh" "$LIB_DIR/update-check.sh"; fi
    chmod +x "$LIB_DIR/update-check.sh"; ok "$LIB_DIR/update-check.sh"
  fi
fi

# A package with releases registers a SessionStart entry that shows the
# release notice the last check found and starts the next check in the
# background (lib/update-check.sh session-start). UPDATE_NOTICE=0 in
# manifest.sh leaves it out.
NOTICE_CMD="~/.local/share/$PKG/update-check.sh session-start"
NOTICE=0
[ -f "$REPO/lib/update-check.sh" ] && [ "${UPDATE_NOTICE:-1}" != 0 ] && NOTICE=1
add_notice() {
  if [ "$NOTICE" -eq 1 ]; then
    jq --arg cmd "$NOTICE_CMD" '
      .hooks //= {}
      | .hooks.SessionStart = ((.hooks.SessionStart // []) + [
          { matcher: "startup", hooks: [{ type: "command", command: $cmd }] }
        ])'
  else cat; fi
}
merge_own() { if declare -F settings_merge >/dev/null; then settings_merge; else cat; fi; }

if declare -F settings_merge >/dev/null || [ "$NOTICE" -eq 1 ] \
   || { [ -f "$SETTINGS" ] && grep -qF "$NOTICE_CMD" "$SETTINGS"; }; then
  step "Merging into $SETTINGS"
  mkdir -p "$(dirname "$SETTINGS")"
  [ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
  jq empty "$SETTINGS" 2>/dev/null || {
    say "  $SETTINGS is not valid JSON — fix it and re-run."
    REASON="settings.json is not valid JSON"; exit 1; }

  # Remove this package's previous entries across every event, then let the
  # manifest add the current ones. That is what makes re-running safe.
  #
  # A single OWNS substring only finds a package's own entries when it installs
  # one script named after the package. A package bundling several hooks needs
  # each script's basename matched too, or a stale entry from whichever script
  # doesn't contain OWNS survives every reinstall instead of being replaced.
  #
  # Each name must stand as a whole word in the command, not merely appear in
  # it. Two packages in one monorepo can share a prefix, and "mono-hook" sits
  # inside ~/.claude/hooks/mono-hook2.sh: a plain substring match would strip
  # the sibling's entry on every reinstall.
  owns_json=$(
    { [ -n "${OWNS:-}" ] && printf '%s\n' "$OWNS"
      for entry in ${FILES[@]+"${FILES[@]}"}; do basename "${entry#*:}"; done
    } | sort -u | jq -R . | jq -s .
  )
  tmp=$(mktemp)
  jq --argjson owns "$owns_json" --arg notice "$NOTICE_CMD" '
    def ours: (.command // "") as $c
      | $c == $notice
        or any($owns[]; gsub("[.]"; "\\.") as $o
          | $c | test("(^|[^A-Za-z0-9_-])" + $o + "($|[^A-Za-z0-9_-])"));
    def strip_ours: map(.hooks |= map(select(ours | not))) | map(select((.hooks | length) > 0));
    if (.hooks | type) == "object" then
      .hooks |= with_entries(
        if (.value | type) == "array" then .value |= strip_ours else . end)
      | .hooks |= with_entries(select((.value | type) != "array" or (.value | length) > 0))
    else . end
  ' "$SETTINGS" | merge_own | add_notice > "$tmp"

  if [ "$DRY" -eq 1 ]; then
    diff <(jq -S . "$SETTINGS") <(jq -S . "$tmp") || true
    rm -f "$tmp"; say; say "(dry run — nothing written)"; exit 0
  elif diff -q "$tmp" "$SETTINGS" >/dev/null 2>&1; then
    rm -f "$tmp"; ok "already up to date"
  else
    cp "$SETTINGS" "$SETTINGS.bak-$PKG"
    mv "$tmp" "$SETTINGS"
    for r in ${REGISTRATIONS[@]+"${REGISTRATIONS[@]}"}; do ok "$r"; done
    if [ "$NOTICE" -eq 1 ]; then ok "SessionStart: the update notice"; fi
    ok "previous settings kept at $SETTINGS.bak-$PKG"
  fi
elif [ "$DRY" -eq 1 ]; then
  say; say "(dry run — this package touches no settings)"; exit 0
fi

if [ -x "$LIB_DIR/update-check.sh" ]; then
  step "Recording the installed version"
  "$LIB_DIR/update-check.sh" record-install "$VERSION" "$REPO"
  ok "v$VERSION, repo at $REPO"
fi

fail=0

if declare -F post_install >/dev/null; then
  step "After installing"
  if [ "${KIT_SKIP_MACHINE_HOOKS:-0}" = 1 ]; then
    ok "post_install skipped (KIT_SKIP_MACHINE_HOOKS=1)"
  elif post_install "$MODE"; then
    ok "post_install"
  else
    warn "post_install in manifest.sh failed — the files are installed, but the step after them is not done"; fail=1
    REASON="post_install failed"
  fi
fi

step "Verifying"
for entry in ${FILES[@]+"${FILES[@]}"} ${DIRS[@]+"${DIRS[@]}"}; do
  [ -e "${entry#*:}" ] && ok "${entry#*:}" || { warn "missing ${entry#*:}"; fail=1; REASON="${REASON:-missing ${entry#*:}}"; }
done
if declare -F verify_probe >/dev/null; then
  if verify_probe; then ok "it does what it is supposed to"
  else warn "the probe in manifest.sh failed — it installed, but does not work"; fail=1
       REASON="${REASON:-verify_probe failed}"; fi
fi

say
if [ "$fail" -eq 0 ]; then
  say "Done. If Claude Code is already running, /hooks forces a settings reload."
else
  say "Finished with problems — see the warnings above."
  exit 1
fi
