"""The voice guide (PLAN §3.5): rules by audience and purpose.

Three parts, in the order a draft reads them:
  1. own_rules: the owner's rules file (own-rules.md in the state, owner-only,
     never committed), copied word for word as the guide's first section at
     each build. Where one conflicts with a rule drawn from the corpus,
     the owner's wins. Its "## Jira" section is the Jira
     audience's whole guide: rules only, no exemplars (PLAN §3.1).
  2. Corpus rules, written by the guide model from the exemplar pool (never
     the holdouts) and the local statistics: per audience, rules for the
     audience and for each purpose in it; then rules across audiences and
     how purposes are combined.
  3. The statistics and never-say list travel beside it in stats.json.

Every rule is a string; the guide goes out anonymised like every built file,
and the leak check reads it before it is written to a build.
"""

import json
import random
import re
from collections import defaultdict

from . import model, pool, state, voice

PER_PURPOSE = 12
COMBINED = 30
RULES_TEMPLATE = """# Your own voice rules

Each line starting "- " is one rule, copied word for word into the guide's
first section at every build. Where one conflicts with a rule drawn from the
corpus, this file wins. Write names as pseudonyms (colleague-07, client-03):
the build's leak check stops on any real name.

## All drafts

## Jira

Jira comments get no exemplars: the rules here are their whole guide.
"""


def rules_file():
    return state.path("own-rules.md")


def init_rules():
    p = rules_file()
    try:
        with open(p, "x", encoding="utf-8") as f:
            f.write(RULES_TEMPLATE)
        return True
    except FileExistsError:
        return False


