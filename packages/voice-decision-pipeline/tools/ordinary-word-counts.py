#!/usr/bin/env python3
"""Ordinary-word names: how often each occurs and what spaCy made of it.

For every name the anonymiser replaces (person alias, first name, client,
kept product, spaCy name) whose every word is in the pipeline's SCOWL
dictionary, this counts each occurrence it replaces in the stored corpus:
which field it sits in, whether it is inside code, its case, and whether
spaCy's cached tag covers it (person, organisation or product, or none).
Then it counts the records and voice items that carry one, and how many of
those were labelled, held out or are exemplars, to size a relabel.

A second table ranks every term by occurrences, most first, with its case
counts and labelled items, and marks where the count drops below 100.

Prints pseudonyms and counts only: never a name, a matched word or any
text. Reads the pipeline's state and writes nothing there. Runs spaCy on
nothing: a text with no cached tag is counted as such.

--spellings adds to each ranked row, on the terminal only, the spellings
the term was matched as, with a count each. The log never gets them, so
run it in a terminal of your own, never through a tool that passes the
terminal's output on.

Run with the pipeline's own interpreter and pylib:
  PYTHONPATH=~/.local/share/voice-decision-pipeline/pylib \
    ~/.local/share/voice-decision-pipeline/venv/bin/python tools/ordinary-word-counts.py [--spellings]
Output also goes to $VDP_LOG_DIR (default /tmp)/vdp-ordinary-word-counts.log,
appended under a dated header.
"""

import os
import re
import sys
import time
from collections import Counter, defaultdict

LOG = os.path.join(os.environ.get("VDP_LOG_DIR") or "/tmp", "vdp-ordinary-word-counts.log")
_logf = open(LOG, "a", encoding="utf-8")
os.chmod(LOG, 0o600)


SPELLINGS = "--spellings" in sys.argv[1:]
RANK_MARK = 100


def log(s="", screen_only=""):
    """s goes to the terminal and the log; screen_only to the terminal only."""
    print(s + screen_only, flush=True)
    _logf.write(s + "\n")
    _logf.flush()


log(f"== vdp ordinary-word counts, {time.strftime('%Y-%m-%dT%H:%M:%S%z')}")

from vdp import SOURCES, inputs, labels, pool, state, textutil, voice  # noqa: E402
from vdp.anonmap import Map  # noqa: E402
from vdp.anonymise import (SENT_FIELDS_NER, SPACY_LABELS_MINE, SPACY_LABELS_PERSON,  # noqa: E402
                           Ner, Replacer, anon_id, dictionary)

NAME_KINDS = {"person", "client", "product"}
WORD_SPLIT = re.compile(r"[\s\-_.]+")


def ordinary(s, words):
    ws = [w for w in WORD_SPLIT.split(s.strip()) if w]
    return bool(ws) and all(w.lower() in words for w in ws)


def case_of(s):
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


def code_ranges(text):
    return [(t["start"], t["end"]) for t in textutil.tag(text) if t["type"] in ("code", "log")]


def other_strings(r, rep):
    """The strings the anonymiser rewrites outside text and the spaCy-tagged
    fields: other source fields (keys too) and reaction names."""
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
        yield from walk(v)
    for x in r.get("reactions") or []:
        if isinstance(x.get("name"), str):
            yield x["name"]


