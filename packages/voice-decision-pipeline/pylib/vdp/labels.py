"""Purpose labelling and its checks (PLAN §3.3, §3.4).

Two passes over every voice item, each sent anonymised with its context:
the labeller (Sonnet 5.5) and, blind to it, the second model (Opus 5.5, a
different model, not a different prompt). Each gives
every purpose a message carries, in the order they appear. Results go to
labels/<pass>.jsonl, one line per item, written after each batch, so a
stopped pass resumes after the last finished batch.

The labelling prompt is fixed here, plus labelling-notes.md in the state:
whatever is written there is added to the prompt, which is how the prompt
is changed between passes (never during one) after a failed label check or
a purpose the two models disagree on too often. `label --redo <purpose,...>`
sends again the items either model gave one of those purposes.

Checks:
  - The owner's sample: 120 labeller-labelled items spread across audiences and
    purposes, each marked right or wrong (and corrected) on the review page.
    Over 6 wrong of 120 fails: the prompt is changed, the
    pass rerun and a fresh sample drawn (`label --new-sample`).
  - Disagreements: every item where the two passes differ is recorded with
    both label sets (labels/disagreements.jsonl); the rate per purpose is
    measured over all of them; a fixed sample of 60 comes to the owner to grade.

An item's final purposes are the owner's correction where they made one, else the
labeller's.
"""

import hashlib
import json
import random
from collections import Counter, defaultdict

from . import model, state, voice

BATCH = 20
SAMPLE = 120
SAMPLE_MAX_WRONG = 6
DISAGREE_SAMPLE = 60
PASSES = {"labeller": "labeller", "second": "second"}

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["n", "purposes"],
        "properties": {
            "n": {"type": "integer"},
            "purposes": {"type": "array", "minItems": 1,
                         "items": {"type": "string", "enum": list(voice.PURPOSES)}}}}}},
}


def notes_file():
    return state.path("labelling-notes.md")


def system_prompt():
    lines = "\n".join(f"- {k}: {v}" for k, v in voice.PURPOSES.items())
    base = f"""You label the purposes of messages written by one person, self-01, at work.
Names in the text are pseudonyms (colleague-07, client-03, product-04); [url], [email],
[phone] and [REDACTED:...] stand for removed details. Each numbered item is one message by
self-01, shown with the conversation before it and, where there is one, after it.

For each item give every purpose the message carries, using only these ids, in the order
they appear in the message. A message can carry several. Use "other" only when none fits.
{lines}

Label the message itself, not the context; the context only shows what it answers."""
    try:
        with open(notes_file(), encoding="utf-8") as f:
            notes = f.read().strip()
    except FileNotFoundError:
        notes = ""
    return base + (f"\n\nFurther notes:\n{notes}" if notes else "")


def prompt_version():
    return hashlib.sha1(system_prompt().encode()).hexdigest()[:12]


def item_prompt(n, it):
    before = voice.render_context(it["before"], 2500)
    after = voice.render_context(it["after"], 800, keep="start")
    return (f"### Item {n} (audience: {it['audience']})\n"
            + (f"Before:\n{before}\n" if before else "")
            + f"Message by self-01:\n{it['text']}\n"
            + (f"After:\n{after}\n" if after else ""))


def labels_file(which):
    return state.path("labels", f"{which}.jsonl")


def read(which):
    """{id: line} for a pass, the newest line per id winning."""
    out = {}
    for r in state.read_jsonl(labels_file(which)):
        out[r["id"]] = r
    return out


def run(which, redo=(), log=print):
    if which not in PASSES:
        raise SystemExit(f"voice-decision-pipeline: unknown pass {which}")
    voice.require_sendable()
    items = voice.load()
    done = read(which)
    redo = set(redo)
    if redo:
        both = {**read("labeller")}
        other = read("second")
        hit = {i for src in (both, other) for i, r in src.items() if redo & set(r["purposes"])}
        todo = [it for it in items if it["id"] in hit]
    else:
        todo = [it for it in items if it["id"] not in done]
    log(f"== label {which}: {len(todo)} of {len(items)} items to send, "
        f"{(len(todo) + BATCH - 1) // BATCH} calls, prompt {prompt_version()}")
    system = system_prompt()
    pv = prompt_version()
    sent = 0
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        prompt = "\n".join(item_prompt(n + 1, it) for n, it in enumerate(chunk))
        prompt += f"\nGive the purposes for items 1 to {len(chunk)}."
        try:
            ans = model.call(PASSES[which], system, prompt, SCHEMA, log=log)
        except model.UsageLimit as e:
            log(f"  stop  usage limit after {sent} items: {e}; run the same command again to resume")
            return 6
        got = {x["n"]: x["purposes"] for x in ans["items"]}
        lines = []
        for n, it in enumerate(chunk, 1):
            if n in got:
                ps = list(dict.fromkeys(got[n]))
                lines.append({"id": it["id"], "purposes": ps, "prompt": pv, "model": model.MODELS[PASSES[which]]})
        with open(labels_file(which), "a", encoding="utf-8") as f:
            for r in lines:
                f.write(json.dumps(r, sort_keys=True) + "\n")
        sent += len(chunk)
        missing = len(chunk) - len(lines)
        log(f"  batch {i // BATCH + 1}: {len(lines)} labelled" + (f", {missing} left for the next run" if missing else "")
            + f" ({sent}/{len(todo)})")
    log(f"  ok    label {which}: {len(read(which))} items labelled")
    return 0


