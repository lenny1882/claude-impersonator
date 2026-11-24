"""Voice validation (PLAN §3.5, §3.7).

For every held-back message, a brief of what it says, in neutral words and
none of its own (Sonnet 5.5), is written first. Drafts are
written from the brief, the context, the audience and the purposes by the
drafting model (Opus 5.5), with 3, 5 and 8 exemplars, as voice-runtime
drafts from a brief. The judge (Fable 5.2, not the drafting model) sees the brief too,
compares each draft with the real message and scores it 1 to 5. The count
with the best mean score is the build's exemplar count.

Only held-back messages the exemplar pool's rule would keep are drafted,
scored or paired (counted()); the rest are held back but count for nothing.

The drafter's settings are the state's voice/drafter.json (drafter.py). Rows
carry their audience's draft method, a hash of the settings its drafts
depend on; only rows of an audience's current method count, so changing one
audience's notes drafts and pairs only that audience again, and the other
audiences' drafts, pairs and answers stand. Rows written without a method
are ignored.

'voice validate --batch' drafts one batch for each audience with nothing
judged under its current method: PAIRS_PER_AUDIENCE held-back messages the
owner has never been shown (in a pair, the judge review, the label check or
the disagreement grading), drawn once per method and kept in
validation/batch.json. 'voice pairs --redraw all' then drops the pairs of
every audience whose pairs were drafted under an older method and draws its
batch.

Exemplars are picked as voice-runtime picks them: the pool narrowed to the
audience and to any of the purposes, then the closest by similarity to the
situation; a cell with too few is filled from the same audience, closest
first, whatever the purpose. The situation is the
message the held-back one answers, else the last message before it. Vectors
come from embedding-lib, so this runs on its interpreter; each exemplar's
vector is cached by its hash.

The owner then sees blind pairs (their message and the best count's draft,
shuffled): 12 per audience across the five corpus audiences, spread across
the purposes. Each answer is written to validation-answers.jsonl as it is
given; pairs.json holds the pairs and pairs-key.json which side is real,
both in the state. On top of the pairs they review the judge's 20
worst-scored drafts and 10 random ones.

Pass rule (the settings' pass_rule section, settings.py; the names below
are its defaults here, and each change is recorded with the run it applies
to in validation/pass-rule.jsonl): every
gate on its own, none weighed against another. The spotting rate is right
picks minus wrong picks over pairs ("can't tell" counts as neither); how sure
a rate is comes from a Dirichlet over the right, wrong and can't-tell counts,
so it takes the number of pairs into account:
  - blind test: at least SURE that the overall spotting rate is at most
    OVERALL_BAR;
  - each audience: at least SURE that its spotting rate is at most
    AUDIENCE_BAR; between UNSURE and SURE it gets 12 more pairs, under UNSURE
    it fails;
  - grades: at least GRADES_ALL of drafts at 4 or higher, at least
    GRADES_AUDIENCE in each audience, and none at 1.
"""

import json
import os
import random
import time
from collections import Counter, defaultdict

from . import drafter, guide, labels, model, pool, state, voice
from .index import VOICE_SOURCES

# The defaults of the pass rule and the judge; the state's settings.json
# "pass_rule" and "judge" sections win (settings.py, rule(), judge_system()).
COUNTS = (3, 5, 8)
OVERALL_BAR, AUDIENCE_BAR = 0.10, 0.25
SURE, UNSURE = 0.80, 0.50
GRADES_ALL, GRADES_AUDIENCE = 0.80, 0.70
DRAWS = 20000
PAIRS_PER_AUDIENCE = 12
WORST, RANDOM = 20, 10


DRAFT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["text"],
                "properties": {"text": {"type": "string"}}}


BRIEF_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["brief"],
                "properties": {"brief": {"type": "string"}}}

# The one 1-5 scale: the judge's prompt and the owner's grade buttons both use it.
GRADES = {5: "indistinguishable from self-01's own", 4: "sendable as is or with a trivial edit",
          3: "content right, needs rewording", 2: "voice or content wrong", 1: "of no use"}

