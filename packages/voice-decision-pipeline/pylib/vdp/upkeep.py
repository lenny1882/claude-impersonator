"""Upkeep of the voice model from the drafts Claude wrote in the owner's voice
(PLAN §3.8).

voice-runtime records each draft, the version the owner approved and each
draft the owner discarded (its drafts.jsonl). The pipeline reads those
records from upkeep/records.jsonl in its state: `upkeep import <file>` adds a
machine's drafts.jsonl there, and under PLAN §5 the build machine's S3
reader fills the same file.

Each `voice upkeep` (and each `voice build`, before anything else):
  matching     a draft's sent version is the owner's message in the draft's
               conversation (Slack conversation, Bitbucket PR) posted within
               upkeep.window_minutes after approval, closest in wording to
               the approved text. Jira isn't extracted, so a Jira draft, and
               any draft with no match, has the approved text as its last
               known version.
  near-copies  an owner's message in the draft's conversation, sent at any
               time after the draft was written, whose wording is at least upkeep.near_copy_min alike to
               a draft's first or approved text.
  edits        a draft is edited when its first version and its last known
               version differ in words, punctuation or capitals, once source
               encodings are undone (normalise) and spacing ignored.
  holding out  matched and near-copy messages are left out of the voice
               items (voice.load), so out of the exemplar pool, the guide's
               input, the statistics and validation, until the owner accepts
               them on the review page; accepted, they count everywhere with
               the purposes the owner confirmed there.
  due          a review session is due once upkeep.due_items edited drafts
               await one, or upkeep.due_days have passed since the last with
               at least one item to review; with nothing to review the clock
               starts again. upkeep/due.json holds the state the SessionStart
               line (bin/voice-decision-pipeline-due) reads.
  suggestions  when a session is due, local counts of the word-level edits
               across its edited drafts, and one call to the upkeep model
               with the counts and the anonymised pairs, give rule lines for
               the owner's rules file: each edit recurring in at least
               upkeep.recur_min drafts, under one audience's section when
               every draft it came from went to that audience.

Draft texts hold real names: `anonymise` writes their anonymised copy to
anon/drafts.jsonl with the corpus, the leak check reads it, and only that copy
reaches a model or the review page.
"""

import datetime
import difflib
import hashlib
import json
import re
from collections import Counter, defaultdict

from . import state

# The defaults; the state's settings.json "upkeep" section wins (settings.py).
WINDOW_MINUTES = 60
NEAR_COPY_MIN = 0.8
RECUR_MIN = 3
DUE_ITEMS = 20
DUE_DAYS = 28
PAIRS_MAX = 60
PHRASE_MAX = 6

SYSTEM = """You turn the edits one person, self-01, made to drafts written in their voice into
rules for their own rules file. Names are pseudonyms (colleague-07, client-03); [code] stands for
code left out. You are shown counts of the word-level edits that recur across the drafts, worked
out without you, then each draft beside the version self-01 actually sent or approved.

Write one rule line for each edit that recurs in at least {recur_min} of the drafts: short,
specific and checkable, saying what to do or not do in a draft, the way self-01 would write it in
their own rules file. A recurring edit the counts can't show (cutting reasons, merging sentences,
a changed order) counts too, if you can see it in at least {recur_min} drafts. No rule about a
particular person, client, product or project, and nothing you cannot see in the pairs. Name the
drafts each rule comes from by their numbers."""

PROMPT = """Recurring word-level edits (edit: drafts it is in; audiences):
{counts}

The drafts and what self-01 sent or approved:

{pairs}

Write the rule lines."""

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["suggestions"],
          "properties": {"suggestions": {"type": "array", "items": {
              "type": "object", "additionalProperties": False, "required": ["line", "drafts"],
              "properties": {"line": {"type": "string"},
                             "drafts": {"type": "array", "items": {"type": "integer"}}}}}}}

DRAFT_FIELDS = ("id", "ts", "kind", "audience", "purposes", "destination", "text", "status")


