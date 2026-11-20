"""Local statistics and the never-say list (PLAN §3.4, §3.5). No API.

Measured from the anonymised copies, so nothing in stats.json can carry a
name: length, capitalisation, end punctuation, exclamation marks, emoji,
openings and sign-offs per audience, and British against American spelling.
Every voice item counts, the ones too short or too code-heavy to be
exemplars included.

The never-say list: phrases common in generic business writing that the
voice items hold rarely or never, each with its count there. Two references:
  - colleagues: phrases of 2 to 4 words, every word in the bundled
    dictionary (so no name gets in), common in other people's messages in
    the corpus and rare in the owner's;
  - generic: the fixed list in data/generic-phrases.txt.
"""

import os
import re
from collections import Counter, defaultdict

from . import state, voice
from .anonymise import dictionary
from .index import VOICE_SOURCES

WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")
# Slack's :name: form, and the pictograph and dingbat blocks.
EMOJI = re.compile(r":[a-z0-9_+\-]+:|[" + chr(0x1F300) + "-" + chr(0x1FAFF) + chr(0x2600) + "-" + chr(0x27BF) + "]")
SPELLING = [("colour", "color"), ("behaviour", "behavior"), ("organise", "organize"),
            ("organised", "organized"), ("realise", "realize"), ("realised", "realized"),
            ("analyse", "analyze"), ("apologise", "apologize"), ("prioritise", "prioritize"),
            ("favour", "favor"), ("centre", "center"), ("licence", "license"),
            ("cancelled", "canceled"), ("travelling", "traveling"), ("grey", "gray"),
            ("optimise", "optimize"), ("summarise", "summarize"), ("customise", "customize"),
            ("initialise", "initialize"), ("serialise", "serialize"), ("normalise", "normalize")]
# Rare: under 1 use in 1,000 messages, or under a tenth of the colleagues' rate.
RARE_RATE = 0.001
RATIO = 0.1
COLLEAGUE_MIN = 15
COLLEAGUE_TOP = 120


def generic_phrases():
    p = os.path.join(os.path.dirname(__file__), "data", "generic-phrases.txt")
    with open(p, encoding="utf-8") as f:
        return [l.strip().lower() for l in f if l.strip() and not l.startswith("#")]


def prose(text, tags):
    return voice.without_code(text, tags).replace("[code]", " ")


def others():
    """Other people's messages in the voice sources, anonymised: not
    the owner's, not bots'."""
    for s in VOICE_SOURCES:
        for r in state.read_jsonl(state.anon_file(s)):
            fl = {t["type"] for t in r.get("tags") or [] if "start" not in t}
            if r.get("author") in ("self-01", "bot") or "bot" in fl:
                continue
            if (r.get("text") or "").strip():
                yield prose(r["text"], r.get("tags"))


def ngrams(text, words, lo=2, hi=4):
    ws = WORD.findall(text.lower())
    out = set()
    for n in range(lo, hi + 1):
        for i in range(len(ws) - n + 1):
            g = ws[i:i + n]
            if all(w in words for w in g):
                out.add(" ".join(g))
    return out


def count_phrase(texts_lower, phrase):
    rx = re.compile(r"(?<![a-z0-9'])" + re.escape(phrase) + r"(?![a-z0-9'])")
    return sum(1 for t in texts_lower if rx.search(t))


def first_word(t):
    m = WORD.search(t.lower())
    return m.group(0) if m else None


def last_words(t, words):
    ws = WORD.findall(t.lower())
    if len(ws) < 5:
        return None
    tail = ws[-1]
    return tail if tail in words else None


PURPOSE_MIN = 10


def median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * q))] if xs else 0


def build(items=None, log=print):
    from . import labels
    items = items or voice.load()
    words = dictionary()
    final = labels.final()
    by_aud = defaultdict(list)
    by_pur = defaultdict(lambda: defaultdict(list))
    for it in items:
        t = prose(it["text"], it["tags"]).strip()
        by_aud[it["audience"]].append(t)
        if t:
            for p in final.get(it["id"], []):
                by_pur[it["audience"]][p].append(voice.words(t))
    auds = {}
    for aud, ts in sorted(by_aud.items()):
        ts = [t for t in ts if t]
        n = max(1, len(ts))
        wc = [voice.words(t) for t in ts]
        opens = Counter(w for w in (first_word(t) for t in ts) if w and w in words)
        signs = Counter(w for w in (last_words(t, words) for t in ts) if w)
        auds[aud] = {
            "messages": len(ts), "median_words": median(wc), "p90_words": pct(wc, 0.9),
            "lowercase_start": round(sum(1 for t in ts if t[:1].islower()) / n, 3),
            "full_stop_end": round(sum(1 for t in ts if t.rstrip().endswith(".")) / n, 3),
            "exclamation_per_message": round(sum(t.count("!") for t in ts) / n, 3),
            "emoji_per_message": round(sum(len(EMOJI.findall(t)) for t in ts) / n, 3),
            "openings": [[w, c] for w, c in opens.most_common(10) if c >= 3],
            "signoffs": [[w, c] for w, c in signs.most_common(10) if c >= 3],
            # Length per purpose, where at least PURPOSE_MIN messages carry it.
            "purposes": {p: {"messages": len(xs), "median_words": median(xs), "p90_words": pct(xs, 0.9)}
                         for p, xs in sorted(by_pur[aud].items()) if len(xs) >= PURPOSE_MIN},
        }
    mine = [prose(it["text"], it["tags"]).lower() for it in items]
    alltext = " ".join(mine)
    spelling = {"british": 0, "american": 0}
    for b, a in SPELLING:
        spelling["british"] += len(re.findall(rf"\b{b}\b", alltext))
        spelling["american"] += len(re.findall(rf"\b{a}\b", alltext))
    theirs = [t.lower() for t in others()]
    n_me, n_them = max(1, len(mine)), max(1, len(theirs))
    never = []
    # Colleagues' phrases, counted once per message.
    gc = Counter()
    for t in theirs:
        gc.update(ngrams(t, words))
    mc = Counter()
    for t in mine:
        mc.update(ngrams(t, words))
    cands = []
    for g, c in gc.items():
        if c < COLLEAGUE_MIN:
            continue
        rate_them, rate_me = c / n_them, mc[g] / n_me
        if rate_me <= RARE_RATE or rate_me <= RATIO * rate_them:
            cands.append((rate_them, g, c))
    cands.sort(reverse=True)
    # A longer phrase that holds a listed shorter one adds nothing.
    kept = []
    for _, g, c in cands:
        if any(f" {k} " in f" {g} " for k, _ in kept):
            continue
        kept.append((g, c))
        if len(kept) >= COLLEAGUE_TOP:
            break
    for g, c in kept:
        never.append({"phrase": g, "self": mc[g], "reference": "colleagues", "reference_count": c})
    listed = {x["phrase"] for x in never}
    for g in generic_phrases():
        if g in listed:
            continue
        me = count_phrase(mine, g)
        if me / n_me <= RARE_RATE:
            never.append({"phrase": g, "self": me, "reference": "generic",
                          "reference_count": count_phrase(theirs, g)})
    log(f"  ok    stats: {len(items)} voice items over {len(auds)} audiences; "
        f"never-say list {len(never)} phrases ({len(kept)} from colleagues)")
    return {"schema_version": 1, "audiences": auds, "spelling": spelling, "never_say": never}
