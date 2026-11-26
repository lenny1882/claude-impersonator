"""Decision extraction (PLAN §4.9): from the anonymised copies, the units the
extraction passes read, and the prompt they read them with.

A unit is one stretch of a conversation read as a whole, so a decision that
spreads over several messages (a question, a discussion, a choice) is one
case:
  transcripts  a candidate message of the owner's and the next
               decisions.after messages of the same session (with the Claude
               reply before each); candidates inside that stretch are read in
               the same unit
  slack        a thread, or an unthreaded message with its context window
  bitbucket    a PR's description and comments
  gsd          one record: a STATE.md decision, a CONTEXT.md decision with
               its discuss session where one is found, or a SUMMARY.md
               deviation entry
A unit starts only from the owner's own message; everyone else's is context.

Candidates: every GSD record and AskUserQuestion answer; an owner's reply to
a Claude reply offering two or more numbered choices and ending in a
question; and any owner's message, with the Claude reply or the message it
answers, matching the filter's wording (decisions.filter). The rest of the
owner's messages are the pool the catch-rate sample is drawn from.

Nothing here is sent: the extraction passes refuse to run until the owner
has approved this prompt, the kinds' definitions and the case fields on the
review page (prompt_version, approved()).
"""

import hashlib
import json
import random
import re
from collections import defaultdict

from . import state

KINDS = {
    "libraries-tooling": ("libraries and tooling: which package, framework, service SDK or tool to use, add, "
                          "keep, upgrade, replace or drop, including build and development tools"),
    "code-structure": ("code structure: where code lives, naming, patterns, how modules and files split, and "
                       "the interfaces between modules inside one service"),
    "test-approach": ("test approach: what to test, at what level (unit, integration, end-to-end), with which "
                      "tools, and with what test data"),
    "other": ("anything else: scope, priorities, user-facing behaviour, process, infrastructure and CI, API "
              "shape across services, dates, a client's wishes"),
}

FILTER = [r"\brather\b", r"\binstead\b", r"\bshould (we|i|it|this)\b", r"\bshall we\b", r"\bor should\b",
          r"\bwhich (one|option|approach|way)\b", r"\bprefer", r"\bgo with\b", r"\blet'?s (use|go|do|keep|drop)\b",
          r"\bdecid", r"\bdecision\b", r"\boption [0-9a-c]\b", r"\bvs\.?\b", r"\bversus\b", r"\bswitch(ing)? to\b",
          r"\bdrop\b", r"\bdon'?t use\b", r"\bstick with\b", r"\btrade-?off", r"\bwe (need|want|must)\b",
          r"\bhas to\b", r"\bhave to\b", r"\bnot (yet|now)\b", r"\bpush back\b", r"\bwhy not\b"]
# An owner's message correcting what Claude did.
CORRECTION = r"^\s*(no\b|nope\b|don'?t\b|stop\b|wrong\b|actually\b|that'?s not\b|not that\b|why did you\b|undo\b|revert\b)"
AFTER = 6
CHARS = 1500
UNIT_CHARS = 16000
SAMPLE_STEP = 0.10
BATCH = 4

ENDINGS = ("option", "combined", "added_option", "own_answer", "none")
ORIGINS = ("own_pick", "accepted_recommendation", "changed_recommendation", "dictated", "delegated", "executor")
DECIDED_BY = ("owner", "client", "manager", "colleague", "executor")
OUTCOMES = ("kept", "reversed", "unknown")

