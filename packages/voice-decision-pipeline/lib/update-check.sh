#!/usr/bin/env bash
# Daily release check for voice-decision-pipeline.
#
# Asks the release lookup below what the newest release is, compares it
# against the version recorded at install time, and writes the answer to a
# state file. It never fetches, never touches the install directory, and never
# installs anything — upgrading is always an explicit `./update.sh`.
#
# A release left as a draft or marked pre-release is never reported, no
# matter how its version number sorts. update.sh downloads that release's
# voice-decision-pipeline.tar.gz asset directly — no git involved, so this works the same
# whether the install came from a git clone or a downloaded tarball.
#
# The check runs at most once per calendar day. Callers should run it in the
# background: a remote that is unreachable, slow, or asking for credentials
# must never hold up a session. `curl` is invoked under `timeout` for exactly
# that reason, and the day stamp is written even when the check fails, so an
# offline machine tries once a day rather than every session.
#
# Needs `curl`.
#
# A package's manifest.sh can define update_available, which check runs once
# for each newly found release, with the installed version, the new one and
# the release URL. See do_check. It can also define claude_updated, which
# claude-check runs when Claude Code's version has changed. See claude_check.
#
# Everything a caller displays comes from the *previous* run's state file. That
# is deliberate: reading a file is instant, whereas waiting on the network is
# not, so the notice you see is at most a day stale and costs nothing to show.
#
#   check [--force]   run today's check if it has not run; silent; ~0.5s
#   badge             "<glyph> vX.Y.Z" if an update is waiting, else nothing
#   notice            two-line plain-text notice, else nothing
#   hook-json         {"systemMessage": "..."} for a hook to emit, else nothing
#   session-start     hook-json, then today's check and claude-check in the
#                     background; what install.sh registers on SessionStart
#   claude-check      run claude_updated if Claude Code's version changed
#   status            installed / available / last checked
#   record-install <version> <repo-dir>    called by install.sh
#   clear             forget what the last check found

set -uo pipefail

PROJECT="voice-decision-pipeline"
DISPLAY_NAME="voice-decision-pipeline"
GITHUB_SLUG="lenny1882/claude-impersonator"
CURL=(timeout 8 curl)

STATE="${XDG_STATE_HOME:-$HOME/.local/state}/$PROJECT"
STAMP="$STATE/last-check"
AVAIL="$STATE/available"
URL_F="$STATE/available-url"
INSTALLED="$STATE/installed"
REPO_F="$STATE/repo-dir"

read_file() { cat "$1" 2>/dev/null | head -1 | tr -d '[:space:]'; }

# True when $2 is a strictly higher version than $1. sort -V orders 1.9.0
# below 1.10.0, which a string comparison would get backwards.
newer_than() {
  [ -n "$2" ] || return 1
  [ "$1" = "$2" ] && return 1
  [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -1)" = "$2" ]
}

# --- release lookup: versions.txt on the versions branch ---------------------
# new-package.sh inserts this for a package in a monorepo. There,
# /releases/latest returns whichever package released last, so the repo's
# release workflow keeps one line per package — "<name> <version>" — in
# versions.txt on the versions branch. It writes a package's line only after
# that release's tarball is uploaded, and never for a pre-release, so the file
# never names a version that cannot be downloaded.
#
# release_lookup sets tag, latest and rel_url, or returns 1 with the reason in
# lookup_error. It runs curl as "${CURL[@]}", so a caller can wrap it in
# `timeout`. VERSIONS_URL can be overridden, which is how tests run it against
# a local file.

VERSIONS_URL="${VERSIONS_URL:-https://raw.githubusercontent.com/$GITHUB_SLUG/versions/versions.txt}"

release_lookup() {
  local list
  tag=""; latest=""; rel_url=""; lookup_error=""

  list=$("${CURL[@]}" -fsSL "$VERSIONS_URL" 2>/dev/null) \
    || { lookup_error="Could not read $VERSIONS_URL — no release published yet, or no network."; return 1; }

  latest=$(printf '%s\n' "$list" | awk -v p="$PROJECT" '$1 == p { print $2; exit }' \
    | grep -E '^[0-9]+(\.[0-9]+)*$') || true
  [ -n "$latest" ] || { lookup_error="$VERSIONS_URL lists no release of $PROJECT yet."; return 1; }

  tag="$PROJECT-v$latest"
  rel_url="https://github.com/$GITHUB_SLUG/releases/tag/$tag"
}

update_pending() {
  local have want
  have=$(read_file "$INSTALLED"); want=$(read_file "$AVAIL")
  [ -n "$have" ] || return 1
  newer_than "$have" "$want"
}

# --- the check itself --------------------------------------------------------

do_check() {
  local repo tag latest rel_url lookup_error
  mkdir -p "$STATE"

  repo=$(read_file "$REPO_F")
  # No recorded install, or it has been moved or deleted: nothing to ask.
  [ -n "$repo" ] && [ -d "$repo" ] || return 0

  # Stamp first. A remote that hangs or refuses should cost one attempt per
  # day, not one per session start.
  date +%F > "$STAMP"

  if ! release_lookup; then
    : > "$AVAIL"; : > "$URL_F"
    return 0
  fi

  local before; before=$(read_file "$AVAIL")
  printf '%s\n' "$latest" > "$AVAIL"
  printf '%s\n' "$rel_url" > "$URL_F"

  # update_available, from the package's manifest.sh, runs once per newly found
  # release: when it is newer than what is installed and differs from what the
  # previous check found. It runs inside this check, which callers run in the
  # background, so it can act but cannot show anything in a session — that is
  # what notice and hook-json are for. Its output goes to update_available.log.
  local have; have=$(read_file "$INSTALLED")
  if newer_than "$have" "$latest" && [ "$latest" != "$before" ]; then
    run_manifest_hook update_available "v$latest found (installed v$have)" "$have" "$latest" "$rel_url"
  fi
}

