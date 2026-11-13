"""The leak check at the end of `anonymise` (PLAN §2.3).

The review batches sample 50 items per source; this reads all of them. Every
real name the pipeline knows is searched for in every anonymised record,
source fields included: each person's full names, handles of 3 characters
or more and emails from users.json, the Bitbucket accounts' names, the
aliases and unique first names in the anonymising map, first names two
people share, and the client and kept product names. A single word only
spaCy took for a name counts once James has marked it a name; until then it
is counted as undecided, and marked not a name it isn't searched for. A hit
is a place the replacement missed.

Only what is sent is searched: each record's text, source fields (keys
included), reactions and author. The source name, tag types, ids and
timestamps are the pipeline's own words, not the corpus's.

The report, with the real term and a short piece of the text around it, is
written to the state as leak-report.json (owner-only, never sent) and shown
on the review page.
"""

import json
import re
from collections import defaultdict

from . import SOURCES, state

MAX_EXAMPLES = 3
SENT_KEYS = ("text", "source_fields", "reactions", "author")
SNIPPET = 60


def terms(d, amap):
    """{lowercased term: kind} for everything that must not appear."""
    from .anonymise import Replacer, first_name_roles, name_decisions, one_word, slack_users
    from .bitbucket import people_file
    out = {}
    dec = {k: v.get("decision") for k, v in name_decisions().items()}

    def add(t, kind, min_len=3):
        t = (t or "").strip()
        if len(t) >= min_len and t.lower() not in out:
            out[t.lower()] = kind
    for u in slack_users(d):
        if u.get("is_bot") or u.get("name") == "slackbot":
            continue
        p = u.get("profile") or {}
        for n in (u.get("real_name"), p.get("real_name"), p.get("display_name")):
            if n and " " in n.strip():
                add(n, "person name")
        fn, ln = (p.get("first_name") or "").strip(), (p.get("last_name") or "").strip()
        if fn and ln:
            add(f"{fn} {ln}", "person name")
        add(u.get("name"), "slack handle")
        add(p.get("email"), "email")
    for fn in first_name_roles(slack_users(d), lambda u: "person")[1]:
        add(fn, "shared first name")
    for p in (state.read_json(people_file(), {}) or {}).values():
        if p.get("display_name") and " " in p["display_name"].strip():
            add(p["display_name"], "bitbucket name")
        add(p.get("nickname"), "bitbucket name", min_len=4)
    for e in amap.entries:
        kind = {"person": "person alias", "client": "client", "product": "product"}.get(e["kind"])
        if not kind:
            continue
        for a in e.get("aliases", []):
            if e.get("origin") == "spacy" and one_word(a) and dec.get(Replacer.norm(a)) != "name":
                continue
            add(a, kind)
        for fn in e.get("first_names", []):
            add(fn, "unique first name")
    return out


def scan(d, amap):
    found = terms(d, amap)
    if not found:
        return {"terms_checked": 0, "hits": 0, "terms": []}
    rx = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(
        re.escape(t) for t in sorted(found, key=len, reverse=True)) + r")(?![A-Za-z0-9])",
        re.IGNORECASE)
    hits = defaultdict(lambda: {"count": 0, "examples": []})
    for s in SOURCES:
        for r in state.read_jsonl(state.anon_file(s)):
            body = json.dumps({k: r[k] for k in SENT_KEYS if k in r}, ensure_ascii=False)
            for m in rx.finditer(body):
                t = m.group(1).lower()
                h = hits[t]
                h["count"] += 1
                if len(h["examples"]) < MAX_EXAMPLES:
                    a, b = max(0, m.start() - SNIPPET), m.end() + SNIPPET
                    h["examples"].append({"source": s, "id": r["id"], "text": body[a:b]})
    from .anonymise import name_decisions
    cands = state.read_json(state.path("name-candidates.json"), []) or []
    nd = name_decisions()
    report = {
        "terms_checked": len(found),
        "undecided_names": sum(1 for c in cands if c["key"] not in nd),
        "hits": sum(h["count"] for h in hits.values()),
        "terms": sorted(({"term": t, "kind": found[t], **h} for t, h in hits.items()),
                        key=lambda x: (-x["count"], x["term"])),
    }
    state.write_json(report_file(), report)
    return report


def report_file():
    return state.path("leak-report.json")


def load():
    return state.read_json(report_file(), None)
