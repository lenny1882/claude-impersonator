"""Voice validation (PLAN §3.5, §3.7).

For every held-back message, a brief of what it says, in neutral words and
none of its own (Sonnet 5.5), is written first. Drafts are
written from the brief, the context, the audience and the purposes by the
drafting model (Opus 5.5), with 3, 5 and 8 exemplars, as voice-runtime
drafts from a brief.
The judge (Fable 5.2, not the drafting model) sees the brief too,
compares each draft with the real message and scores it 1 to 5. The count
with the best mean score is the build's exemplar count.

Only held-back messages the exemplar pool's rule would keep are drafted,
scored or paired (counted()); the rest are held back but count for nothing.

Rows carry METHOD; rows written without a brief have none and are ignored,
so a run resumes only its own method.

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
both in the state. On top of the pairs the owner reviews the judge's 20
worst-scored drafts and 10 random ones.

Pass: right picks minus wrong picks no more than 10% of
pairs ("can't tell" counts as neither); at least 80% of drafts graded 4 or
higher and none at 1. Overall, reported per audience; an audience where
right picks beat wrong picks by 3 or more gets 12 more pairs before the
result stands.
"""

import json
import os
import random
import time
from collections import Counter, defaultdict

from . import guide, labels, model, pool, state, voice
from .index import VOICE_SOURCES

COUNTS = (3, 5, 8)
# "brief-2": the drafter says only what the brief says, lengths per purpose,
# and the brief says how a message addresses someone.
# "brief-5": the never-say list without pseudonym words, contraction tails,
# emoji names or placeholders.
METHOD = "brief-5"
PAIRS_PER_AUDIENCE = 12
WORST, RANDOM = 20, 10

DRAFT_SYSTEM = """You draft a message as self-01, in self-01's own voice, following the guide below
and matching the example messages self-01 really wrote. Names are pseudonyms (colleague-07,
client-03, product-04); keep using them. [code] stands for code left out: write [code] where
self-01 would paste code. Reply with the message text only: no preamble, no quotation marks.

"""

DRAFT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["text"],
                "properties": {"text": {"type": "string"}}}

BRIEF_SYSTEM = """You write the brief for one message: what it says, never how it says it. The
writer is self-01; names are pseudonyms (colleague-07, client-03, product-04); keep them.
[url], [email], [code] and [REDACTED:...] stand for removed details; keep them where the
message has them. List each point the message makes, in the order it makes them, one short
note per line, in plain neutral words of your own: facts, questions, requests, decisions,
names, numbers, dates. Never quote or echo its wording, and say nothing about its length,
tone, punctuation, capitalisation, emoji or sign-off; where it greets, jokes or thanks, say
so in a few words of your own ("a greeting", "a joke about the train being late"). Where it
addresses someone, say how: an @mention, or their name in the text; where it names no one,
say nothing about who it is for. Add nothing the message doesn't say."""

BRIEF_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["brief"],
                "properties": {"brief": {"type": "string"}}}

# The one 1-5 scale: the judge's prompt and the owner's grade buttons both use it.
GRADES = {5: "indistinguishable from self-01's own", 4: "sendable as is or with a trivial edit",
          3: "content right, needs rewording", 2: "voice or content wrong", 1: "of no use"}

JUDGE_SYSTEM = """You judge drafts written in one person's voice. The person is self-01; names
are pseudonyms. You see the conversation, the message self-01 really wrote next, a brief of
what that message says, and several drafts written from the brief without seeing the
message. Score each draft 1 to 5 for how far self-01 would send it as is, judged against the
real message: mostly voice (wording, length, tone, punctuation, capitalisation), and whether
it says what the brief says, nothing dropped or added.
""" + "\n" + " ".join(f"{n}: {GRADES[n]}." for n in (5, 4, 3, 2, 1))

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

def brief_prompt(it):
    ctx = voice.render_context(it["before"], 2000) or "(no earlier messages)"
    return (f"Conversation before it:\n{ctx}\n\nThe message:\n{voice.without_code(it['text'], it.get('tags') or [])}"
            f"\n\nWrite its brief.")