SYSTEM = """You read stretches of one person's work conversations and find the decisions in them.
The person is self-01; other names are pseudonyms (colleague-07, client-03, product-04); [code]
stands for code left out, [url] and [email] for removed details. A stretch is a Claude Code
session, a Slack thread, a Bitbucket pull request or a GSD planning record.

A decision is a choice between ways of doing something that self-01 made, accepted, asked for,
turned down, delegated, or passed on from someone else. Questions that were dropped unanswered
count too, with no choice. Plain instructions with no alternative in sight ("run the tests")
are not decisions. One stretch can hold several decisions, or none.

For each decision give:
- question: what was being decided, in a short neutral sentence
- options_offered: the options as first put, word for word where they were listed
- options_added: options that came up later in the discussion
- recommended_first, recommended_last: the option Claude recommended at first and at the end,
  or "" for none. In a Claude Code question an option labelled "(Recommended)" is the
  recommendation; in Claude's prose, judge from what it says, and give "" where it recommended
  nothing
- ending: option (one offered option), combined (several), added_option (one that came up
  later), own_answer (self-01's own answer, not among the options), none (no choice was made)
- choice: what was chosen, in a short sentence, or "" for none
- origin: own_pick (self-01 picked it), accepted_recommendation (self-01 took Claude's final
  recommendation), changed_recommendation (self-01's pushback changed Claude's recommendation),
  dictated (self-01 said what they wanted outright), delegated ("you decide"), executor (a GSD
  executor decided alone)
- decided_by: owner, client, manager, colleague or executor: whose call it was; a client's or
  manager's call self-01 only passed on is theirs
- from: the pseudonym of who decided when it wasn't self-01, else ""
- reason: why, as stated; if never stated, your best inference with reason_inferred true
- kind: {kinds}
- outcome: kept, reversed (undone later in the stretch) or unknown; outcome_ref quotes the
  words that undid it, else ""
- quote: the words that show the choice, quoted from the stretch

Give every stretch by its number, with an empty list where it holds no decision."""

UNIT = """### Stretch {n} ({source}{project})
{text}
"""

END = "\nGive the decisions in each of the {n} stretches."


def cfg():
    from . import settings
    return settings.get("decisions")


def kinds_text(kinds):
    return "; ".join(f"{k} ({v})" for k, v in kinds.items())


def system_prompt(c=None):
    from . import settings
    c = c or cfg()
    return settings.fill(c["system"], kinds=kinds_text(c["kinds"]))


def schema(c=None):
    c = c or cfg()
    s = {"type": "string"}
    case = {"type": "object", "additionalProperties": False, "properties": {
        "question": s, "options_offered": {"type": "array", "items": s}, "options_added": {"type": "array", "items": s},
        "recommended_first": s, "recommended_last": s, "ending": {"type": "string", "enum": list(ENDINGS)},
        "choice": s, "origin": {"type": "string", "enum": list(ORIGINS)},
        "decided_by": {"type": "string", "enum": list(DECIDED_BY)}, "from": s, "reason": s,
        "reason_inferred": {"type": "boolean"}, "kind": {"type": "string", "enum": list(c["kinds"])},
        "outcome": {"type": "string", "enum": list(OUTCOMES)}, "outcome_ref": s, "quote": s}}
    case["required"] = list(case["properties"])
    return {"type": "object", "additionalProperties": False, "required": ["stretches"], "properties": {
        "stretches": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                 "required": ["n", "decisions"],
                                                 "properties": {"n": {"type": "integer"},
                                                                "decisions": {"type": "array", "items": case}}}}}}


def prompt_version(c=None):
    """What the owner approves: the system prompt, the kinds, the per-stretch
    wording, the fields and the models of both passes."""
    from . import settings
    c = c or cfg()
    m = settings.get("models")
    body = json.dumps({"system": system_prompt(c), "unit": c["unit"], "end": c["end"], "schema": schema(c),
                       "models": [m["extract_first"], m["extract_second"]]}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:12]


def approval_file():
    return state.path("decisions", "approved.json")


def approved():
    """Whether the owner approved the current prompt."""
    a = state.read_json(approval_file(), None) or {}
    return a.get("prompt_version") == prompt_version()


