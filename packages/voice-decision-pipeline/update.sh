#!/usr/bin/env bash
# Update voice-decision-pipeline to its newest release, then re-run the installer.
#
# "Newest" is whatever the release lookup below reports; a draft or a
# pre-release is never offered, no matter how its version number sorts. This
# downloads that release's voice-decision-pipeline.tar.gz asset and extracts it over this
# directory, so it works the same whether you installed from a downloaded
# tarball or a git clone — no git required.
#
#   ./update.sh            check, ask, upgrade, reinstall
#   ./update.sh --check    report what is available and stop
#   ./update.sh --yes      no prompts (the reinstall inherits this)
#
# Any other options are passed straight through to install.sh, so
# `./update.sh --link` upgrades a symlinked development install.
#
# Needs `curl` and `tar`.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="voice-decision-pipeline"
GITHUB_SLUG="lenny1882/claude-impersonator"
TARBALL_NAME="voice-decision-pipeline.tar.gz"
CURL=(curl)

[ -f "$REPO/VERSION" ] || {
  printf '%s does not look like a %s install (no VERSION file).\n' "$REPO" "$PROJECT" >&2
  exit 1
}
CURRENT="$(head -1 "$REPO/VERSION" | tr -d '[:space:]')"

CHECK_ONLY=0; ASSUME_YES=0; PASSTHROUGH=()
for a in "$@"; do
  case "$a" in
    --check)   CHECK_ONLY=1 ;;
    --yes|-y)  ASSUME_YES=1; PASSTHROUGH+=("$a") ;;
    -h|--help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)         PASSTHROUGH+=("$a") ;;
  esac
done

say()  { printf '%s\n' "$*"; }
die()  { printf '%s\n' "$*" >&2; exit 1; }

confirm() {
  [ "$ASSUME_YES" -eq 1 ] && return 0
  local reply
  read -r -p "$1 [Y/n] " reply </dev/tty || return 1
  case "$reply" in [Nn]*) return 1 ;; *) return 0 ;; esac
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

say "== $PROJECT — installed v$CURRENT"
say "   asking github.com/$GITHUB_SLUG for the newest release"

release_lookup || die "$lookup_error"

# sort -V puts 1.10.0 above 1.9.0, which a string comparison gets backwards.
if [ "$latest" = "$CURRENT" ] \
   || [ "$(printf '%s\n%s\n' "$CURRENT" "$latest" | sort -V | tail -1)" = "$CURRENT" ]; then
  say "   already on the newest release (latest: v$latest)"
  exit 0
fi

say
say "   v$latest is available."
[ -n "$rel_url" ] && say "   release notes: $rel_url"
say

if [ "$CHECK_ONLY" -eq 1 ]; then
  say "   --check given; stopping here. Run without it to upgrade."
  exit 0
fi

confirm "   Update now?" || { say "   Left alone."; exit 0; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
asset_url="https://github.com/$GITHUB_SLUG/releases/download/$tag/$TARBALL_NAME"
say "   downloading $TARBALL_NAME (v$latest)"
curl -fsSL -o "$tmp/$TARBALL_NAME" "$asset_url" \
  || die "Could not download $asset_url"

# pre_update and post_update come from the new release's manifest.sh, which
# can know every version before it; the installed one cannot know what comes
# next. Both get the current and the new version. They are skipped with
# --dry-run and when KIT_SKIP_MACHINE_HOOKS=1, as test harnesses set it.
mkdir -p "$tmp/new"
tar -xzf "$tmp/$TARBALL_NAME" -C "$tmp/new" --strip-components=1 \
  || die "Could not unpack $TARBALL_NAME"
[ -f "$tmp/new/manifest.sh" ] || die "$TARBALL_NAME has no manifest.sh"
export CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
manifest_has() { ( FILES=(); DIRS=(); STATE_DIRS=(); REGISTRATIONS=(); . "$1" >/dev/null 2>&1; declare -F "$2" >/dev/null ); }
manifest_run() { local m=$1 h=$2; shift 2; ( FILES=(); DIRS=(); STATE_DIRS=(); REGISTRATIONS=(); . "$m"; "$h" "$@" ); }
run_hooks=1
case " ${PASSTHROUGH[*]-} " in *" --dry-run "*) run_hooks=0 ;; esac

if manifest_has "$tmp/new/manifest.sh" pre_update; then
  if [ "$run_hooks" -eq 0 ]; then say "   pre_update skipped (--dry-run)"
  elif [ "${KIT_SKIP_MACHINE_HOOKS:-0}" = 1 ]; then say "   pre_update skipped (KIT_SKIP_MACHINE_HOOKS=1)"
  elif manifest_run "$tmp/new/manifest.sh" pre_update "$CURRENT" "$latest"; then say "   pre_update ok"
  else die "pre_update in the new release's manifest.sh failed — nothing changed, still at v$CURRENT."; fi
fi

say "   extracting into $REPO"
if ! tar -xzf "$tmp/$TARBALL_NAME" -C "$REPO" --strip-components=1; then
  # pre_update may have stopped services, and install.sh will not run to put
  # them back, so install_failed is called here instead.
  if manifest_has "$tmp/new/manifest.sh" install_failed; then
    if [ "$run_hooks" -eq 0 ]; then say "   install_failed skipped (--dry-run)"
    elif [ "${KIT_SKIP_MACHINE_HOOKS:-0}" = 1 ]; then say "   install_failed skipped (KIT_SKIP_MACHINE_HOOKS=1)"
    elif manifest_run "$tmp/new/manifest.sh" install_failed reinstall "unpacking v$latest failed"; then say "   install_failed ok"
    else say "   install_failed in the new release's manifest.sh failed too"; fi
  fi
  die "Unpacking v$latest into $REPO failed — $REPO may be part old, part new. Re-run ./update.sh."
fi

say "   now at v$latest"
say
say "== Re-running the installer"
"$REPO/install.sh" "${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}" \
  || die "install.sh failed after updating to v$latest — post_update not run."

if manifest_has "$REPO/manifest.sh" post_update; then
  say
  say "== After updating"
  if [ "$run_hooks" -eq 0 ]; then say "   post_update skipped (--dry-run)"
  elif [ "${KIT_SKIP_MACHINE_HOOKS:-0}" = 1 ]; then say "   post_update skipped (KIT_SKIP_MACHINE_HOOKS=1)"
  elif manifest_run "$REPO/manifest.sh" post_update "$CURRENT" "$latest"; then say "   post_update ok"
  else die "post_update in manifest.sh failed — v$latest is installed, but the step after it is not done."; fi
fi