def own_rules():
    """(rules, jira rules) from the rules file: every "- " or "* " bullet,
    continuation lines joined, word for word."""
    try:
        with open(rules_file(), encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return [], []
    out = {"main": [], "jira": []}
    sec, cur = "main", None
    for line in text.splitlines():
        h = re.match(r"^#{1,6}\s+(.*)$", line)
        if h:
            sec = "jira" if h.group(1).strip().lower().startswith("jira") else "main"
            cur = None
            continue
        b = re.match(r"^\s*[-*]\s+(.*)$", line)
        if b:
            out[sec].append(b.group(1).rstrip())
            cur = out[sec]
        elif line.strip() and cur is not None and line.startswith((" ", "\t")):
            cur[-1] += " " + line.strip()
        else:
            cur = None
    return out["main"], out["jira"]


def _rules_schema(keys):
    arr = {"type": "array", "items": {"type": "string"}}
    return {"type": "object", "additionalProperties": False, "required": ["rules", "purposes"],
            "properties": {"rules": arr, "purposes": {
                "type": "object", "additionalProperties": False, "required": list(keys),
                "properties": {k: arr for k in keys}}}}


GENERAL_SCHEMA = {"type": "object", "additionalProperties": False,
                  "required": ["general", "combinations"],
                  "properties": {"general": {"type": "array", "items": {"type": "string"}},
                                 "combinations": {"type": "array", "items": {"type": "string"}}}}

SYSTEM = """You write a style guide for drafting messages in one person's voice. The person is
self-01; names are pseudonyms (colleague-07, client-03, product-04); [code] stands for code
left out, [url] and [email] for removed details. You are shown real messages self-01 wrote.

Write rules another model can follow to draft new messages that self-01's readers could not
tell from theirs. Each rule is one short, specific, checkable instruction drawn from the
messages: wording they use and avoid, length, openings and endings, punctuation and
capitalisation, how direct they are, how they order things. Quote their typical words where that
helps. No rule about a particular person, client, product or project; no rule that only
restates the purpose; nothing you cannot see in the messages. British or American spelling
as the messages use it."""


def fmt_ex(e):
    return (f"(answering: {e['answered'][:300]})\n" if e["answered"] else "") + e["text"]


def write(log=print):
    voice.require_sendable()
    items = voice.load()
    ex = pool.exemplars(items)
    if not ex:
        raise SystemExit("voice-decision-pipeline: the exemplar pool is empty; run 'voice label' and 'voice holdout' first")
    from . import voicestats
    stats = voicestats.build(items, log=log)
    rnd = random.Random("guide")
    by = defaultdict(lambda: defaultdict(list))
    for e in ex:
        for p in e["purposes"]:
            by[e["audience"]][p].append(e)
    out = {"audiences": {}}
    for aud in voice.CORPUS_AUDIENCES:
        cells = by.get(aud)
        if not cells:
            log(f"  skip  {aud}: no exemplars")
            continue
        keys = [p for p in voice.PURPOSES if cells.get(p)]
        parts = []
        for p in keys:
            xs = list(cells[p])
            rnd.shuffle(xs)
            parts.append(f"## Purpose: {p} ({voice.PURPOSES[p]}), {len(cells[p])} messages\n\n"
                         + "\n\n---\n\n".join(fmt_ex(e) for e in xs[:PER_PURPOSE]))
        prompt = (f"Audience: {aud}. Statistics of every message self-01 wrote to this audience:\n"
                  f"{json.dumps(stats['audiences'].get(aud, {}))}\n\n" + "\n\n".join(parts) +
                  f"\n\nWrite the rules for this audience as a whole, then the rules for each of "
                  f"these purposes: {', '.join(keys)}.")
        try:
            ans = model.call("guide", SYSTEM, prompt, _rules_schema(keys), log=log)
        except model.UsageLimit as e:
            log(f"  stop  usage limit: {e}; run the same command again")
            return None
        out["audiences"][aud] = {"rules": ans["rules"],
                                 "purposes": {p: v for p, v in ans["purposes"].items() if v}}
        log(f"  ok    guide {aud}: {len(ans['rules'])} audience rules, {len(keys)} purposes")
    multi = [e for e in ex if len(e["purposes"]) > 1]
    rnd.shuffle(multi)
    summary = json.dumps({a: v["rules"] for a, v in out["audiences"].items()})
    prompt = ("Rules written per audience:\n" + summary + "\n\nMessages carrying several purposes, "
              "each with its purposes in the order they appear:\n\n" +
              "\n\n---\n\n".join(f"[{e['audience']}; {', '.join(e['purposes'])}]\n{fmt_ex(e)}"
                                 for e in multi[:COMBINED]) +
              "\n\nWrite the rules that hold across every audience, and the rules for how "
              "self-01 combines purposes in one message (what comes first, how they are joined).")
    try:
        ans = model.call("guide", SYSTEM, prompt, GENERAL_SCHEMA, log=log)
    except model.UsageLimit as e:
        log(f"  stop  usage limit: {e}; run the same command again")
        return None
    out["general"], out["combinations"] = ans["general"], ans["combinations"]
    state.write_json(state.path("voice", "corpus-guide.json"), out)
    state.write_json(state.path("voice", "stats.json"), stats)
    log("  ok    guide written to voice/corpus-guide.json")
    return out


def assemble(build_time):
    """guide.json for a build: the owner's rules first, then the corpus guide."""
    cg = state.read_json(state.path("voice", "corpus-guide.json"), None)
    if cg is None:
        raise SystemExit("voice-decision-pipeline: no guide written yet; run 'voice guide'")
    mine, jira = own_rules()
    return {"schema_version": 1, "build_time": build_time, "own_rules": mine,
            "general": cg.get("general", []), "combinations": cg.get("combinations", []),
            "audiences": cg.get("audiences", {}), "jira": jira}


def render(g, stats, audience, purposes):
    """The guide text a draft for audience and purposes reads: the same
    sections voice-runtime's `guide` gives (validation drafts with it)."""
    out = []
    if g.get("own_rules"):
        out.append("self-01's own rules (these win over every rule below):\n" +
                   "\n".join(f"- {r}" for r in g["own_rules"]))
    if audience == "jira":
        out.append("Jira comments:\n" + "\n".join(f"- {r}" for r in g.get("jira", [])))
        return "\n\n".join(out)
    if g.get("general"):
        out.append("Every audience:\n" + "\n".join(f"- {r}" for r in g["general"]))
    a = g.get("audiences", {}).get(audience, {})
    if a.get("rules"):
        out.append(f"Writing to {audience}:\n" + "\n".join(f"- {r}" for r in a["rules"]))
    for p in purposes:
        if a.get("purposes", {}).get(p):
            out.append(f"When the purpose is {p}:\n" + "\n".join(f"- {r}" for r in a["purposes"][p]))
    if len(purposes) > 1 and g.get("combinations"):
        out.append("Combining purposes:\n" + "\n".join(f"- {r}" for r in g["combinations"]))
    st = (stats or {}).get("audiences", {}).get(audience)
    if st:
        out.append(f"Measured, to {audience}: median {st['median_words']} words (90% under "
                   f"{st['p90_words']}); {int(st['lowercase_start'] * 100)}% start lower case; "
                   f"{int(st['full_stop_end'] * 100)}% end with a full stop; "
                   f"{st['exclamation_per_message']} exclamation marks and "
                   f"{st['emoji_per_message']} emoji per message.")
        for p in purposes:
            sp = st.get("purposes", {}).get(p)
            if sp:
                out.append(f"Measured, to {audience} when the purpose is {p}: median {sp['median_words']} "
                           f"words (90% under {sp['p90_words']}), over {sp['messages']} messages.")
    ns = [x["phrase"] for x in (stats or {}).get("never_say", [])]
    if ns:
        out.append("self-01 never or almost never writes: " + "; ".join(f'"{p}"' for p in ns[:80]))
    return "\n\n".join(out)