def approve():
    import time
    state.write_json(approval_file(), {"prompt_version": prompt_version(),
                                       "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})


def require_approved():
    if not approved():
        raise SystemExit("voice-decision-pipeline: the extraction prompt isn't approved: read and approve it on "
                         "the review page's Decisions > Prompt (or 'decisions prompt' prints it)")


# --- units ---------------------------------------------------------------------------------

def _owner(r):
    return r.get("author") == "self-01" and any(t.get("type") == "item" for t in r.get("tags") or [])


def _flags(r):
    return {t["type"] for t in r.get("tags") or [] if "start" not in t}


def _clip(t, n):
    t = t or ""
    return t if len(t) <= n else t[:n] + " […]"


def _numbered_question(reply):
    lines = (reply or "").strip().splitlines()
    return (len([l for l in lines if re.match(r"\s*\d+[.)]\s", l)]) >= 2
            and bool(lines) and lines[-1].rstrip().endswith("?"))


def is_candidate(r, c=None, rx=None):
    c = c or cfg()
    rx = rx or re.compile("|".join(c["filter"]), re.I)
    f = _flags(r)
    sf = r.get("source_fields") or {}
    if r["source"] == "gsd" or "ask-user" in f:
        return True
    if r["source"] == "transcripts":
        if _numbered_question(sf.get("preceding_reply")):
            return True
        if re.search(c["correction"], r.get("text") or "", re.I):
            return True
    return bool(rx.search((r.get("text") or "") + "\n" + (sf.get("preceding_reply") or "")))


def _ask_text(sf):
    out = []
    for q in sf.get("questions") or []:
        opts = "; ".join(q.get("options") or [])
        ans = (sf.get("answers") or {}).get(q.get("question"))
        out.append(f"[Claude asked] {q.get('question')} Options: {opts}. [self-01 answered] {ans}")
    return "\n".join(out)


def _transcript_line(r, c):
    sf = r.get("source_fields") or {}
    out = []
    if sf.get("preceding_reply"):
        out.append("[Claude] " + _clip(sf["preceding_reply"], c["chars"]))
    if sf.get("questions"):
        out.append(_ask_text(sf))
    else:
        out.append("[self-01] " + _clip(r.get("text"), c["chars"]))
    return "\n".join(out)


def _ctx_line(r, c):
    return f"[{r.get('author') or 'unknown'}] " + _clip(r.get("text"), c["chars"])


def load_anon():
    from . import SOURCES
    return {s: list(state.read_jsonl(state.anon_file(s))) for s in SOURCES}


def units(log=print):
    """[unit] over the whole corpus: {id, source, project, records (ids),
    text, candidate}. Candidate units first come from candidates; every
    other owner message is a unit of its own, for the sample."""
    c = cfg()
    rx = re.compile("|".join(c["filter"]), re.I)
    data = load_anon()
    out = []

    def add(source, recs, text, cand, project=""):
        uid = "u" + hashlib.sha1(("|".join(r["id"] for r in recs)).encode()).hexdigest()[:16]
        out.append({"id": uid, "source": source, "project": project, "records": [r["id"] for r in recs],
                    "owner": [r["id"] for r in recs if _owner(r)], "text": _clip(text, c["unit_chars"]),
                    "candidate": cand})

    # Transcripts: per session, in time order.
    by = defaultdict(list)
    for r in data["transcripts"]:
        by[r.get("conversation")].append(r)
    for conv, rs in by.items():
        rs.sort(key=lambda r: (r.get("ts") or "", r["id"]))
        i = 0
        while i < len(rs):
            r = rs[i]
            proj = (r.get("source_fields") or {}).get("project") or ""
            if not (_owner(r) and is_candidate(r, c, rx)):
                if _owner(r):
                    add("transcripts", [r], _transcript_line(r, c), False, proj)
                i += 1
                continue
            # The candidate and the next `after` messages: candidates among
            # them are read in the same unit; the next unit starts after it.
            span = rs[i:i + 1 + c["after"]]
            add("transcripts", span, "\n\n".join(_transcript_line(x, c) for x in span), True, proj)
            i += len(span)
    # Slack and Bitbucket: an owner's message with its context; messages
    # sharing a thread or PR with a candidate join one unit.
    for s in ("slack", "bitbucket"):
        idx = {r["id"]: r for r in data[s]}
        groups = defaultdict(list)
        for r in data[s]:
            if not _owner(r):
                continue
            sf = r.get("source_fields") or {}
            key = (r.get("conversation"), sf.get("thread_ts") or sf.get("slack_ts")) if s == "slack" \
                else (r.get("conversation"), sf.get("pr"))
            groups[key].append(r)
        for key, rs in groups.items():
            cand = any(is_candidate(r, c, rx) for r in rs)
            if not cand:
                for r in rs:
                    ctx = sorted((idx[x] for x in r.get("context_ids") or [] if x in idx),
                                 key=lambda x: x.get("ts") or "")
                    span = sorted(ctx + [r], key=lambda x: (x.get("ts") or "", x["id"]))
                    add(s, span, "\n".join(_ctx_line(x, c) for x in span), False)
                continue
            seen, span = set(), []
            for r in rs:
                for x in [idx[y] for y in r.get("context_ids") or [] if y in idx] + [r]:
                    if x["id"] not in seen:
                        seen.add(x["id"])
                        span.append(x)
            if s == "bitbucket":
                conv = key[0]
                for x in data[s]:
                    if x.get("conversation") == conv and x["id"] not in seen:
                        seen.add(x["id"])
                        span.append(x)
            span.sort(key=lambda x: (x.get("ts") or "", x["id"]))
            add(s, span, "\n".join(_ctx_line(x, c) for x in span), True)
    # GSD: one record a unit; a CONTEXT.md decision carries its discuss
    # session's questions where one is found (origin()).
    asks = [r for r in data["transcripts"] if r.get("source_fields", {}).get("questions")]
    for r in data["gsd"]:
        sf = r.get("source_fields") or {}
        head = f"[{sf.get('kind')} in {sf.get('file')}]"
        text = head + "\n" + (r.get("text") or "")
        if sf.get("kind") == "context-decision":
            m = discuss_match(r, asks)
            if m:
                text += "\n\n[from its discuss session]\n" + _ask_text(m.get("source_fields") or {})
        add("gsd", [r], text, True, sf.get("repo_name") or "")
    log(f"  ok    units: {sum(u['candidate'] for u in out)} candidate, "
        f"{sum(not u['candidate'] for u in out)} others in the sample pool")
    return out


def _words(t):
    return set(re.findall(r"[a-z0-9]+", (t or "").lower())) - {"the", "a", "an", "to", "of", "and", "or", "in", "for"}


def discuss_match(rec, asks):
    """The AskUserQuestion answer, in the same project and before the
    CONTEXT.md was written, whose questions share the most words with the
    decision; None when none shares at least a third of the decision
    title's words."""
    sf = rec.get("source_fields") or {}
    proj = sf.get("project") or sf.get("repo_name")
    title = _words(sf.get("section") or rec.get("text", "").split("\n", 1)[0])
    if not title:
        return None
    best, score = None, 0.0
    for a in asks:
        asf = a.get("source_fields") or {}
        if proj and asf.get("project") and asf["project"] != proj:
            continue
        if (a.get("ts") or "") > (rec.get("ts") or "~"):
            continue
        qw = set()
        for q in asf.get("questions") or []:
            qw |= _words(q.get("question")) | _words(q.get("header"))
        sc = len(title & qw) / len(title)
        if sc > score:
            best, score = a, sc
    return best if score >= 1 / 3 else None


def sample(us, step=1, seed="decisions-sample"):
    """The catch-rate sample: step x decisions.sample_step of the non-candidate
    units, drawn by a fixed seed so each step adds to the one before."""
    c = cfg()
    pool = sorted(u["id"] for u in us if not u["candidate"])
    random.Random(seed).shuffle(pool)
    n = round(len(pool) * min(1.0, c["sample_step"] * step))
    return set(pool[:n])


def render(us, n0=1):
    from . import settings
    c = cfg()
    body = "".join(settings.fill(c["unit"], n=n0 + k, source=u["source"],
                                 project=f", {u['project']}" if u["project"] else "", text=u["text"])
                   for k, u in enumerate(us))
    return body + settings.fill(c["end"], n=len(us))


def shown_prompt():
    """The prompt as the owner approves it: the system prompt, one example
    stretch's wording, the closing line and the fields."""
    c = cfg()
    return {"version": prompt_version(c), "system": system_prompt(c), "unit": c["unit"], "end": c["end"],
            "kinds": c["kinds"], "endings": list(ENDINGS), "origins": list(ORIGINS),
            "decided_by": list(DECIDED_BY), "outcomes": list(OUTCOMES)}