def main():
    words = dictionary()
    d = inputs.load()
    amap = Map.load()
    ner = Ner()
    rep = Replacer(d, amap, ner)   # the map is never saved
    real = {}
    for s in SOURCES:
        for r in state.read_jsonl(state.corpus_file(s)):
            real[r["id"]] = r
    log(f"  corpus records: {len(real)}")

    terms = {}                      # (pseudonym, normalised form) -> stats
    forms = defaultdict(set)        # pseudonym -> normalised forms

    def stat(pseud, kind, form):
        k = (pseud, form)
        if k not in terms:
            terms[k] = {"kind": kind, "occ": 0, "field": Counter(), "code": 0,
                        "case": Counter(), "spacy": Counter(), "records": set(),
                        "seen": Counter()}
            forms[pseud].add(form)
        return terms[k]

    def count(text, rid, field, tagged):
        if not text:
            return
        spans = [s for s in rep.spans(text, False) if s[3] in NAME_KINDS
                 and ordinary(text[s[0]:s[1]], words)]
        if not spans:
            return
        cr = code_ranges(text)
        cached = ner.key(text) in ner.cache if tagged else False
        ents = ner.ents(text) if cached else []
        for a, b, pseud, kind in spans:
            st = stat(pseud, kind, Replacer.norm(text[a:b]))
            st["occ"] += 1
            st["field"][field] += 1
            st["case"][case_of(text[a:b])] += 1
            st["records"].add(rid)
            st["seen"][text[a:b]] += 1
            if any(x < b and a < y for x, y in cr):
                st["code"] += 1
                continue
            if not tagged:
                st["spacy"]["not tagged field"] += 1
            elif not cached:
                st["spacy"]["no cache"] += 1
            else:
                labs = {lab for x, y, lab in ents if x < b and a < y}
                if labs & SPACY_LABELS_PERSON:
                    st["spacy"]["person"] += 1
                elif labs & SPACY_LABELS_MINE:
                    st["spacy"]["org/product"] += 1
                else:
                    st["spacy"]["untagged"] += 1

    for rid, r in real.items():
        count(r.get("text") or "", rid, "text", True)
        for k in SENT_FIELDS_NER:
            v = (r.get("source_fields") or {}).get(k)
            if isinstance(v, str):
                count(v, rid, "context field", True)
        for v in other_strings(r, rep):
            count(rep.group_dm_name(v), rid, "other field", False)

    # Voice items: the item itself carries a term, or the text sent with it
    # (the message it answers, its thread or window) does.
    anon = {}
    for s in voice.VOICE_SOURCES:
        for r in state.read_jsonl(state.anon_file(s)):
            anon[r["id"]] = r
    items = voice.load()
    lab = labels.final()
    held = pool.held()
    exem = {e["id"] for e in pool.exemplars(items)}
    to_real = {anon_id(rid): rid for rid in real}

    def sent_with(it):
        out = set()
        a = anon.get(it["id"]) or {}
        out.update(to_real.get(c) for c in a.get("context_ids") or [])
        ans = voice.answered_id(real[it["real_id"]], real)
        if ans:
            out.add(ans)
        out.discard(None)
        return out

    ctx_of = {it["id"]: sent_with(it) for it in items}

    def item_counts(recs):
        direct = {it["id"] for it in items if it["real_id"] in recs}
        via = {it["id"] for it in items if it["id"] not in direct and ctx_of[it["id"]] & recs}
        both = direct | via
        return {"direct": len(direct), "via context": len(via),
                "labelled": len(both & set(lab)), "exemplars": len(both & exem),
                "held out": len(both & held)}

    log(f"  voice items: {len(items)}; labelled {len(lab)}; exemplars {len(exem)}; "
        f"held out {len(held)}")
    log("")
    if not terms:
        log("  no ordinary-word name is replaced anywhere in the corpus")
        return

    log("  term                kind     occ  text ctxf othf code | lower cap upper mixed "
        "| person org/prod untag nocache | recs items:direct via  lab  exem held")
    all_recs = set()
    for (pseud, form) in sorted(terms, key=lambda k: (k[0], sorted(forms[k[0]]).index(k[1]))):
        st = terms[(pseud, form)]
        n = sorted(forms[pseud]).index(form) + 1
        ic = st["items"] = item_counts(st["records"])
        st["n"] = n
        all_recs |= st["records"]
        f, c, sp = st["field"], st["case"], st["spacy"]
        log(f"  {pseud + ' t' + str(n):<19} {st['kind']:<7} {st['occ']:>5} "
            f"{f['text']:>5} {f['context field']:>4} {f['other field']:>4} {st['code']:>4} | "
            f"{c['lower']:>5} {c['capital']:>3} {c['upper']:>5} {c['mixed']:>5} | "
            f"{sp['person']:>6} {sp['org/product']:>8} {sp['untagged']:>5} {sp['no cache']:>7} | "
            f"{len(st['records']):>4} {ic['direct']:>12} {ic['via context']:>4} "
            f"{ic['labelled']:>4} {ic['exemplars']:>5} {ic['held out']:>4}")
    origin = {e["pseudonym"]: e.get("origin") or "" for e in amap.entries}
    aliases = {e["pseudonym"]: e["aliases"] for e in amap.entries}

    def positions(pseud, form):
        """1-based places in the map entry's alias list that the term is,
        so it can be found there without being printed."""
        ps = [str(i) for i, a in enumerate(aliases.get(pseud, []), 1) if Replacer.norm(a) == form]
        return ",".join(ps) or "-"
    log("")
    log("  ranked by occurrences, most first")
    log("  rank term                kind    origin       occ | lower  cap upper mixed "
        "| lower%  labelled items  alias places")
    marked = False
    for i, k in enumerate(sorted(terms, key=lambda k: (-terms[k]["occ"], k)), 1):
        st, (pseud, form) = terms[k], k
        if not marked and st["occ"] < RANK_MARK:
            log(f"  -- below {RANK_MARK} occurrences --")
            marked = True
        c = st["case"]
        extra = ""
        if SPELLINGS:
            extra = "  | " + ", ".join(f"{s} {n}" for s, n in st["seen"].most_common(4))
            if len(st["seen"]) > 4:
                extra += f", +{len(st['seen']) - 4} more"
        log(f"  {i:>4} {pseud + ' t' + str(st['n']):<19} {st['kind']:<7} "
            f"{origin.get(pseud, ''):<10} {st['occ']:>5} | {c['lower']:>5} {c['capital']:>4} "
            f"{c['upper']:>5} {c['mixed']:>5} | {round(100 * c['lower'] / st['occ']):>5}% "
            f"{st['items']['labelled']:>8}  {positions(pseud, form):>12}", extra)
    tot = item_counts(all_recs)
    nt = sum(sp["not tagged field"] for sp in (t["spacy"] for t in terms.values()))
    log("")
    log(f"  totals: {len(terms)} terms over {len(forms)} pseudonyms; "
        f"{sum(t['occ'] for t in terms.values())} occurrences in {len(all_recs)} records; "
        f"{nt} in fields spaCy never tags (other field)")
    log(f"  voice items carrying one: {tot['direct']} directly, {tot['via context']} only in "
        f"the text sent with them; {tot['labelled']} labelled (a relabel sends each to both "
        f"passes), {tot['exemplars']} exemplars, {tot['held out']} held out")
    log("  ok    finished")


try:
    main()
except BaseException as e:
    # Type and line only: an error's message can carry a record id or a
    # name from the corpus.
    tb = e.__traceback__
    while tb.tb_next:
        tb = tb.tb_next
    log(f"  FAIL  {type(e).__name__} at line {tb.tb_lineno} of {os.path.basename(tb.tb_frame.f_code.co_filename)}")
    sys.exit(1)
