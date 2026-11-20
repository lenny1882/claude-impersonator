"""Holdouts and the exemplar pool (PLAN §3.5, §3.7).

Holdouts: 10% of the labelled voice items, drawn per audience so each keeps
its share, are held back from the exemplar pool and from the guide, and
drafted against in validation. Each validation run draws a fresh holdout
(`voice holdout --fresh`); the run number is kept with it, and the answers
of every run are kept.

The pool: every other labelled voice item, minus messages of 3 words or
fewer and messages at least 50% code or logs by characters.
Both thresholds are config values in the state (voice-config.json);
changing them changes the pool only. A kept exemplar's code and log spans
become [code], in it and in the message it answers.
Dropped messages still count in the statistics (voicestats).
"""

import hashlib
import random
from collections import defaultdict

from . import labels, state, voice

HOLDOUT_SHARE = 0.10
DEFAULTS = {"min_words": 4, "max_code_share": 0.5}


def config():
    c = dict(DEFAULTS)
    c.update(state.read_json(state.path("voice-config.json"), {}) or {})
    return c


def holdout_file():
    return state.path("holdouts.json")


def holdout(fresh=False, log=print):
    cur = state.read_json(holdout_file(), None)
    if cur and not fresh:
        return cur
    lab = labels.final()
    by_aud = defaultdict(list)
    for it in voice.load():
        if it["id"] in lab:
            by_aud[it["audience"]].append(it["id"])
    if not by_aud:
        raise SystemExit("voice-decision-pipeline: nothing labelled yet; run 'voice label' first")
    run = (cur or {}).get("run", 0) + 1
    rnd = random.Random(f"holdout-{run}")
    ids = []
    for aud in sorted(by_aud):
        xs = sorted(by_aud[aud])
        rnd.shuffle(xs)
        ids.extend(xs[:max(1, round(len(xs) * HOLDOUT_SHARE))])
    d = {"run": run, "ids": sorted(ids)}
    state.write_json(holdout_file(), d)
    log(f"  ok    holdout run {run}: {len(ids)} items held back")
    return d


def countable(it, c=None):
    """Whether a held-back message counts in validation: the pool's own rule,
    with min_words words still left after code becomes [code] and links
    [url]."""
    c = c or config()
    return keep(it, c) and voice.shown_words(it["text"]) >= c["min_words"]


def holdout_more(audience, n, log=print):
    """Hold back n more of an audience's messages, only as many as needed, when
    its pairs run out: chosen from messages that would
    count, were never shown to the guide, and aren't held back already. They
    leave the exemplar pool; validate then drafts them."""
    from . import guide
    cur = state.read_json(holdout_file(), None)
    if not cur:
        raise SystemExit("voice-decision-pipeline: no holdout yet; run 'voice holdout' first")
    shown = guide.shown_ids()
    held_now = set(cur["ids"])
    lab = labels.final()
    c = config()
    cands = sorted(it["id"] for it in voice.load()
                   if it["audience"] == audience and it["id"] in lab and it["id"] not in held_now
                   and it["id"] not in shown and countable(it, c))
    rnd = random.Random(f"holdout-{cur['run']}-more-{audience}-{len(held_now)}")
    rnd.shuffle(cands)
    add = sorted(cands[:n])
    if not add:
        raise SystemExit(f"voice-decision-pipeline: no {audience} message left to hold back")
    cur["ids"] = sorted(held_now | set(add))
    cur.setdefault("added", []).append({"audience": audience, "ids": add})
    state.write_json(holdout_file(), cur)
    log(f"  ok    held back {len(add)} more {audience} messages"
        + (f" (only {len(add)} left that the guide never saw)" if len(add) < n else "")
        + f"; run 'voice validate' to draft them, then 'voice pairs --more {audience}'")
    return add


def held():
    return set((state.read_json(holdout_file(), {}) or {}).get("ids", []))


def keep(it, c=None):
    c = c or config()
    return voice.words(it["text"]) >= c["min_words"] and \
        voice.code_share(it["text"], it["tags"]) < c["max_code_share"]


def exemplar(it, purposes):
    text = voice.without_code(it["text"], it["tags"])
    ans = voice.without_code(it["answered"], it["answered_tags"])
    h = hashlib.sha256(((ans + "\n\n" + text) if ans else text).encode()).hexdigest()
    return {"id": it["id"], "audience": it["audience"], "purposes": purposes,
            "text": text, "answered": ans, "hash": h}


def exemplars(items=None):
    """The pool: [exemplar], holdouts left out."""
    lab = labels.final()
    out_ = held()
    c = config()
    return [exemplar(it, lab[it["id"]]) for it in (items or voice.load())
            if it["id"] in lab and it["id"] not in out_ and keep(it, c)]
