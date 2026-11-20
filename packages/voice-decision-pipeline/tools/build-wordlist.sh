#!/usr/bin/env bash
# Builds pylib/vdp/data/words.txt, the English word list Mining uses to tell
# an ordinary word from a name (PLAN §2.3; SCOWL alone).
#
# Source: the SCOWL word lists Debian and Ubuntu ship as wbritish and
# wamerican (/usr/share/dict/british-english and american-english). Only
# entries written all in lower case are kept, so the lists' own proper nouns
# ("London") never make a client name look ordinary; possessives ('s) go.
#
#   packages/voice-decision-pipeline/tools/build-wordlist.sh
#
# Writes words.txt and WORDS-LICENCE.txt, neither committed: both are
# holds words the repo's sanitise hook
# (test/run-tests.sh does it when missing);
# the release workflow runs it through manifest.sh's build(). Logs to
# /tmp/voice-decision-pipeline-build-wordlist.log.
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
OUT="$HERE/pylib/vdp/data"
LOG="${VDP_LOG_DIR:-/tmp}/voice-decision-pipeline-build-wordlist.log"
exec > >(tee "$LOG") 2>&1
echo "== build-wordlist, $(date -Is)"

SRC=(/usr/share/dict/british-english /usr/share/dict/american-english)
for f in "${SRC[@]}"; do
  [ -r "$f" ] || { echo "missing $f: install the wbritish and wamerican packages"; exit 1; }
done
mkdir -p "$OUT"
LC_ALL=C cat "${SRC[@]}" | LC_ALL=C grep -E "^[a-z]+$" | LC_ALL=C sort -u > "$OUT/words.txt"
echo "  ok    words.txt: $(wc -l < "$OUT/words.txt") words"

# SCOWL's licence asks for its notice beside every copy: copied from the
# system's own copyright file at build time, like the list itself.
LIC=/usr/share/doc/wbritish/copyright
[ -r "$LIC" ] || { echo "missing $LIC: install the wbritish package"; exit 1; }
{ printf 'words.txt is built from SCOWL, as shipped in the wbritish and wamerican\npackages, by tools/build-wordlist.sh: lower-case entries only.\n\n'; cat "$LIC"; } > "$OUT/WORDS-LICENCE.txt"
echo "  ok    WORDS-LICENCE.txt"
echo "== finished"
