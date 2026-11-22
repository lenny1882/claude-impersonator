#!/usr/bin/env python3
"""What matching people's names case-sensitively would change.

For every person term in the newest ordinary-word-counts run (a name that
is also an ordinary word), a case-sensitive match replaces an occurrence
only where it is written in the same case as one of the map spellings it
matches. A term whose matched spellings are all several words is left
out, as it stays as it is. From the run's counts by case, one line a
term: rank, pseudonym, map spelling and its case, occurrences, how many
would still be replaced, and how many would no longer be, by case.

Prints real spellings from the anonymising map: run it
in a terminal of your own, never through a tool that passes the terminal's
output on. The log gets every line without the spelling:
$VDP_LOG_DIR (default /tmp)/vdp-case-sensitive-names.log, appended under a
dated header. Reads the map and the counts log, writes nothing else.

Run with the pipeline's own interpreter and pylib:
  PYTHONPATH=~/.local/share/voice-decision-pipeline/pylib \
    ~/.local/share/voice-decision-pipeline/venv/bin/python tools/case-sensitive-names.py
"""

import os
import re
import sys
import time

DIR = os.environ.get("VDP_LOG_DIR") or "/tmp"
LOG = os.path.join(DIR, "vdp-case-sensitive-names.log")
COUNTS = os.path.join(DIR, "vdp-ordinary-word-counts.log")
_logf = open(LOG, "a", encoding="utf-8")
os.chmod(LOG, 0o600)


def log(s, screen=None):
    """screen, when given, goes to the terminal in place of s; the log
    always gets s."""
    print(s if screen is None else screen, flush=True)
    _logf.write(s + "\n")
    _logf.flush()


SHORT = {"lower": "lower", "capital": "cap", "upper": "upper", "mixed": "mixed"}


def row(rank, pseud, spelling, occ, still, gone, bycase):
    """One term's line; the log's copy has the spelling column blanked."""
    def line(sp):
        return f"{rank:>4} {pseud:<18} {sp:<24} {occ:>5} {still:>5} {gone:>5}  {bycase}".rstrip()
    log(line(""), line(spelling))


log(f"== vdp case-sensitive names, {time.strftime('%Y-%m-%dT%H:%M:%S%z')}")

from vdp.anonmap import Map  # noqa: E402

WORD_SPLIT = re.compile(r"[\s\-_.]+")
CASES = ("lower", "capital", "upper", "mixed")   # the counts log's column order


def case_of(s):
    """The same four classes as tools/ordinary-word-counts.py."""
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return "mixed"
    if all(c.islower() for c in letters):
        return "lower"
    if len(letters) > 1 and all(c.isupper() for c in letters):
        return "upper"
    ws = [w for w in WORD_SPLIT.split(s.strip()) if w]
    if all(w[0].isupper() and (w[1:] == "" or w[1:].islower()) for w in ws):
        return "capital"
    return "mixed"


def ranked_rows():
    """The newest run's ranked rows: (rank, pseudonym, kind, occ, counts by
    case, alias places). Rows are read by their | groups, since the origin
    column can be empty."""
    with open(COUNTS, encoding="utf-8") as f:
        text = f.read()
    run = text.split("\n== ")[-1]
    if "ranked by occurrences" not in run:
        raise SystemExit("the newest counts run has no ranked table: rerun tools/ordinary-word-counts.py")
    rows = []
    for line in run.split("ranked by occurrences", 1)[1].splitlines():
        f = line.split()
        if not f or not f[0].isdigit():
            continue
        g = line.split("|")
        left, case, right = g[0].split(), [int(x) for x in g[1].split()], g[2].split()
        if len(right) < 3:
            raise SystemExit("the newest counts run has no alias places: rerun tools/ordinary-word-counts.py")
        rows.append((int(left[0]), left[1], left[3], int(left[-1]), case, right[2]))
    return rows


def main():
    entries = {e["pseudonym"]: e for e in Map.load().entries}
    row("rank", "pseudonym", "spelling (case)", "occ", "still", "gone", "gone by case")
    tot = {"terms": 0, "occ": 0, "still": 0, "no longer": 0, "no spelling": 0, "multi": 0}
    for rank, pseud, kind, occ, case, places in ranked_rows():
        if kind != "person":
            continue
        e = entries.get(pseud)
        if e is not None and places != "-" and all(
                len([w for w in WORD_SPLIT.split(e["aliases"][int(i) - 1]) if w]) > 1
                for i in places.split(",")):
            tot["multi"] += 1      # every spelling is several words: left as it is
            continue
        tot["terms"] += 1
        tot["occ"] += occ
        if e is None:
            spells = []
        elif places != "-":
            spells = [(i, e["aliases"][int(i) - 1]) for i in places.split(",")]
        else:
            # Matched by a first name the person alone has, which the entry
            # keeps apart from its aliases.
            spells = [(f"first name {i}", s) for i, s in enumerate(e.get("first_names") or [], 1)]
        if not spells:
            tot["no spelling"] += occ
            row(rank, pseud, "shared", occ, "-", "-", "")
            continue
        kept = {case_of(s) for _, s in spells}
        still = sum(n for c, n in zip(CASES, case) if c in kept)
        gone = ", ".join(f"{n} {SHORT[c]}" for c, n in zip(CASES, case) if c not in kept and n)
        tot["still"] += still
        tot["no longer"] += occ - still
        row(rank, pseud, " | ".join(f"{s} ({SHORT[case_of(s)]})" for _, s in spells),
            occ, still, occ - still, gone)
    log(f"totals: {tot['terms']} terms, {tot['occ']} occ, {tot['still']} still, "
        f"{tot['no longer']} gone, {tot['no spelling']} shared")
    log(f"left out: {tot['multi']} terms whose spellings are all several words")
    log("ok    finished")


try:
    main()
except SystemExit as e:
    log(f"FAIL  {e}")
    sys.exit(1)
except BaseException as e:
    tb = e.__traceback__
    while tb.tb_next:
        tb = tb.tb_next
    log(f"FAIL  {type(e).__name__} at line {tb.tb_lineno} of {os.path.basename(tb.tb_frame.f_code.co_filename)}")
    sys.exit(1)