def draft_prompt(it, purposes, exs, brief):
    ctx = voice.render_context(it["before"], 4000) or "(no earlier messages)"
    shown = "\n\n---\n\n".join(
        (f"(answering: {e['answered'][:300]})\n" if e["answered"] else "") + e["text"] for e in exs)
    return (f"Examples of messages self-01 wrote to this audience:\n\n{shown}\n\n"
            f"Conversation so far ({'Bitbucket pull request' if it['source'] == 'bitbucket' else 'Slack'}):\n{ctx}\n\n"
            f"What the message has to say (a brief, not its wording):\n{brief}\n\n"
            f"Write self-01's next message, saying what the brief says in self-01's own words, and "
            f"nothing more: no question, offer, mention, pleasantry or sign-off the brief doesn't list. "
            f"Audience: {it['audience']}. Purposes, in order: {', '.join(purposes)}.")


def read_lines(name):
    return list(state.read_jsonl(vdir(name)))


def rows(name, run):
    """A file's rows for this run and METHOD, for held-back messages that count."""
    ok = counted()
    return [r for r in read_lines(name) if r["run"] == run and r.get("method") == METHOD and r["id"] in ok]


_COUNTED = {}


def counted():
    """The held-back messages validation counts: those the exemplar pool's own
    rule would keep (at least min_words words, under max_code_share code),
    with at least min_words words left after code becomes [code] and links
    and [url], as the pairs page shows them; so a "^" or a link, the same on
    both sides, scores and pairs nothing
    Cached per holdout file and corpus change."""
    hf = pool.holdout_file()
    stamp = tuple(os.path.getmtime(f) if os.path.exists(f) else 0
                  for f in [hf] + [state.anon_file(s) for s in VOICE_SOURCES] + [state.path("voice-config.json")])
    if _COUNTED.get("stamp") != stamp:
        by_id = {it["id"]: it for it in voice.load()}
        c = pool.config()
        _COUNTED.update(stamp=stamp, ids={i for i in pool.held() if i in by_id and pool.keep(by_id[i], c)
                                          and voice.shown_words(by_id[i]["text"]) >= c["min_words"]})
    return _COUNTED["ids"]


