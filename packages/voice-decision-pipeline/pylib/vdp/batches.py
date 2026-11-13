"""Review batches of anonymised items, per source (PLAN §2.3).

Before anything from a source is sent, James reviews batches of 50
anonymised items from it, every replacement highlighted, until he says
stop. Batches are drawn per source (Slack, Bitbucket, transcripts, GSD
records; imported transcripts count as transcripts), and nothing from a
source is sent until its own first batch is approved; "stop" applies per
source (James, 11 Nov 2026).

Two gates come before the first batch: every mining candidate has been kept
or struck (PLAN §2.3: "before the first review batch is sent"), and the
anonymised copies were rebuilt after the last mining decision, so kept terms
are already replaced in what James reviews. A third: the Slack extract and
the anonymised copies were built with the audiences now in the inputs, so
an audience set on the mapping page reaches the records before review. A
fourth: every single word only spaCy took for a name is marked a name or not
a name, and the copies were rebuilt after the last such mark.

`sendable(source)` is the check every later pass that sends text must make.
"""

import hashlib
import json
import random
import time

from . import SOURCES, inputs, state
from .record import flags

BATCH_SIZE = 50


def review_file():
    return state.path("review-state.json")


def load_review():
    r = state.read_json(review_file(), {}) or {}
    for s in SOURCES:
        r.setdefault(s, {"batches": [], "approved": 0, "stopped": False})
    return r


def gates():
    """Reasons a new batch can't be drawn yet; empty when it can."""
    reasons = []
    d = inputs.load(required=False)
    if d.get("conversations"):
        h = inputs.audiences_hash(d)
        slack_meta = state.read_json(state.path("slack-meta.json"), None)
        anon_meta = state.read_json(state.path("anon-meta.json"), None)
        if (slack_meta or {}).get("audiences_hash") != h:
            reasons.append("audiences changed since the Slack extract: run "
                           "'voice-decision-pipeline extract slack', then 'anonymise'")
        elif anon_meta is not None and anon_meta.get("audiences_hash") != h:
            reasons.append("audiences changed since the anonymised copies were built: "
                           "run 'voice-decision-pipeline anonymise' again")
    cands = state.read_json(state.path("mining-candidates.json"), None)
    decisions = state.read_json(state.path("mining-decisions.json"), {}) or {}
    meta = state.read_json(state.path("anon-meta.json"), None)
    if meta is None or cands is None:
        reasons.append("no anonymised copies yet: run 'voice-decision-pipeline anonymise'")
        return reasons
    undecided = [c["term"] for c in cands if c["term"] not in decisions]
    if undecided:
        reasons.append(f"{len(undecided)} mining candidates are neither kept nor struck: "
                       "decide them on the review page ('voice-decision-pipeline review')")
    h = hashlib.sha1(json.dumps(decisions, sort_keys=True).encode()).hexdigest()
    if meta.get("decisions_hash") != h:
        reasons.append("mining decisions changed since the anonymised copies were built: "
                       "run 'voice-decision-pipeline anonymise' again")
    from .anonymise import decisions_hash, name_decisions
    names = state.read_json(state.path("name-candidates.json"), []) or []
    nd = name_decisions()
    nleft = sum(1 for c in names if c["key"] not in nd)
    if nleft:
        reasons.append(f"{nleft} single words spaCy took for a name are not marked a name or "
                       "not a name: mark them on the review page's Names")
    if meta.get("names_hash", decisions_hash({})) != decisions_hash(nd):
        reasons.append("names marked since the anonymised copies were built: "
                       "run 'voice-decision-pipeline anonymise' again")
    return reasons


def draw(source, seed=None):
    if source not in SOURCES:
        raise SystemExit(f"voice-decision-pipeline: unknown source {source}")
    g = gates()
    if g:
        raise SystemExit("voice-decision-pipeline: can't draw a batch yet:\n  - " + "\n  - ".join(g))
    rv = load_review()
    st = rv[source]
    if st["stopped"]:
        raise SystemExit(f"voice-decision-pipeline: review of {source} is stopped; "
                         "no more batches are drawn for it")
    open_ = [b for b in st["batches"] if b["status"] == "open"]
    if open_:
        raise SystemExit(f"voice-decision-pipeline: {open_[0]['name']} is still open; "
                         "approve or reject it on the review page first")
    recs = list(state.read_jsonl(state.anon_file(source)))
    by_id = {r["id"]: r for r in recs}
    seen = {i for b in st["batches"] for i in b["items"]}
    pool = [r["id"] for r in recs if "item" in flags(r) and r["id"] not in seen]
    if not pool:
        raise SystemExit(f"voice-decision-pipeline: no unreviewed items left in {source}")
    rng = random.Random(seed if seed is not None else time.time_ns())
    picked = rng.sample(pool, min(BATCH_SIZE, len(pool)))
    n = len(st["batches"]) + 1
    name = f"{source}-{n:03d}"
    items = []
    for i in picked:
        r = by_id[i]
        items.append({"item": r, "context": [by_id[c] for c in r["context_ids"] if c in by_id]})
    state.write_json(state.path("batches", f"{name}.json"),
                     {"name": name, "source": source, "items": items,
                      "drawn_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    st["batches"].append({"name": name, "items": picked, "status": "open"})
    state.write_json(review_file(), rv)
    return name, len(picked)


def decide(name, status, note=""):
    if status not in ("approved", "rejected"):
        raise ValueError(status)
    rv = load_review()
    for s in SOURCES:
        for b in rv[s]["batches"]:
            if b["name"] == name:
                if b["status"] != "open":
                    raise SystemExit(f"voice-decision-pipeline: {name} is already {b['status']}")
                b["status"] = status
                b["note"] = note
                b["decided_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                if status == "approved":
                    rv[s]["approved"] += 1
                state.write_json(review_file(), rv)
                return s
    raise SystemExit(f"voice-decision-pipeline: no batch called {name}")


def stop(source):
    rv = load_review()
    if rv[source]["approved"] < 1:
        raise SystemExit(f"voice-decision-pipeline: {source} has no approved batch yet; "
                         "stopping now would leave it unsendable")
    rv[source]["stopped"] = True
    state.write_json(review_file(), rv)


def sendable(source):
    """True once the source's first batch is approved (PLAN §2.3)."""
    return load_review()[source]["approved"] >= 1