def cfg():
    from . import settings
    return settings.get("upkeep")


def path(name):
    return state.path("upkeep", name)


def records_file():
    return path("records.jsonl")


def anon_file():
    return state.path("anon", "drafts.jsonl")


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(ts):
    """A record's or message's time, as UTC; None if it has none."""
    if not ts:
        return None
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(datetime.timezone.utc)
    except ValueError:
        return None


# --- the records ---------------------------------------------------------------

def _key(r):
    return hashlib.sha256(json.dumps([r.get(k) for k in DRAFT_FIELDS], ensure_ascii=False).encode()).hexdigest()


def import_records(src, log=print):
    """Add a drafts.jsonl's records to records.jsonl, each once."""
    have = {_key(r): r for r in state.read_jsonl(records_file())}
    added = bad = 0
    with open(src, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if not isinstance(r, dict) or r.get("kind") not in ("draft", "final") or not r.get("id") \
                    or not isinstance(r.get("text"), str) or not parse(r.get("ts")):
                bad += 1
                continue
            k = _key(r)
            if k not in have:
                have[k] = r
                added += 1
    state.write_jsonl(records_file(), sorted(have.values(), key=lambda r: (r["ts"], r["id"], r["kind"])))
    log(f"  ok    {added} new draft records from {src}, {len(have)} in all"
        + (f"; {bad} lines that aren't draft records left out" if bad else ""))
    return added


def drafts():
    """{draft id: {id, audience, purposes, destination, ts, first, final,
    status, final_ts}}: each draft's first text and its latest final record
    (status approved or discarded; drafted while there is none)."""
    out = {}
    for r in sorted(state.read_jsonl(records_file()), key=lambda r: r.get("ts") or ""):
        i = r.get("id")
        if not i:
            continue
        if r.get("kind") == "draft" and i not in out:
            out[i] = {"id": i, "audience": r.get("audience"), "purposes": list(r.get("purposes") or []),
                      "destination": r.get("destination") or "other", "ts": r.get("ts"),
                      "first": r.get("text") or "", "final": None, "status": "drafted", "final_ts": None}
        elif r.get("kind") == "final" and i in out:
            out[i].update(final=r.get("text") or "", status=r.get("status") or "approved", final_ts=r.get("ts"))
    return out


def conversation(destination):
    """(source, corpus conversation id) a destination names; None for Jira
    and other (never extracted)."""
    if destination.startswith("slack:"):
        return "slack", destination[len("slack:"):]
    if destination.startswith("bitbucket:"):
        return "bitbucket", destination[len("bitbucket:"):]
    return None


# --- comparing texts -------------------------------------------------------------

SLACK_LINK = re.compile(r"<((?:https?|mailto):[^|>]+)\|([^>]*)>")
SLACK_BARE = re.compile(r"<((?:https?|mailto):[^>]+)>")
SLACK_MENTION = re.compile(r"<[@#!][^>]*>")
AT_NAME = re.compile(r"(?<![\w@])@[\w.\-]+")
MD_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!>~|])")
TOKEN = re.compile(r"\w+(?:['’]\w+)*|[^\w\s]")