# -- the owner's checks ------------------------------------------------------

def check_file():
    return state.path("label-check.json")


def disagree_grades_file():
    return state.path("disagreement-grades.json")


def corrections():
    """{id: purposes} the owner gave on either check page."""
    out = {}
    for src in (state.read_json(check_file(), {}) or {}).get("answers", {}), \
            (state.read_json(disagree_grades_file(), {}) or {}).get("answers", {}):
        for i, a in src.items():
            if a.get("purposes"):
                out[i] = a["purposes"]
    return out


def final():
    """{id: purposes}: the owner's correction, else the labeller's."""
    out = {i: r["purposes"] for i, r in read("labeller").items()}
    out.update(corrections())
    return out


def spread_sample(ids_labels, n, seed):
    """n ids spread across audiences and purposes: round-robin over the
    (audience, purpose) cells, every label of an item counting."""
    rnd = random.Random(seed)
    cells = defaultdict(list)
    for i, (aud, ps) in ids_labels.items():
        for p in ps:
            cells[(aud, p)].append(i)
    for v in cells.values():
        rnd.shuffle(v)
    keys = sorted(cells)
    rnd.shuffle(keys)
    out, seen = [], set()
    while len(out) < n and any(cells[k] for k in keys):
        for k in keys:
            while cells[k] and cells[k][-1] in seen:
                cells[k].pop()
            if cells[k] and len(out) < n:
                i = cells[k].pop()
                seen.add(i)
                out.append(i)
    return out


def draw_sample(new=False):
    """The label-check sample, drawn once, again only with new=True."""
    cur = state.read_json(check_file(), None)
    if cur and not new:
        return cur
    lab = read("labeller")
    aud = {it["id"]: it["audience"] for it in voice.load()}
    pool = {i: (aud[i], r["purposes"]) for i, r in lab.items() if i in aud}
    if not pool:
        raise SystemExit("voice-decision-pipeline: nothing labelled yet; run 'voice label' first")
    n = (cur or {}).get("round", 0) + 1
    ids = spread_sample(pool, SAMPLE, seed=f"label-check-{n}")
    d = {"round": n, "prompt": prompt_version(), "ids": ids, "answers": {}}
    if cur:
        d["previous"] = (cur.get("previous") or []) + [{k: cur[k] for k in ("round", "prompt", "ids", "answers")}]
    state.write_json(check_file(), d)
    return d


def check_result():
    d = state.read_json(check_file(), None)
    if not d:
        return {"drawn": False}
    ans = {i: a for i, a in d["answers"].items() if i in set(d["ids"])}
    wrong = sum(1 for a in ans.values() if a.get("verdict") == "wrong")
    return {"drawn": True, "round": d["round"], "size": len(d["ids"]), "answered": len(ans),
            "wrong": wrong, "done": len(ans) == len(d["ids"]),
            "passed": len(ans) == len(d["ids"]) and wrong <= SAMPLE_MAX_WRONG * len(d["ids"]) / SAMPLE}


def disagreements():
    a, b = read("labeller"), read("second")
    out = []
    for i in sorted(set(a) & set(b)):
        if a[i]["purposes"] != b[i]["purposes"] and set(a[i]["purposes"]) != set(b[i]["purposes"]):
            out.append({"id": i, "labeller": a[i]["purposes"], "second": b[i]["purposes"]})
    return out


def disagreement_rates():
    """{purpose: {"either": n, "differ": n, "rate": f}} over every item both
    passes labelled: an item counts for a purpose where either gave it, and
    differs where only one did."""
    a, b = read("labeller"), read("second")
    either, differ = Counter(), Counter()
    for i in set(a) & set(b):
        x, y = set(a[i]["purposes"]), set(b[i]["purposes"])
        for p in x | y:
            either[p] += 1
            if (p in x) != (p in y):
                differ[p] += 1
    return {p: {"either": either[p], "differ": differ[p],
                "rate": round(differ[p] / either[p], 3) if either[p] else 0.0}
            for p in voice.PURPOSES}


def write_disagreements():
    ds = disagreements()
    state.write_jsonl(state.path("labels", "disagreements.jsonl"), ds)
    g = state.read_json(disagree_grades_file(), None)
    if not g:
        rnd = random.Random("disagreements-1")
        ids = [d["id"] for d in ds]
        rnd.shuffle(ids)
        state.write_json(disagree_grades_file(), {"ids": sorted(ids[:DISAGREE_SAMPLE]), "answers": {}})
    return ds


def summary():
    lab, sec = read("labeller"), read("second")
    return {"labelled": len(lab), "second": len(sec), "check": check_result(),
            "disagreements": len(disagreements()) if lab and sec else 0,
            "rates": disagreement_rates() if lab and sec else {}}
