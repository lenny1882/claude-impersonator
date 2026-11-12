"""The leak check at the end of `anonymise` (PLAN §2.3).

The review batches sample 50 items per source; this reads all of them. Every
real name the pipeline knows is searched for in every anonymised record,
source fields included: each person's full names, handles of 3 characters
or more and emails from users.json, the Bitbucket accounts' names, the
aliases and unique first names in the anonymising map, and the client and
kept product names. A hit is a place the replacement missed.

The report, with the real term and a short piece of the text around it, is
written to the state as leak-report.json (owner-only, never sent) and shown
on the review page.
"""

import json
import re
from collections import defaultdict

from . import SOURCES, state

MAX_EXAMPLES = 3
SNIPPET = 60


def terms(d, amap):
    """{lowercased term: kind} for everything that must not appear."""
    from .anonymise import slack_users
    from .bitbucket import people_file
    out = {}

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
    for p in (state.read_json(people_file(), {}) or {}).values():
        if p.get("display_name") and " " in p["display_name"].strip():
            add(p["display_name"], "bitbucket name")
        add(p.get("nickname"), "bitbucket name", min_len=4)
    for e in amap.entries:
        kind = {"person": "person alias", "client": "client", "product": "product"}.get(e["kind"])
        if not kind:
            continue
        for a in e.get("aliases", []):
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
            body = json.dumps({k: v for k, v in r.items() if k != "replacements"},
                              ensure_ascii=False)
            for m in rx.finditer(body):
                t = m.group(1).lower()
                h = hits[t]
                h["count"] += 1
                if len(h["examples"]) < MAX_EXAMPLES:
                    a, b = max(0, m.start() - SNIPPET), m.end() + SNIPPET
                    h["examples"].append({"source": s, "id": r["id"], "text": body[a:b]})
    report = {
        "terms_checked": len(found),
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