def normalise(text):
    """The text as compared: Slack's encodings undone (a mention or channel
    link becomes @mention, a link its text or address, &amp; &lt; &gt; their
    characters), Markdown escapes undone, an @name written in a draft becomes
    @mention too, and spacing evened out."""
    t = text or ""
    t = SLACK_LINK.sub(lambda m: m.group(2) or m.group(1), t)
    t = SLACK_BARE.sub(lambda m: m.group(1), t)
    t = SLACK_MENTION.sub("@mention", t)
    t = AT_NAME.sub("@mention", t)
    t = t.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    t = MD_ESCAPE.sub(r"\1", t)
    t = t.translate({0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"'})
    return re.sub(r"\s+", " ", t).strip()


def tokens(text):
    return TOKEN.findall(normalise(text))


def similarity(a, b):
    """How alike two texts are in wording: 0 to 1, over their lower-case
    words and punctuation."""
    ta, tb = [x.lower() for x in tokens(a)], [x.lower() for x in tokens(b)]
    if not ta and not tb:
        return 1.0
    return difflib.SequenceMatcher(None, ta, tb, autojunk=False).ratio()


def edited(first, last):
    return tokens(first) != tokens(last)


def changes(first, last):
    """The set of word-level edits from first to last, each a short
    description: a phrase removed or added (and where), a capital lowered or
    raised, the end mark changed."""
    a, b = tokens(first), tokens(last)
    la, lb = [x.lower() for x in a], [x.lower() for x in b]
    out = set()

    def phrase(xs):
        s = re.sub(r" (?=[^\w\s@\[(\"'])", "", " ".join(xs[:PHRASE_MAX])) + (" …" if len(xs) > PHRASE_MAX else "")
        return s.lower()

    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, la, lb, autojunk=False).get_opcodes():
        if op == "equal":
            for x, y in zip(a[i1:i2], b[j1:j2]):
                if x != y:
                    out.add(f'capital {"lowered" if y == y.lower() else "raised"}: "{x.lower()}"')
            continue
        where = " at the start" if i1 == 0 else " at the end" if i2 == len(a) else ""
        if i2 > i1:
            out.add(f'removed "{phrase(a[i1:i2])}"{where}')
        if j2 > j1:
            out.add(f'added "{phrase(b[j1:j2])}"{where}')
    ea = a[-1] if a and not a[-1][0].isalnum() else "(none)"
    eb = b[-1] if b and not b[-1][0].isalnum() else "(none)"
    if a and b and ea != eb:
        out.add(f"end mark {ea} → {eb}")
    return out


# --- matching ---------------------------------------------------------------------

def owner_messages():
    """{(source, conversation): [corpus record]} of the owner's own messages."""
    from .index import voice_item
    by = defaultdict(list)
    for s in ("slack", "bitbucket"):
        for r in state.read_jsonl(state.corpus_file(s)):
            if voice_item(r):
                by[(s, r.get("conversation"))].append(r)
    return by


def match(log=print):
    """Match every draft to its sent version and near-copies, mark edits,
    and write upkeep/matches.json and upkeep/due.json."""
    from . import inputs
    from .anonymise import anon_id
    c = cfg()
    d = inputs.load(required=False) or {}
    struck = set(d.get("struck_conversations") or [])
    ds = drafts()
    msgs = owner_messages()
    window = datetime.timedelta(minutes=c["window_minutes"])
    out, claimed = {}, {}
    for i, x in ds.items():
        conv = conversation(x["destination"])
        if conv and conv[1] in struck:
            continue
        rec = {k: x[k] for k in ("audience", "purposes", "destination", "status", "ts", "final_ts")}
        rec.update(source=conv[0] if conv else None, sent=None, sent_similarity=None, near=[], edited=False)
        cands = msgs.get(conv, []) if conv else []
        if x["status"] == "approved" and x["final"] is not None:
            t0 = parse(x["final_ts"])
            best = None
            for r in cands:
                t = parse(r.get("ts"))
                if t0 and t and t0 <= t <= t0 + window:
                    sim = similarity(x["final"], r.get("text") or "")
                    if best is None or sim > best[0]:
                        best = (sim, r)
            if best:
                rec["sent"], rec["sent_similarity"] = anon_id(best[1]["id"]), round(best[0], 3)
                rec["sent_real"] = best[1]["id"]
            last = best[1].get("text") if best else x["final"]
            rec["edited"] = edited(x["first"], last)
        t_draft = parse(x["ts"])
        for r in cands:
            a = anon_id(r["id"])
            t = parse(r.get("ts"))
            # A message sent before the draft existed can't be a copy of it.
            if a == rec["sent"] or not t or (t_draft and t < t_draft):
                continue
            sim = max(similarity(x["first"], r.get("text") or ""),
                      similarity(x["final"], r.get("text") or "") if x["final"] else 0)
            if sim >= c["near_copy_min"]:
                rec["near"].append(a)
                if sim > claimed.get(a, (0, None))[0]:
                    claimed[a] = (sim, i)
        out[i] = rec
    # A message near several drafts is shown with the closest only.
    for i, rec in out.items():
        rec["near"] = sorted(a for a in rec["near"] if claimed.get(a, (0, i))[1] == i)
    m = {"built_at": iso(now()), "drafts": out}
    state.write_json(path("matches.json"), m)
    n_sent = sum(1 for r in out.values() if r["sent"])
    n_near = sum(len(r["near"]) for r in out.values())
    n_ed = sum(1 for r in out.values() if r["edited"])
    log(f"  ok    upkeep: {len(out)} drafts, {n_sent} matched to a sent message, {n_near} near-copies, "
        f"{n_ed} edited")
    due(out, log=log)
    return m


def matches():
    return (state.read_json(path("matches.json"), None) or {}).get("drafts", {})


# --- the owner's review ------------------------------------------------------------

def review_file():
    return path("review.json")


def review():
    r = state.read_json(review_file(), None) or {}
    r.setdefault("messages", {})
    r.setdefault("discarded", {})
    r.setdefault("suggestions", {})
    r.setdefault("sessions", [])
    r.setdefault("clock", None)
    return r


def save_review(r):
    state.write_json(review_file(), r)


def reviewed_drafts(r=None):
    r = r or review()
    return {i for s in r["sessions"] for i in s.get("drafts", [])}


def held_messages(m=None):
    """{anonymised message id: draft id} of every matched or near-copy message."""
    m = matches() if m is None else m
    out = {}
    for i, rec in m.items():
        for a in ([rec["sent"]] if rec.get("sent") else []) + list(rec.get("near") or []):
            out.setdefault(a, i)
    return out


def held_ids():
    """The anonymised ids kept out of the voice items: held messages the
    owner hasn't accepted."""
    acc = accepted()
    return {a for a in held_messages() if a not in acc}


def accepted():
    """{anonymised message id: {audience, purposes}} the owner accepted."""
    return {a: {"audience": v.get("audience"), "purposes": v.get("purposes") or []}
            for a, v in review()["messages"].items() if v.get("verdict") == "accepted"}


def pending(m=None, r=None):
    """What the next review session holds: edited drafts not yet in an ended
    session, discarded drafts not yet marked, held messages not yet decided."""
    m = matches() if m is None else m
    r = r or review()
    seen = reviewed_drafts(r)
    ed = sorted(i for i, rec in m.items() if rec.get("edited") and i not in seen)
    disc = sorted(i for i, rec in m.items() if rec.get("status") == "discarded" and i not in r["discarded"])
    msgs = sorted(a for a in held_messages(m) if a not in r["messages"])
    voice_disc = sorted(i for i, v in r["discarded"].items() if v == "voice" and i not in seen)
    return {"edited": ed, "discarded": disc, "messages": msgs, "discarded_voice": voice_disc}


def due(m=None, log=print):
    """Whether a review session is due; written to upkeep/due.json."""
    c = cfg()
    r = review()
    p = pending(m, r)
    t = now()
    clock = parse(r["clock"]) if r["clock"] else None
    if clock is None:
        clock = t
        r["clock"] = iso(t)
        save_review(r)
    edited_n = len(p["edited"]) + len(p["discarded_voice"])
    items = edited_n + len(p["discarded"]) + len(p["messages"])
    days = (t - clock).total_seconds() / 86400
    why = None
    if edited_n >= c["due_items"]:
        why = f"{edited_n} edited drafts"
    elif days >= c["due_days"]:
        if items:
            why = f"{items} items, {int(days)} days since the last session"
        else:
            r["clock"] = iso(t)
            save_review(r)
    line = (f"Voice review session due: {why}. Run: voice-decision-pipeline review" if why else "")
    d = {"due": bool(why), "line": line, "edited": edited_n, "items": items, "checked_at": iso(t),
         "clock": r["clock"]}
    state.write_json(path("due.json"), d)
    if why:
        log(f"  ok    {line}")
    return d


def end_session(log=print):
    """The owner finished a session: its edited drafts are reviewed, the
    clock starts again, and the next session's suggestions are made afresh."""
    r = review()
    p = pending(r=r)
    r["sessions"].append({"ended": iso(now()), "drafts": p["edited"] + p["discarded_voice"]})
    r["clock"] = iso(now())
    r["suggestions"] = {}
    save_review(r)
    state.write_json(path("suggestions.json"), {})
    due()
    log(f"  ok    review session ended: {len(p['edited']) + len(p['discarded_voice'])} drafts reviewed")


# --- suggestions ---------------------------------------------------------------------

def anon_drafts():
    return {r["id"]: r for r in state.read_jsonl(anon_file())}


def anon_messages(ids):
    want, out = set(ids), {}
    for s in ("slack", "bitbucket"):
        for r in state.read_jsonl(state.anon_file(s)):
            if r["id"] in want:
                out[r["id"]] = r
    return out


def session_pairs(m=None, r=None):
    """[(draft id, audience, first, last)] anonymised, for the session's
    edited drafts and its discarded drafts marked as wrong in voice (last
    empty: nothing kept). Drafts whose anonymised copy isn't written yet
    (anonymise not run since they came in) are left out."""
    m = matches() if m is None else m
    p = pending(m, r)
    ad = anon_drafts()
    sent = anon_messages(m[i]["sent"] for i in p["edited"] if m[i].get("sent"))
    out = []
    for i in p["edited"]:
        a = ad.get(i)
        if not a:
            continue
        rec = m[i]
        last = (sent.get(rec["sent"]) or {}).get("text") if rec.get("sent") else a.get("final")
        if last is None:
            continue
        out.append((i, rec["audience"], a.get("first") or "", last))
    for i in p["discarded_voice"]:
        a = ad.get(i)
        if a:
            out.append((i, m[i]["audience"], a.get("first") or "", ""))
    return out


def counts(pairs, recur_min=None):
    """[{edit, drafts, audiences}] for each edit in at least recur_min of the
    pairs, most drafts first."""
    recur_min = cfg()["recur_min"] if recur_min is None else recur_min
    by = defaultdict(set)
    auds = defaultdict(set)
    for i, aud, first, last in pairs:
        for ch in changes(first, last):
            by[ch].add(i)
            auds[ch].add(aud)
    rows = [{"edit": k, "drafts": sorted(v), "audiences": sorted(auds[k])}
            for k, v in by.items() if len(v) >= recur_min]
    return sorted(rows, key=lambda x: (-len(x["drafts"]), x["edit"]))


def section_for(audiences):
    """Where a suggested line goes: one audience's section when every draft
    it came from went to that audience, else the lines for all."""
    s = set(audiences)
    return s.pop() if len(s) == 1 else "all"


def pairs_hash(pairs):
    return hashlib.sha256(json.dumps(sorted(i for i, *_ in pairs)).encode()).hexdigest()[:16]


def suggest(log=print, force=False):
    """The session's suggested rule lines, written to upkeep/suggestions.json.
    Made once per set of drafts; nothing is sent when no edit recurs."""
    from . import inputs, leaks, model, settings
    from .anonmap import Map
    c = cfg()
    pairs = session_pairs()
    h = pairs_hash(pairs)
    cur = state.read_json(path("suggestions.json"), None) or {}
    if cur.get("pairs_hash") == h and not force:
        log(f"  --    suggestions already made for these {len(pairs)} drafts")
        return cur
    rows = counts(pairs)
    out = {"pairs_hash": h, "made_at": iso(now()), "drafts": len(pairs), "counts": rows, "suggestions": []}
    if not rows:
        state.write_json(path("suggestions.json"), out)
        log(f"  ok    no edit recurs in {c['recur_min']} of the {len(pairs)} drafts; nothing sent")
        return out
    from .voice import require_sendable
    require_sendable()
    keep = leaks.clean([[f, l] for _, _, f, l in pairs], inputs.load(), Map.load())
    keep_set = {json.dumps(x, ensure_ascii=False) for x in keep}
    sent = [(i, aud, f, l) for i, aud, f, l in pairs if json.dumps([f, l], ensure_ascii=False) in keep_set]
    if len(sent) < len(pairs):
        log(f"  held  {len(pairs) - len(sent)} draft pairs not sent: the leak check found a name in them")
    sent = sent[-c["pairs_max"]:]
    n_of = {i: n for n, (i, *_) in enumerate(sent, 1)}
    counts_text = "\n".join(
        f"- {r['edit']}: drafts {', '.join(str(n_of[i]) for i in r['drafts'] if i in n_of) or 'none sent'}; "
        f"{', '.join(r['audiences'])}" for r in rows)
    pairs_text = "\n\n".join(
        f"### Draft {n} (to {aud})\nDraft:\n{f}\n\nSent or approved:\n{l or '(discarded: nothing kept)'}"
        for n, (i, aud, f, l) in enumerate(sent, 1))
    system = settings.fill(c["system"], recur_min=c["recur_min"])
    prompt = settings.fill(c["prompt"], counts=counts_text, pairs=pairs_text)
    try:
        ans = model.call("upkeep", system, prompt, SCHEMA, log=log)
    except model.UsageLimit as e:
        log(f"  stop  usage limit: {e}; run the same command again")
        return None
    aud_of = {i: aud for i, aud, *_ in sent}
    by_n = {n: i for i, n in n_of.items()}
    for k, sgg in enumerate(ans["suggestions"], 1):
        ids = sorted({by_n[n] for n in sgg["drafts"] if n in by_n})
        if len(ids) < c["recur_min"] or not sgg["line"].strip():
            continue
        out["suggestions"].append({"key": f"{h}-{k}", "line": sgg["line"].strip(), "drafts": ids,
                                   "section": section_for(aud_of[i] for i in ids)})
    state.write_json(path("suggestions.json"), out)
    log(f"  ok    {len(out['suggestions'])} rule lines suggested from {len(sent)} drafts")
    return out


def add_rule(line, section):
    """Append line to the owner's rules file: under the heading for all
    drafts, or under the audience's own heading, made if it isn't there."""
    from . import guide, settings
    guide.init_rules()
    p = guide.rules_file()
    with open(p, encoding="utf-8") as f:
        lines = f.read().splitlines()
    want = "main" if section == "all" else "audience:" + section
    heads = [(n, re.match(r"^#{1,6}\s+(.*)$", l).group(1).strip().lower())
             for n, l in enumerate(lines) if re.match(r"^#{1,6}\s+", l)]
    heads = [(n, guide.own_section(t), t) for n, t in heads]
    # The lines for all go under "All drafts" where the file has it, not
    # under its title.
    pick = [k for k, (_, sec, t) in enumerate(heads) if sec == want and (want != "main" or t == "all drafts")] \
        or [k for k, (_, sec, _) in enumerate(heads) if sec == want]
    at = None
    for k, (n, sec, _) in enumerate(heads):
        if pick and k == pick[0]:
            end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
            at = end
            while at > n + 1 and not lines[at - 1].strip():
                at -= 1
            break
    bullet = "- " + " ".join(line.split())
    if at is None:
        name = "All drafts" if section == "all" else section
        if section != "all":
            name = next((a["name"] for a in settings.audiences() if a["slug"] == section), section)
        lines += ["", f"## {name}", "", bullet]
    else:
        lines.insert(at, bullet)
    state.write_text(p, "\n".join(lines) + "\n")