JUDGE_BASE = """You judge drafts written in one person's voice. The person is self-01; names
are pseudonyms. You see the conversation, the message self-01 really wrote next, a brief of
what that message says, and several drafts written from the brief without seeing the
message. Score each draft 1 to 5 for how far self-01 would send it as is, judged against the
real message: mostly voice (wording, length, tone, punctuation, capitalisation), and whether
it says what the brief says, nothing dropped or added.
"""


def grades():
    """{1..5: meaning} of the judge's scale, as the settings give it."""
    from . import settings
    return {int(k): v for k, v in settings.get("judge")["grades"].items()}


def judge_system():
    from . import settings
    g = grades()
    return settings.get("judge")["system"] + "\n" + " ".join(f"{n}: {g[n]}." for n in (5, 4, 3, 2, 1))


JUDGE_SYSTEM = JUDGE_BASE + "\n" + " ".join(f"{n}: {GRADES[n]}." for n in (5, 4, 3, 2, 1))


def rule():
    """The pass rule and its sizes, as the settings give them."""
    from . import settings
    return settings.get("pass_rule")

# The judge's per-message prompt and context size: the defaults; the state's
# settings.json "judge" section wins.
JUDGE_PROMPT = """Conversation:
{context}

The message self-01 really wrote:
{message}

The brief the drafts were written from:
{brief}

{drafts}

Score drafts 1 to {n}."""
JUDGE_BEFORE_CHARS = 4000

JUDGE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["scores"],
                "properties": {"scores": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["draft", "score", "reason"],
                    "properties": {"draft": {"type": "integer"},
                                   "score": {"type": "integer", "minimum": 1, "maximum": 5},
                                   "reason": {"type": "string"}}}}}}


def vdir(*p):
    return state.path("validation", *p)


def run_no():
    return (state.read_json(pool.holdout_file(), {}) or {}).get("run", 0)


# -- embeddings ---------------------------------------------------------------

def _el():
    import embedding_lib as el
    if getattr(el, "EMBEDDING_LIB_API", None) != 1:
        raise SystemExit("voice-decision-pipeline: embedding-lib API 1 is required")
    return el


def exemplar_vectors(ex, log=print):
    import numpy as np
    from .index import fit
    el = _el()
    cache_p, hashes_p = vdir("exemplar-vectors.npy"), vdir("exemplar-hashes.json")
    ident = el.identity()
    cached = {}
    meta = state.read_json(hashes_p, None)
    if meta and meta.get("identity") == ident and os.path.exists(cache_p):
        m = np.load(cache_p)
        cached = {h: m[i] for i, h in enumerate(meta["hashes"])}
    todo = [e for e in ex if e["hash"] not in cached]
    if todo:
        log(f"  embed {len(todo)} exemplars ({len(ex) - len(todo)} cached)")
        texts = fit(el, [(e["id"], e["answered"], e["text"]) for e in todo])
        for i in range(0, len(texts), 512):
            for e, v in zip(todo[i:i + 512], el.embed(texts[i:i + 512])):
                cached[e["hash"]] = v
    hs = [e["hash"] for e in ex]
    m = np.vstack([cached[h] for h in hs]).astype("float32") if hs else np.zeros((0, 1), "float32")
    tmp = vdir(".vec.tmp.npy")
    np.save(tmp, m)
    os.replace(tmp, cache_p)
    state.write_json(hashes_p, {"identity": ident, "hashes": hs})
    return m


def search(ex, m, qv, audience, purposes, k):
    """voice-runtime's pick: audience and any purpose, closest first; filled
    from the same audience, closest first."""
    import numpy as np
    idx = [i for i, e in enumerate(ex) if e["audience"] == audience]
    if not idx:
        return []
    sims = m[idx] @ qv
    order = [idx[j] for j in np.argsort(-sims)]
    ps = set(purposes)
    first = [i for i in order if ps & set(ex[i]["purposes"])][:k]
    rest = [i for i in order if i not in set(first)][:max(0, k - len(first))]
    return [ex[i] for i in first + rest]


def situation(it):
    if it["answered"]:
        return voice.without_code(it["answered"], it["answered_tags"])
    return it["before"][-1][1] if it["before"] else it["text"][:0]


# -- drafting and judging -----------------------------------------------------