def append(name, rows):
    with open(vdir(name), "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def drafts_and_judge(counts=COUNTS, limit=None, log=print):
    import numpy as np
    voice.require_sendable()
    from . import voicestats
    g = guide.assemble("validation")
    items = voice.load()
    by_id = {it["id"]: it for it in items}
    lab = labels.final()
    ok = counted()
    hold = [by_id[i] for i in sorted(pool.held()) if i in by_id and i in lab and i in ok]
    if not hold:
        raise SystemExit("voice-decision-pipeline: no holdouts; run 'voice holdout' first")
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
        system = DRAFT_SYSTEM + guide.render(g, stats, it["audience"], ps)
        try:
            if it["id"] not in briefs:
                ans = model.call("brief", BRIEF_SYSTEM, brief_prompt(it), BRIEF_SCHEMA, log=log)
                briefs[it["id"]] = ans["brief"]
                append("briefs.jsonl", [{"run": run, "method": METHOD, "id": it["id"], "brief": ans["brief"]}])
            brief = briefs[it["id"]]
            for k in counts:
                if (it["id"], k) in have:
                    continue
                exs = search(ex, m, np.asarray(qv, "float32"), it["audience"], ps, k)
                ans = model.call("drafter", system, draft_prompt(it, ps, exs, brief), DRAFT_SCHEMA, log=log)
                append("drafts.jsonl", [{"run": run, "method": METHOD, "id": it["id"], "k": k, "text": ans["text"],
                                         "exemplars": [e["id"] for e in exs]}])
                have.add((it["id"], k))
            ds = {r["k"]: r["text"] for r in rows("drafts.jsonl", run) if r["id"] == it["id"]}
            ks = [k for k in counts if k in ds]
            jp = (f"Conversation:\n{voice.render_context(it['before'], 4000) or '(none)'}\n\n"
                  f"The message self-01 really wrote:\n{it['text']}\n\n"
                  f"The brief the drafts were written from:\n{brief}\n\n" +
                  "\n\n".join(f"Draft {i}:\n{ds[k]}" for i, k in enumerate(ks, 1)) +
                  f"\n\nScore drafts 1 to {len(ks)}.")
            ans = model.call("judge", JUDGE_SYSTEM, jp, JUDGE_SCHEMA, log=log)
        except model.UsageLimit as e:
            log(f"  stop  usage limit after {n - 1} messages: {e}; run the same command again to resume")
            return 6
        except model.CallFailed as e:
            log(f"  skip  {it['id']}: {e}")
            continue
        sc = {x["draft"]: x for x in ans["scores"]}
        append("judge.jsonl", [{"run": run, "method": METHOD, "id": it["id"], "k": k, "score": sc[i]["score"],
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
    key = state.read_json(key_file(), {}) if cur["pairs"] else {}
    used = {p["id"] for p in cur["pairs"]}
    items = {it["id"]: it for it in voice.load()}
    lab = labels.final()
    drafts = {r["id"]: r["text"] for r in rows("drafts.jsonl", run) if r["k"] == k}
    for aud in ([audience] if audience else voice.CORPUS_AUDIENCES):
        _draw(cur, key, used, items, lab, drafts, aud, PAIRS_PER_AUDIENCE)
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


def judge_review(log=print):
    """The judge's 20 worst-scored drafts and 10 random others, for the best
    count, drawn once per run."""
    p = vdir("judge-review.json")
    run = run_no()
    cur = state.read_json(p, None)
    if cur and cur["run"] == run:
        return cur
    k = best_count(run)
    js = [r for r in rows("judge.jsonl", run) if r["k"] == k]
    js.sort(key=lambda r: (r["score"], r["id"]))
    worst = js[:WORST]
    rest = js[WORST:]
    random.Random(f"judge-review-{run}").shuffle(rest)
    items = {it["id"]: it for it in voice.load()}
    drafts = {r["id"]: r["text"] for r in rows("drafts.jsonl", run) if r["k"] == k}
    cur = {"run": run, "k": k, "items": [
        {"id": r["id"], "why": w, "score": r["score"], "reason": r["reason"],
         "audience": items[r["id"]]["audience"], "real": items[r["id"]]["text"],
         "draft": drafts.get(r["id"], ""), "context": voice.render_context(items[r["id"]]["before"], 3000)}
        for w, group in (("worst", worst), ("random", rest[:RANDOM])) for r in group if r["id"] in items]}
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


def report(run=None):
    run = run_no() if run is None else run
    pr = state.read_json(pairs_file(), None)
    if not pr or pr["run"] != run:
        return {"run": run, "pairs": 0}
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
    live = {p["pair"] for p in active(pr)}
    grades = [a["grade"] for r, a in ans.items() if r in live and a.get("grade")]
    c = per["all"]
    n = sum(c.values())
    rnd = random.Random(f"report-{run}-{n}")
    draws = [_dirichlet(rnd, [1 + c["right"], 1 + c["wrong"], 1 + c["cant"]]) for _ in range(4000)]
    spot = sorted(r - w for r, w, _ in draws)
    blind_ok = n > 0 and c["right"] - c["wrong"] <= 0.1 * n
    grades_ok = bool(grades) and sum(1 for x in grades if x >= 4) >= 0.8 * len(grades) and 1 not in grades
    more = [k[4:] for k, v in per.items() if k.startswith("aud:") and v["right"] - v["wrong"] >= 3]
    done = n == len(active(pr)) and len(grades) == len(active(pr))
    return {
        "run": run, "k": pr["k"], "pairs": len(active(pr)), "dropped": sorted(pr.get("dropped", {})), "answered": n, "graded": len(grades),
        "counts": {k: dict(v) for k, v in per.items()},
        "spotting": {"estimate": round((c["right"] - c["wrong"]) / n, 3) if n else None,
                     "low": round(spot[int(0.025 * len(spot))], 3), "high": round(spot[int(0.975 * len(spot))], 3)},
        "confidence_pass_holds": round(sum(1 for s in spot if s <= 0.1) / len(spot), 3),
        "grades": dict(Counter(grades)), "blind_ok": blind_ok, "grades_ok": grades_ok,
        "more_pairs_for": more, "done": done,
        "passed": done and blind_ok and grades_ok and not more,
        "right_pairs": [p["pair"] for p in active(pr)
                        if ans.get(p["pair"], {}).get("pick") == key.get(p["pair"])],
    }
