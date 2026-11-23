#!/usr/bin/env python3
"""Examples of ordinary-word names, as a local page to read in a browser.

Two sections:
- for each pseudonym given, a sample of the places the anonymiser replaces
  its ordinary-word spellings, with the text around each, word marked;
- the fields spaCy never tags (repo, channel and reaction names, other
  source fields): per field, its distinct values that hold an ordinary-word
  name, most frequent first, with the pseudonym each would get.

The page holds real text. It is written to
$VDP_LOG_DIR (default /tmp)/vdp-ordinary-word-examples.html, readable by
you alone, and opened from disk: nothing serves or sends it. Never pass it
or this script's terminal output through a tool. The log gets counts only:
$VDP_LOG_DIR/vdp-ordinary-word-examples.log, appended under a dated header.
Reads the pipeline's state and writes nothing there.

Run with the pipeline's own interpreter and pylib:
  PYTHONPATH=~/.local/share/voice-decision-pipeline/pylib \\
    ~/.local/share/voice-decision-pipeline/venv/bin/python tools/ordinary-word-examples.py \\
    [--sample N] [--values N] PSEUDONYM...
"""

import argparse
import html
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict

DIR = os.environ.get("VDP_LOG_DIR") or "/tmp"
LOG = os.path.join(DIR, "vdp-ordinary-word-examples.log")
OUT = os.path.join(DIR, "vdp-ordinary-word-examples.html")
_logf = open(LOG, "a", encoding="utf-8")
os.chmod(LOG, 0o600)


def log(s=""):
    print(s, flush=True)
    _logf.write(s + "\n")
    _logf.flush()


log(f"== vdp ordinary-word examples, {time.strftime('%Y-%m-%dT%H:%M:%S%z')}")

from vdp import SOURCES, inputs, state  # noqa: E402
from vdp.anonmap import Map  # noqa: E402
from vdp.anonymise import SENT_FIELDS_NER, Ner, Replacer, dictionary  # noqa: E402
from vdp.review import page  # noqa: E402

NAME_KINDS = {"person", "client", "product"}
WORD_SPLIT = re.compile(r"[\s\-_.]+")
CONTEXT = 100
PROGRESS = 5000                  # records between progress lines


def ordinary(s, words):
    ws = [w for w in WORD_SPLIT.split(s.strip()) if w]
    return bool(ws) and all(w.lower() in words for w in ws)


def untagged_strings(r, rep):
    """(field, string) for the strings the anonymiser rewrites that spaCy
    never tags: source fields other than the tagged ones (keys too, under
    their parent field's name) and reaction names. Same walk as
    tools/ordinary-word-counts.py."""
    def walk(v):
        if isinstance(v, str):
            yield v
        elif isinstance(v, list):
            for x in v:
                yield from walk(x)
        elif isinstance(v, dict):
            for k, x in v.items():
                if isinstance(k, str):
                    yield k
                yield from walk(x)
    for k, v in (r.get("source_fields") or {}).items():
        if k in SENT_FIELDS_NER or k in ("slack_ts", "thread_ts"):
            continue
        if k in ("repo", "cwd", "repo_name", "project"):
            v = os.path.basename(str(v or "").rstrip("/"))
        for s in walk(v):
            yield k, rep.group_dm_name(s)
    for x in r.get("reactions") or []:
        if isinstance(x.get("name"), str):
            yield "reaction", x["name"]