def brief_prompt(it, d=None):
    from .settings import fill
    d = d or drafter.load()
    ctx = voice.render_context(it["before"], d["brief_before_chars"]) or "(no earlier messages)"
    return fill(d["brief_prompt"], context=ctx, message=voice.without_code(it['text'], it.get('tags') or []))


def draft_prompt(it, purposes, exs, brief, d=None):
    from .settings import fill
    d = d or drafter.load()
    n = d["answering_chars"]
    ctx = voice.render_context(it["before"], d["draft_before_chars"]) or "(no earlier messages)"
    shown = "\n\n---\n\n".join(
        (f"(answering: {e['answered'][:n]})\n" if e["answered"] else "") + e["text"] for e in exs)
    return fill(d["draft_prompt"], examples=shown, context=ctx, brief=brief, audience=it["audience"],
                purposes=", ".join(purposes),
                source="Bitbucket pull request" if it["source"] == "bitbucket" else "Slack")


def judge_prompt(it, brief, drafts):
    """The judge's prompt for one message: drafts is [text], in order."""
    from . import settings
    j = settings.get("judge")
    return settings.fill(j["prompt"], context=voice.render_context(it["before"], j["before_chars"]) or "(none)",
                         message=it["text"], brief=brief, n=len(drafts),
                         drafts="\n\n".join(f"Draft {i}:\n{t}" for i, t in enumerate(drafts, 1)))


def read_lines(name):
    return list(state.read_jsonl(vdir(name)))


def rows(name, run):
    """A file's rows for this run, for held-back messages that count, drafted
    under their audience's current method."""
    ok = counted()
    aud = _COUNTED["aud"]
    cur = drafter.methods()
    return [r for r in read_lines(name) if r["run"] == run and r["id"] in ok
            and drafter.normal(r.get("method"), aud[r["id"]]) == cur.get(aud[r["id"]])]


_COUNTED = {}


def counted():
    """The held-back messages validation counts: those the exemplar pool's own
    rule would keep (at least min_words words, under max_code_share code),
    with at least min_words words left after code becomes [code] and links
    and [url], as the pairs page shows them; so a "^" or a link, the same on
    both sides, scores and pairs nothing.
    Cached per holdout file and corpus change."""
    hf = pool.holdout_file()
    stamp = tuple(os.path.getmtime(f) if os.path.exists(f) else 0
                  for f in [hf] + [state.anon_file(s) for s in VOICE_SOURCES] + [state.path("voice-config.json")])
    if _COUNTED.get("stamp") != stamp:
        by_id = {it["id"]: it for it in voice.load()}
        c = pool.config()
        ids = {i for i in pool.held() if i in by_id and pool.countable(by_id[i], c)}
        _COUNTED.update(stamp=stamp, ids=ids, aud={i: by_id[i]["audience"] for i in ids})
    return _COUNTED["ids"]


