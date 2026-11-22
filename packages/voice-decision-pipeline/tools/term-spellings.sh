#!/usr/bin/env bash
# Ordinary-word names by rank, with their spellings: for each ranked term
# in the newest ordinary-word-counts run whose rank is in FROM..TO, prints
# one line: rank, pseudonym, the map spellings it matches, occurrences,
# counts by case and labelled items. A term whose matched spellings are all
# several words is left out. Lines run from most labelled items to fewest.
#
#   tools/term-spellings.sh [FROM [TO]]    (default 27 to the last rank)
#
# Prints real spellings from the anonymising map: run it in a terminal of
# your own, never through a tool that passes the terminal's output on. The
# log gets the range and counts of what was printed, never a spelling:
# $VDP_LOG_DIR (default /tmp)/vdp-term-spellings.log, appended under a
# dated header. Reads the map and the counts log, writes nothing else.
set -euo pipefail

FROM=${1:-27}
TO=${2:-999999}
DIR=${VDP_LOG_DIR:-/tmp}
STATE=${VDP_STATE:-${CLAUDE_DIR:-$HOME/.claude}/voice-decision-pipeline}
MAP=$STATE/anonymising-map.json
COUNTS=$DIR/vdp-ordinary-word-counts.log
LOG=$DIR/vdp-term-spellings.log

touch "$LOG" && chmod 600 "$LOG"
log() { printf '%s\n' "$1" >>"$LOG"; }
log "== vdp term spellings, $(date +%Y-%m-%dT%H:%M:%S%z), ranks $FROM to $TO"
fail() { echo "term-spellings: $1" >&2; log "  FAIL  $1"; exit 1; }

[ -r "$MAP" ] || fail "no anonymising map at $MAP"
[ -r "$COUNTS" ] || fail "no counts log at $COUNTS: run tools/ordinary-word-counts.py first"

# The newest run's ranked rows, as: rank pseudonym tN occ lower cap upper
# mixed lower% labelled places. The origin column can be empty, so the row
# is read by its | groups.
run=$(grep '^== ' "$COUNTS" | tail -1)
rows=$(awk -v f="$FROM" -v t="$TO" '
  /^== / { b = ""; r = 0 }
  /ranked by occurrences/ { r = 1; next }
  /^$/ { r = 0 }
  r && $1 ~ /^[0-9]+$/ && $1 + 0 >= f && $1 + 0 <= t {
    split($0, g, "|"); nl = split(g[1], L, " "); split(g[2], C, " "); nr = split(g[3], R, " ")
    b = b L[1] " " L[2] " " L[3] " " L[nl] " " C[1] " " C[2] " " C[3] " " C[4] " " R[1] " " R[2] " " (nr >= 3 ? R[3] : "?") "\n" }
  END { printf "%s", b }' "$COUNTS")
[ -n "$rows" ] || fail "no ranked terms from $FROM to $TO in the newest counts run"
awk '$11 == "?" { bad = 1 } END { exit bad }' <<<"$rows" \
  || fail "the newest counts run has no alias places: rerun tools/ordinary-word-counts.py"

# One line a term: rank, pseudonym, spelling, then the counts.
printf '%4s  %-20s %-24s %5s %5s %5s %5s %5s %8s\n' \
  rank pseudonym spelling occ lower cap upper mixed labelled
out=$(jq -rR --slurpfile m "$MAP" '
  def l(n): tostring | (" " * ([n - length, 0] | max)) + .;
  def r(n): tostring | . + (" " * ([n - length, 0] | max));
  ($m[0].entries | map({key: .pseudonym, value: .}) | from_entries) as $by
  | split(" ") as $f | ($by[$f[1]]) as $e
  | (if $e == null then "(shared first name)"
     elif $f[10] == "-" then ($e.first_names // [] | join(" | "))
     else [$f[10] | split(",")[] | tonumber | $e.aliases[. - 1]] | join(" | ") end) as $sp
  # A term whose every matched spelling is several words is left out: it
  # needs no answer.
  | select($e == null or $f[10] == "-"
      or ([$f[10] | split(",")[] | tonumber | $e.aliases[. - 1]
           | [splits("[\\s._-]+") | select(. != "")] | length] | min) < 2)
  | "\($f[0] | l(4))  \($f[1] | r(20)) \($sp | r(24)) \($f[3] | l(5)) \($f[4] | l(5)) \($f[5] | l(5)) \($f[6] | l(5)) \($f[7] | l(5)) \($f[9] | l(8))"
' <<<"$rows")
# Most labelled items first; the rank column keeps the occurrence rank.
[ -z "$out" ] || awk '{ print $NF "\t" $0 }' <<<"$out" | sort -t $'\t' -k1,1nr -s | cut -f2-
shown=$(grep -c . <<<"$out" || true)
nt=$(wc -l <<<"$rows")
np=$(awk '{ print $2 }' <<<"$rows" | sort -u | wc -l)
occ=$(awk '{ s += $4 } END { print s }' <<<"$rows")
log "  counts run: ${run#== }"
log "  $nt terms over $np pseudonyms, $occ occurrences; printed $shown, left out $((nt - shown)) whose spellings are all several words"
log "  ok    finished"