# Runs a function from the recorded package's manifest.sh, if it defines it,
# logging to $STATE/<hook>.log. A failure is logged, never passed on: this runs
# in the background, where nobody would see it.
run_manifest_hook() { # run_manifest_hook <hook> <log line> <args...>
  local hook=$1 line=$2 repo; shift 2
  [ "${KIT_SKIP_MACHINE_HOOKS:-0}" = 1 ] && return 0
  repo=$(read_file "$REPO_F")
  [ -n "$repo" ] && [ -f "$repo/manifest.sh" ] || return 0
  mkdir -p "$STATE"
  (
    export CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
    FILES=(); DIRS=(); STATE_DIRS=(); REGISTRATIONS=()
    # shellcheck disable=SC1091
    . "$repo/manifest.sh" || exit 0
    declare -F "$hook" >/dev/null || exit 0
    printf '%s  %s\n' "$(date '+%F %T')" "$line"
    if "$hook" "$@"; then echo "  $hook ok"
    else echo "  $hook failed (status $?)"; fi
  ) >> "$STATE/$hook.log" 2>&1
}

# claude_updated, from the package's manifest.sh, runs when the Claude Code
# version differs from the one seen last time, with the old and new versions.
# The first run only records it. Run on every session start, in the
# background: a Claude Code update should not wait for the daily check.
claude_check() {
  command -v claude >/dev/null 2>&1 || return 0
  local now was
  now=$(timeout 10 claude --version 2>/dev/null | head -1 | grep -oE '[0-9]+(\.[0-9]+)+' | head -1)
  [ -n "$now" ] || return 0
  mkdir -p "$STATE"
  was=$(read_file "$STATE/claude-version")
  printf '%s\n' "$now" > "$STATE/claude-version"
  [ -n "$was" ] && [ "$was" != "$now" ] || return 0
  run_manifest_hook claude_updated "Claude Code v$was -> v$now" "$was" "$now"
}

checked_today() {
  [ "$(read_file "$STAMP")" = "$(date +%F)" ]
}

# --- subcommands -------------------------------------------------------------

case "${1:-status}" in
  check)
    if [ "${2:-}" != "--force" ] && checked_today; then exit 0; fi
    do_check
    ;;

  badge)
    update_pending && printf '⬆ v%s' "$(read_file "$AVAIL")"
    ;;

  notice)
    if update_pending; then
      printf '%s: v%s is available (installed: v%s)\n' \
        "$PROJECT" "$(read_file "$AVAIL")" "$(read_file "$INSTALLED")"
      printf '  update with: cd %s && ./update.sh\n' "$(read_file "$REPO_F")"
      url=$(read_file "$URL_F")
      [ -n "$url" ] && printf '  release notes: %s\n' "$url"
    fi
    ;;

  session-start)
    # For a SessionStart hook: print the notice the last check left, then start
    # today's check detached, with every stream closed so the session does not
    # wait on it.
    "$0" hook-json
    ( { "$0" check; "$0" claude-check; } </dev/null >/dev/null 2>&1 & ) </dev/null >/dev/null 2>&1
    ;;

  claude-check)
    claude_check
    ;;

  hook-json)
    if update_pending; then
      msg=$(printf '%s v%s is available (you have v%s). Update: cd %s && ./update.sh' \
        "$DISPLAY_NAME" "$(read_file "$AVAIL")" "$(read_file "$INSTALLED")" "$(read_file "$REPO_F")")
      if command -v jq >/dev/null 2>&1; then
        jq -n --arg m "$msg" '{systemMessage: $m}'
      else
        # Only the message is interpolated and it is built from version strings
        # and a path, so escaping quotes and backslashes covers it.
        printf '{"systemMessage": "%s"}\n' "$(printf '%s' "$msg" | sed 's/\\/\\\\/g; s/"/\\"/g')"
      fi
    fi
    ;;

  status)
    printf '%s\n' "$DISPLAY_NAME"
    printf '  installed:    %s\n' "$(read_file "$INSTALLED" || true)"
    printf '  available:    %s\n' "$(read_file "$AVAIL" | grep . || echo '(none found)')"
    printf '  release url:  %s\n' "$(read_file "$URL_F" | grep . || echo '-')"
    printf '  last checked: %s\n' "$(read_file "$STAMP" | grep . || echo 'never')"
    printf '  repo:         %s\n' "$(read_file "$REPO_F" | grep . || echo '(not recorded)')"
    update_pending && printf '  -> update available, run ./update.sh in the repo\n'
    ;;

  record-install)
    mkdir -p "$STATE"
    printf '%s\n' "${2:?version required}"  > "$INSTALLED"
    printf '%s\n' "${3:?repo dir required}" > "$REPO_F"
    ;;

  clear)
    rm -f "$STAMP" "$AVAIL" "$URL_F"
    ;;

  *)
    printf 'usage: %s {check [--force]|badge|notice|hook-json|session-start|claude-check|status|clear}\n' \
      "$(basename "$0")" >&2
    exit 1
    ;;
esac
exit 0