def append(name, rows):
    with open(vdir(name), "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def shown_before():
    """Ids of every held-back message whose real text the owner has been
    shown: in a pair (dropped ones too), the judge review, the label check
    or the disagreement grading, every round of each."""
    out = {p["id"] for p in (state.read_json(pairs_file(), {}) or {}).get("pairs", [])}
    out |= {x["id"] for x in (state.read_json(vdir("judge-review.json"), {}) or {}).get("items", [])}
    for f in (labels.check_file(), labels.disagree_grades_file()):
        d = state.read_json(f, {}) or {}
        for r in [d] + list(d.get("previous") or []):
            out |= set(r.get("ids") or [])
    return out


def judged_audiences(run=None):
    """Audiences with a held-back message judged under their current method."""
    run = run_no() if run is None else run
    aud = (counted(), _COUNTED["aud"])[1]
    return {aud[r["id"]] for r in rows("judge.jsonl", run)}


def pair_method(p, run=None):
    """The method a pair's draft was written under: as recorded when it was
    drawn, or for an older pair, that of the drafts row whose text is on the
    pair (a message can have drafts under several methods)."""
    if p.get("method"):
        return drafter.normal(p["method"], p["audience"])
    run = run_no() if run is None else run
    k = (state.read_json(pairs_file(), {}) or {}).get("k")
    found = None
    for r in read_lines("drafts.jsonl"):
        if r["id"] == p["id"] and r["run"] == run and r["k"] == k and r["text"] in (p["a"], p["b"]):
            found = drafter.normal(r.get("method"), p["audience"])
    return found


def stale_audiences():
    """The audiences 'voice pairs --redraw all' draws again: those with a pair
    in use drafted under an older method than their current one, and those
    with no pair in use and a batch drawn under their current method."""
    cur = drafter.methods()
    pr = state.read_json(pairs_file(), None) or {}
    run = run_no()
    out = []
    for a in voice.corpus_audiences():
        mine = [p for p in active(pr) if p["audience"] == a]
        if any(pair_method(p) != cur[a] for p in mine) or (not mine and _batch_entry(a, run) is not None):
            out.append(a)
    return out


def batch_file():
    return vdir("batch.json")


def _batch_entry(a, run):
    cur = state.read_json(batch_file(), None) or {}
    e = (cur.get("ids") or {}).get(a)
    if cur.get("run") == run and isinstance(e, dict) and e.get("method") == drafter.method(a):
        return e["ids"]
    return None


def batch(log=print):
    """{audience: [ids]}: one batch for each corpus audience with nothing
    judged under its current method, of counted held-back messages the owner
    has never been shown, spread across purposes. Drawn once per audience
    method and run, then read back, so a resumed run drafts the same
    messages."""
    run = run_no()
    n_ = rule()["pairs_per_audience"]
    lab = labels.final()
    ok = counted()
    aud = _COUNTED["aud"]
    seen = shown_before()
    done = judged_audiences(run)
    cur = state.read_json(batch_file(), None) or {}
    stored = dict(cur.get("ids") or {}) if cur.get("run") == run else {}
    out = {}
    for a in voice.corpus_audiences():
        m = drafter.method(a)
        had = _batch_entry(a, run)
        if had is not None:
            out[a] = had
            continue
        if a in done:
            continue
        cand = {i: (a, lab[i]) for i in sorted(ok) if aud[i] == a and i in lab and i not in seen}
        if len(cand) < n_:
            # Short of a batch: hold back more of the audience, only messages
            # the guide never saw and the owner was never shown.
            try:
                add = pool.holdout_more(a, n_ - len(cand), log=lambda *x: None, exclude=seen)
            except SystemExit:
                add = []
            if add:
                log(f"  ok    held back {len(add)} more {a} messages for the batch")
                ok = counted()
                aud = _COUNTED["aud"]
                cand = {i: (a, lab[i]) for i in sorted(ok) if aud.get(i) == a and i in lab and i not in seen}
        out[a] = sorted(labels.spread_sample(cand, n_, seed=f"batch-{m}-{run}-{a}"))
        stored[a] = {"method": m, "ids": out[a]}
        if len(out[a]) < n_:
            log(f"  --    {a}: only {len(out[a])} held-back messages never shown; a batch is {n_}")
    state.write_json(batch_file(), {"run": run, "ids": stored})
    return out


def drafts_and_judge(counts=None, limit=None, only_batch=False, log=print):
    import numpy as np
    voice.require_sendable()
    counts = tuple(counts or rule()["exemplar_counts"])
    jsys = judge_system()
    from . import voicestats
    g = guide.assemble("validation")
    d = drafter.load()
    mth = drafter.methods(d)
    items = voice.load()
    by_id = {it["id"]: it for it in items}
    lab = labels.final()
    # The batch first: drawing it may hold back more messages.
    b = {i for ids in batch(log=log).values() for i in ids} if only_batch else None
    ok = counted()
    hold = [by_id[i] for i in sorted(pool.held()) if i in by_id and i in lab and i in ok]
    if not hold:
        raise SystemExit("voice-decision-pipeline: no holdouts; run 'voice holdout' first")
    if b is not None:
        hold = [it for it in hold if it["id"] in b]
    if limit:
        hold = hold[:limit]
    # Measured afresh, so the lengths per purpose follow the current labels;
    # after the holdout check, so a refused run leaves stats.json as it was.
    stats = voicestats.build(items, log=log)
    state.write_json(state.path("voice", "stats.json"), stats)
    ex = pool.exemplars(items)
    m = exemplar_vectors(ex, log=log)
    el = _el()
    run = run_no()
    have = {(r["id"], r["k"]) for r in rows("drafts.jsonl", run)}
    judged = {r["id"] for r in rows("judge.jsonl", run)}
    briefs = {r["id"]: r["brief"] for r in rows("briefs.jsonl", run)}
    todo = [it for it in hold if it["id"] not in judged]
    log(f"== validate run {run}: {len(todo)} of {len(hold)} held-back messages to draft and judge, "
        f"counts {list(counts)}")
    qvs = el.embed([situation(it) or it["audience"] for it in todo]) if todo else []
    for n, (it, qv) in enumerate(zip(todo, qvs), 1):
        ps = lab[it["id"]]
        system = d["draft_system"] + guide.render(g, stats, it["audience"], ps, d)
        method = mth[it["audience"]]
        try:
            if it["id"] not in briefs:
                ans = model.call("brief", d["brief_system"], brief_prompt(it, d), BRIEF_SCHEMA, log=log)
                briefs[it["id"]] = ans["brief"]
                append("briefs.jsonl", [{"run": run, "method": method, "id": it["id"], "brief": ans["brief"]}])
            brief = briefs[it["id"]]
            for k in counts:
                if (it["id"], k) in have:
                    continue
                exs = search(ex, m, np.asarray(qv, "float32"), it["audience"], ps, k)
                ans = model.call("drafter", system, draft_prompt(it, ps, exs, brief, d), DRAFT_SCHEMA, log=log)
                append("drafts.jsonl", [{"run": run, "method": method, "id": it["id"], "k": k, "text": ans["text"],
                                         "exemplars": [e["id"] for e in exs]}])
                have.add((it["id"], k))
            ds = {r["k"]: r["text"] for r in rows("drafts.jsonl", run) if r["id"] == it["id"]}
            ks = [k for k in counts if k in ds]
            jp = judge_prompt(it, brief, [ds[k] for k in ks])
            ans = model.call("judge", jsys, jp, JUDGE_SCHEMA, log=log)
        except model.UsageLimit as e:
            log(f"  stop  usage limit after {n - 1} messages: {e}; run the same command again to resume")
            return 6
        except model.CallFailed as e:
            log(f"  skip  {it['id']}: {e}")
            continue
        sc = {x["draft"]: x for x in ans["scores"]}
        append("judge.jsonl", [{"run": run, "method": method, "id": it["id"], "k": k, "score": sc[i]["score"],
                                "reason": sc[i]["reason"]} for i, k in enumerate(ks, 1) if i in sc])
        if n % 25 == 0 or n == len(todo):
            log(f"  {n}/{len(todo)} judged")
    log(f"  ok    validate run {run}: best count {best_count()}")
    return 0


def scores(run=None):
    run = run_no() if run is None else run
    out = defaultdict(list)
    for r in rows("judge.jsonl", run):
        out[r["k"]].append(r["score"])
    return out


def best_count(run=None):
    sc = scores(run)
    if not sc:
        return None
    return max(sorted(sc), key=lambda k: (sum(sc[k]) / len(sc[k]), -k))


# -- blind pairs ----------------------------------------------------------------

def pairs_file():
    return vdir("pairs.json")


def key_file():
    return vdir("pairs-key.json")


def answers_file():
    return state.path("validation-answers.jsonl")


def make_pairs(audience=None, log=print):
    """12 pairs per corpus audience, or 12 more for one audience."""
    if audience is not None:
        _audience(audience)
    run = run_no()
    k = best_count(run)
    if k is None:
        raise SystemExit("voice-decision-pipeline: no judged drafts; run 'voice validate' first")
    cur = state.read_json(pairs_file(), None)
    if cur and cur["run"] != run:
        cur = None
    if cur and audience is None:
        return cur
    cur = cur or {"run": run, "k": k, "pairs": []}
    # More pairs use the exemplar count the existing pairs were drawn at.
    k = cur["k"]
    key = state.read_json(key_file(), {}) if cur["pairs"] else {}
    used = {p["id"] for p in cur["pairs"]}
    items = {it["id"]: it for it in voice.load()}
    lab = labels.final()
    drafts = {r["id"]: r["text"] for r in rows("drafts.jsonl", run) if r["k"] == k}
    for aud in ([audience] if audience else voice.corpus_audiences()):
        _draw(cur, key, used, items, lab, drafts, aud, rule()["pairs_per_audience"])
    state.write_json(key_file(), key)
    state.write_json(pairs_file(), cur)
    log(f"  ok    {len(active(cur))} blind pairs (exemplar count {cur['k']})")
    return cur


def _draw(cur, key, used, items, lab, drafts, aud, n):
    """Add n pairs for aud from drafts not yet in any pair, dropped ones included."""
    run = cur["run"]
    rnd = random.Random(f"pairs-{run}-{len(cur['pairs'])}")
    pool_ = {i: (aud, lab[i]) for i in drafts if i in items and items[i]["audience"] == aud
             and i not in used}
    for i in labels.spread_sample(pool_, n, seed=f"pairs-{run}-{aud}-{len(used)}"):
        it = items[i]
        real_a = rnd.random() < 0.5
        pid = f"p{len(cur['pairs']) + 1:03d}"
        cur["pairs"].append({"pair": pid, "id": i, "audience": aud, "purposes": lab[i],
                             "method": drafter.method(aud),
                             "context": voice.render_context(it["before"], 3000),
                             "a": it["text"] if real_a else drafts[i],
                             "b": drafts[i] if real_a else it["text"]})
        key[pid] = "A" if real_a else "B"
        used.add(i)


def active(pr):
    """The pairs that count: all but those dropped."""
    gone = set((pr or {}).get("dropped", {}))
    return [p for p in (pr or {}).get("pairs", []) if p["pair"] not in gone]


def drop_pairs(ids, reason, log=print):
    """Drop pairs from the result (an answer the page's format gave away, for
    one) and draw as many new pairs for the same audiences in their place.
    Dropped pairs and their answers stay in the files, marked."""
    run = run_no()
    cur = state.read_json(pairs_file(), None)
    if not cur or cur["run"] != run:
        raise SystemExit("voice-decision-pipeline: no pairs for this run; run 'voice pairs' first")
    by = {p["pair"]: p for p in active(cur)}
    bad = [i for i in ids if i not in by]
    if bad:
        raise SystemExit(f"voice-decision-pipeline: not a pair in use: {', '.join(bad)}")
    cur.setdefault("dropped", {})
    for i in ids:
        cur["dropped"][i] = reason
    key = state.read_json(key_file(), {}) or {}
    used = {p["id"] for p in cur["pairs"]}
    items = {it["id"]: it for it in voice.load()}
    lab = labels.final()
    drafts = {r["id"]: r["text"] for r in rows("drafts.jsonl", run) if r["k"] == cur["k"]}
    for aud, n in sorted(Counter(by[i]["audience"] for i in ids).items()):
        before = len(cur["pairs"])
        _draw(cur, key, used, items, lab, drafts, aud, n)
        log(f"  ok    dropped {n} {aud} pair{'s' if n > 1 else ''}, drew "
            + ", ".join(p["pair"] for p in cur["pairs"][before:]))
    state.write_json(key_file(), key)
    state.write_json(pairs_file(), cur)
    return cur


def _audience(aud):
    if aud not in voice.corpus_audiences():
        raise SystemExit(f"voice-decision-pipeline: not an audience: {aud}; "
                         f"one of {', '.join(voice.corpus_audiences())}")


def redraw(aud, log=print):
    """After an audience's drafts are written again under a new method: drop
    every pair of it still in use and draw a fresh batch of
    PAIRS_PER_AUDIENCE, never more, only from messages never in any pair, so
    the owner never judges a message whose real side they have seen. With fewer than a batch of those, it draws none and holds back as
    many more as the batch needs; 'voice validate' drafts them and
    'voice pairs --more' draws the batch. Dropped pairs and their answers
    stay in the files, marked with why."""
    _audience(aud)
    m = drafter.method(aud)
    n_ = rule()["pairs_per_audience"]
    run = run_no()
    cur = state.read_json(pairs_file(), None)
    if not cur or cur["run"] != run:
        raise SystemExit("voice-decision-pipeline: no pairs for this run; run 'voice pairs' first")
    cur.setdefault("dropped", {})
    old = [p for p in active(cur) if p["audience"] == aud]
    for p in old:
        seen = any(q["id"] == p["id"] and q["pair"] != p["pair"] for q in cur["pairs"])
        cur["dropped"][p["pair"]] = ("its message was already in an earlier pair" if seen
                                     else f"replaced: drafts written again under {m}")
    key = state.read_json(key_file(), {}) or {}
    used = {p["id"] for p in cur["pairs"]}
    items = {it["id"]: it for it in voice.load()}
    lab = labels.final()
    drafts = {r["id"]: r["text"] for r in rows("drafts.jsonl", run)
              if r["k"] == cur["k"] and r["id"] not in used
              and r["id"] in items and items[r["id"]]["audience"] == aud}
    log(f"  ok    dropped {len(old)} {aud} pair{'' if len(old) == 1 else 's'}, kept in the files, marked")
    # A batch drawn by 'voice validate --batch', all of it drafted: its pairs
    # are what there is, even short of a full batch; nothing more is held
    # back, as that would change the pool the guide was written from.
    entry = _batch_entry(aud, run)
    in_batch = entry is not None
    bids = set(entry or [])
    whole = in_batch and bids <= set(drafts)
    if (len(drafts) >= n_ or whole) and drafts:
        before = len(cur["pairs"])
        _draw(cur, key, used, items, lab, drafts, aud, min(n_, len(drafts)))
        new = [p["pair"] for p in cur["pairs"][before:]]
        log(f"  ok    drew {len(new)} {aud} pairs from {m} drafts of messages never paired: {new[0]} to {new[-1]}")
    state.write_json(key_file(), key)
    state.write_json(pairs_file(), cur)
    if len(drafts) < n_ and not whole:
        judged = {r["id"] for r in rows("judge.jsonl", run)}
        waiting = {i for i, a in _COUNTED["aud"].items() if a == aud and i not in judged and i not in used}
        need = n_ - len(drafts) - len(waiting)
        log(f"  --    {len(drafts)} {aud} message{'' if len(drafts) == 1 else 's'} drafted under {m} and "
            f"never paired, {len(waiting)} held back and not drafted yet; a batch is {n_}")
        if need > 0:
            pool.holdout_more(aud, need, log=log)
        else:
            log(f"  --    run 'voice validate' to draft them, then 'voice pairs --more {aud}'")
    return cur


def judge_review(log=print):
    """The judge's 20 worst-scored drafts and 10 random others, for the best
    count, drawn once per run."""
    p = vdir("judge-review.json")
    run = run_no()
    cur = state.read_json(p, None)
    if cur and cur["run"] == run:
        return cur
    k = best_count(run)
    rl = rule()
    WORST_, RANDOM_ = rl["judge_review_worst"], rl["judge_review_random"]
    js = [r for r in rows("judge.jsonl", run) if r["k"] == k]
    js.sort(key=lambda r: (r["score"], r["id"]))
    worst = js[:WORST_]
    rest = js[WORST_:]
    random.Random(f"judge-review-{run}").shuffle(rest)
    items = {it["id"]: it for it in voice.load()}
    drafts = {r["id"]: r["text"] for r in rows("drafts.jsonl", run) if r["k"] == k}
    cur = {"run": run, "k": k, "items": [
        {"id": r["id"], "why": w, "score": r["score"], "reason": r["reason"],
         "audience": items[r["id"]]["audience"], "real": items[r["id"]]["text"],
         "draft": drafts.get(r["id"], ""), "context": voice.render_context(items[r["id"]]["before"], 3000)}
        for w, group in (("worst", worst), ("random", rest[:RANDOM_])) for r in group if r["id"] in items]}
    state.write_json(p, cur)
    return cur


def answer(kind, ref, **fields):
    """Write one answer as it is given: pair id and answer only, plus the
    pair's audience and purposes and the time (PLAN §3.7)."""
    row = {"run": run_no(), "kind": kind, "ref": ref, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    row.update(fields)
    append_answer(row)
    return row


def append_answer(row):
    with open(answers_file(), "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def answers(run=None, kind="pair"):
    """{ref: newest answer row} for a run."""
    run = run_no() if run is None else run
    out = {}
    for r in state.read_jsonl(answers_file()):
        if r["run"] == run and r["kind"] == kind:
            out[r["ref"]] = {**out.get(r["ref"], {}), **r}
    return out


def _dirichlet(rnd, a):
    xs = [rnd.gammavariate(x, 1) for x in a]
    s = sum(xs)
    return [x / s for x in xs]


def _spot_draws(c, seed):
    """Draws of the spotting rate (right minus wrong share) for counts c."""
    rnd = random.Random(seed)
    return sorted(r - w for r, w, _ in (_dirichlet(rnd, [1 + c.get("right", 0), 1 + c.get("wrong", 0),
                                                          1 + c.get("cant", 0)]) for _ in range(DRAWS)))


def report(run=None):
    run = run_no() if run is None else run
    pr = state.read_json(pairs_file(), None)
    if not pr or pr["run"] != run:
        return {"run": run, "pairs": 0}
    from . import settings
    rl = rule()
    since = settings.record_pass_rule(run)
    key = state.read_json(key_file(), {}) or {}
    ans = answers(run)
    per = {"all": Counter()}
    for p in active(pr):
        a = ans.get(p["pair"])
        if not a or "pick" not in a:
            continue
        res = "cant" if a["pick"] == "cant" else ("right" if a["pick"] == key[p["pair"]] else "wrong")
        for k in ("all", "aud:" + p["audience"]) + tuple("pur:" + x for x in p["purposes"]):
            per.setdefault(k, Counter())[res] += 1
    live = {p["pair"]: p for p in active(pr)}
    grades = [a["grade"] for r, a in ans.items() if r in live and a.get("grade")]
    by_aud = {}
    for r, a in ans.items():
        if r in live and a.get("grade"):
            by_aud.setdefault(live[r]["audience"], []).append(a["grade"])
    c = per["all"]
    n = sum(c.values())
    spot = _spot_draws(c, f"report-{run}-{n}")
    sure = round(sum(1 for s in spot if s <= rl["overall_bar"]) / len(spot), 3)
    blind_ok = n > 0 and sure >= rl["sure"]
    share4 = lambda xs: sum(1 for x in xs if x >= 4) / len(xs) if xs else 0.0
    grades_aud = {a: round(share4(xs), 3) for a, xs in sorted(by_aud.items())}
    grades_ok = (bool(grades) and share4(grades) >= rl["grades_all"] and 1 not in grades
                 and all(v >= rl["grades_audience"] for v in grades_aud.values()))
    audiences = {}
    for k, v in sorted(per.items()):
        if k.startswith("aud:"):
            m = sum(v.values())
            ds = _spot_draws(v, f"report-{run}-{k}-{m}")
            p = round(sum(1 for s in ds if s <= rl["audience_bar"]) / len(ds), 3)
            audiences[k[4:]] = {"pairs": m, "sure": p, "grades_4_up": grades_aud.get(k[4:]),
                                "state": "ok" if p >= rl["sure"] else "more" if p >= rl["unsure"] else "failed"}
    more = [a for a, v in audiences.items() if v["state"] == "more"]
    failed = [a for a, v in audiences.items() if v["state"] == "failed"]
    done = n == len(active(pr)) and len(grades) == len(active(pr))
    return {
        "run": run, "k": pr["k"], "pairs": len(active(pr)), "dropped": sorted(pr.get("dropped", {})), "answered": n, "graded": len(grades),
        "counts": {k: dict(v) for k, v in per.items()},
        "spotting": {"estimate": round((c["right"] - c["wrong"]) / n, 3) if n else None,
                     "low": round(spot[int(0.025 * len(spot))], 3), "high": round(spot[int(0.975 * len(spot))], 3)},
        "confidence_pass_holds": sure, "audiences": audiences,
        "grades": dict(Counter(grades)), "grades_4_up": round(share4(grades), 3), "blind_ok": blind_ok,
        "grades_ok": grades_ok, "more_pairs_for": more, "failed_audiences": failed, "done": done,
        "passed": done and blind_ok and grades_ok and not more and not failed,
        "pass_rule": rl, "pass_rule_from_run": since,
        "right_pairs": [p["pair"] for p in active(pr)
                        if ans.get(p["pair"], {}).get("pick") == key.get(p["pair"])],
    }