def marked(text, spans, a=None, b=None):
    """text[a:b] escaped, with each span marked and titled with its pseudonym."""
    a = 0 if a is None else a
    b = len(text) if b is None else b
    out, pos = [], a
    for x, y, pseud, _ in sorted(spans):
        if x < a or y > b:
            continue
        out.append(html.escape(text[pos:x]))
        out.append(f"<mark title='{html.escape(pseud)}'>{html.escape(text[x:y])}</mark> "
                   f"<span class=meta>{html.escape(pseud)}</span>")
        pos = y
    out.append(html.escape(text[pos:b]))
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pseudonyms", nargs="*")
    ap.add_argument("--sample", type=int, default=20, help="occurrences shown per pseudonym")
    ap.add_argument("--values", type=int, default=40, help="distinct values shown per field")
    args = ap.parse_args()
    want = set(args.pseudonyms)

    words = dictionary()
    rep = Replacer(inputs.load(), Map.load(), Ner())   # the map is never saved

    def spans_of(text):
        return [s for s in rep.spans(text, False)
                if s[3] in NAME_KINDS and ordinary(text[s[0]:s[1]], words)]

    hits = defaultdict(list)         # pseudonym -> (record id, field, text, span, text's spans)
    fields = defaultdict(Counter)    # field -> value -> occurrences in records
    fspans = {}                      # (field, value) -> spans
    fkind = defaultdict(Counter)     # field -> pseudonym kind -> occurrences
    n_rec = 0
    t0 = time.time()
    for s in SOURCES:
        for r in state.read_jsonl(state.corpus_file(s)):
            n_rec += 1
            if n_rec % PROGRESS == 0:
                log(f"  read {n_rec} records ({s}), {time.time() - t0:.0f} s")
            # (field, text, its spans or None when not yet computed):
            # each string's spans are computed once.
            texts = [("text", r.get("text") or "", None)]
            texts += [(k, v, None) for k in SENT_FIELDS_NER
                      if isinstance(v := (r.get("source_fields") or {}).get(k), str)]
            for f, v in untagged_strings(r, rep):
                sp = spans_of(v) if v else []
                if not sp:
                    continue
                fields[f][v] += 1
                fspans[(f, v)] = sp
                for x in sp:
                    fkind[f][x[3]] += 1
                texts.append((f, v, sp))
            if want:
                for f, t, sp in texts:
                    if sp is None:
                        sp = spans_of(t) if t else []
                    for x in sp:
                        if x[2] in want:
                            hits[x[2]].append((r["id"], f, t, x, sp))
    log(f"  corpus records: {n_rec}, {time.time() - t0:.0f} s")

    rnd = random.Random(1)
    body = [f"<p class=meta>Local page: real text, read it here only. Made "
            f"{html.escape(time.strftime('%d %b %Y %H:%M'))}. Each marked word is followed "
            f"by the pseudonym it would be replaced with.</p>"]
    if want:
        body.append("<h2>Pseudonyms</h2>")
    for p in args.pseudonyms:
        hs = hits.get(p, [])
        by_field = Counter(f for _, f, _, _, _ in hs)
        log(f"  {p}: {len(hs)} occurrences ({', '.join(f'{f} {n}' for f, n in by_field.most_common())})")
        pick = rnd.sample(hs, min(args.sample, len(hs)))
        body.append(f"<h3>{html.escape(p)}</h3><p class=meta>{len(hs)} occurrences; "
                    f"{len(pick)} drawn at random. By field: "
                    f"{html.escape(', '.join(f'{f} {n}' for f, n in by_field.most_common()))}</p>")
        rows = []
        for rid, f, t, x, sp in pick:
            a, b = max(0, x[0] - CONTEXT), min(len(t), x[1] + CONTEXT)
            near = [y for y in sp if a <= y[0] and y[1] <= b]
            rows.append(f"<tr><td class=meta>{html.escape(f)}</td><td><pre>"
                        f"{'…' if a else ''}{marked(t, near, a, b)}{'…' if b < len(t) else ''}"
                        f"</pre></td></tr>")
        body.append(f"<table>{''.join(rows)}</table>")

    body.append("<h2>Fields spaCy never tags</h2>")
    total = sum(sum(c.values()) for c in fields.values())
    occ = {f: sum(fkind[f].values()) for f in fields}
    body.append(f"<p class=meta>{total} values in {len(fields)} fields hold an ordinary-word "
                f"name; {sum(occ.values())} occurrences. Fields with most occurrences first; "
                f"in each, its {args.values} most frequent distinct values.</p>")
    log(f"  fields spaCy never tags: {len(fields)} fields, {sum(occ.values())} occurrences")
    for f in sorted(fields, key=lambda f: -occ[f]):
        kinds = ", ".join(f"{k} {n}" for k, n in fkind[f].most_common())
        log(f"    {f}: {occ[f]} occurrences in {len(fields[f])} distinct values ({kinds})")
        rows = "".join(
            f"<tr><td class=meta>{n}×</td><td><pre>{marked(v, fspans[(f, v)])}</pre></td></tr>"
            for v, n in fields[f].most_common(args.values))
        body.append(f"<h3>{html.escape(f)}</h3><p class=meta>{occ[f]} occurrences in "
                    f"{len(fields[f])} distinct values; by kind: {html.escape(kinds)}</p>"
                    f"<table>{rows}</table>")

    fd = os.open(OUT, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        # The review page's frame, without its link home: nothing serves this.
        fh.write(page("Ordinary-word examples", "".join(body))
                 .replace("<p class=meta><a href='/'>Review home</a></p>", ""))
    os.chmod(OUT, 0o600)
    log(f"  page: {OUT}")
    log("  ok    finished")


try:
    main()
except SystemExit:
    raise
except BaseException as e:
    # Type and line only: an error's message can carry a record id or a
    # name from the corpus.
    tb = e.__traceback__
    while tb.tb_next:
        tb = tb.tb_next
    log(f"  FAIL  {type(e).__name__} at line {tb.tb_lineno} of {os.path.basename(tb.tb_frame.f_code.co_filename)}")
    sys.exit(1)
