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

# The defaults of SYSTEM, PER_PURPOSE and COMBINED; the state's
# settings.json "guide" section wins (settings.py).
PER_PURPOSE = 12
COMBINED = 30
RULES_TEMPLATE = """# Your own voice rules

Each line starting "- " is one rule, copied word for word into the guide's
first section at every build. Where one conflicts with a rule drawn from the
corpus, this file wins. Write names as pseudonyms (colleague-07, client-03):
the build's leak check stops on any real name.

A section named after an audience (## clients, ## project team) holds rules
for that audience only, read after the rules for all drafts.

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


def _bullets(path, section_of, first):
    """{section: [bullet, ...]} from a rules file: every "- " or "* " bullet,
    continuation lines joined, word for word. section_of maps a heading to
    its section; bullets before any heading go to first."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return {}
    out = defaultdict(list)
    sec, cur = first, None
    for line in text.splitlines():
        h = re.match(r"^#{1,6}\s+(.*)$", line)
        if h:
            sec = section_of(h.group(1).strip().lower())
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
    return out


def own_section(heading):
    """Where a heading of the rules file puts its lines: "jira" for the Jira
    section, an audience's slug for a section named after a corpus audience
    (by slug or name, "## clients", "## project team"), else "main", the
    lines for every audience."""
    from . import settings
    if heading.startswith("jira"):
        return "jira"
    for a in settings.audiences():
        if a["corpus"] and heading in (a["slug"].lower(), a["name"].lower()):
            return "audience:" + a["slug"]
    return "main"


def own_rules():
    """(rules, jira rules) from the rules file, word for word."""
    out = _bullets(rules_file(), own_section, "main")
    return out.get("main", []), out.get("jira", [])


def own_rules_audience():
    """{audience slug: [rule]} from the rules file's audience sections, word
    for word; an audience reads them after the lines for every audience."""
    out = _bullets(rules_file(), own_section, "main")
    return {k.split(":", 1)[1]: v for k, v in out.items() if k.startswith("audience:") and v}


# -- rules the owner struck ----------------------------------
#
# A rule the guide model wrote that the owner doesn't want, or a phrase on the
# never-say list, is listed in struck-rules.md in the state. assemble() and
# render() leave it out, so validation drafts and every build go without
# it; a rerun of `voice guide` writes the corpus guide again but can't bring
# it back word for word, and the guide model is told not to write it or one
# like it. One that comes back reworded is struck again, or answered by a
# rule in own-rules.md, which wins over every corpus rule.

STRUCK_TEMPLATE = """# Rules you struck

Each line starting "- " is struck: left out of every validation draft and
every build, however often `voice guide` runs again. Case, spacing, quote
marks and the full stop at the end don't matter; the words do.

Under "## Rules", copy a rule the guide model wrote. The guide model is also
told not to write it, or a rule that says the same. If one comes back in
other words, strike that too, or answer it with a rule in own-rules.md.

Under "## Never say", copy a phrase from the never-say list.

## Rules

## Never say
"""


def struck_file():
    return state.path("struck-rules.md")


def init_struck():
    try:
        with open(struck_file(), "x", encoding="utf-8") as f:
            f.write(STRUCK_TEMPLATE)
        return True
    except FileExistsError:
        return False


def strike_key(s):
    """What a struck line and a rule are matched on: the words, in lower case,
    with spacing, quote marks and end punctuation evened out."""
    s = s.translate({0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"'})
    s = re.sub(r"\s+", " ", s).strip(" .;:!")
    if len(s) > 1 and s[0] == s[-1] and s[0] in "'\"":
        s = s[1:-1].strip(" .;:!")
    return s.lower()


def struck():
    """{"rules": [...], "never_say": [...]}, word for word as the owner wrote them."""
    out = _bullets(struck_file(), lambda h: "never_say" if h.startswith("never") else "rules", "rules")
    return {"rules": out.get("rules", []), "never_say": out.get("never_say", [])}


def strike(cg, keys=None):
    """(corpus guide without the struck rules, keys of the struck rules that
    matched one)."""
    keys = {strike_key(r) for r in struck()["rules"]} if keys is None else keys
    used = set()

    def keep(rs):
        out = []
        for r in rs or []:
            k = strike_key(r)
            if k in keys:
                used.add(k)
            else:
                out.append(r)
        return out
    g = dict(cg)
    g["general"], g["combinations"] = keep(cg.get("general")), keep(cg.get("combinations"))
    g["audiences"] = {a: {**v, "rules": keep(v.get("rules")),
                          "purposes": {p: keep(rs) for p, rs in (v.get("purposes") or {}).items()}}
                      for a, v in (cg.get("audiences") or {}).items()}
    return g, used


def strike_stats(stats, keys=None):
    """(stats without the struck never-say phrases, keys that matched one)."""
    if not stats:
        return stats, set()
    keys = {strike_key(p) for p in struck()["never_say"]} if keys is None else keys
    ns = stats.get("never_say", [])
    used = {strike_key(x["phrase"]) for x in ns} & keys
    return {**stats, "never_say": [x for x in ns if strike_key(x["phrase"]) not in keys]}, used


def struck_summary(stats):
    """Counts only, for a log Claude reads: struck lines may quote real words."""
    s = struck()
    cg = state.read_json(state.path("voice", "corpus-guide.json"), None) or {}
    rk, nk = {strike_key(r) for r in s["rules"]}, {strike_key(p) for p in s["never_say"]}
    _, ru = strike(cg, rk)
    _, nu = strike_stats(stats, nk)
    return {"rules": len(rk), "rules_matched": len(ru), "never_say": len(nk), "never_say_matched": len(nu)}


def struck_for_prompt(log=print):
    """The struck rules the guide model may be shown: each one the leak check
    finds nothing in. The rest stay struck from the guide but aren't sent;
    the log gives their count, never their words."""
    rules = struck()["rules"]
    if not rules:
        return []
    from . import inputs, leaks
    from .anonmap import Map
    ok = leaks.clean(rules, inputs.load(), Map.load())
    if len(ok) < len(rules):
        log(f"  held  {len(rules) - len(ok)} struck rules not shown to the guide model: the leak check "
            "found a name in them (they are still struck)")
    return ok


def struck_prompt(rules):
    if not rules:
        return ""
    return ("\n\nself-01 struck these rules from an earlier guide as wrong. Don't write any of them, "
            "or a rule that says the same in other words:\n" + "\n".join(f"- {r}" for r in rules))


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


# The guide writer's task prompts and the examples' "answering" length: the
# defaults; the state's settings.json "guide" section wins (settings.py).
AUDIENCE_PROMPT = """Audience: {audience}. Statistics of every message self-01 wrote to this audience:
{stats}

{examples}

Write the rules for this audience as a whole, then the rules for each of these purposes: {purposes}."""
PURPOSE_EXAMPLES = """## Purpose: {purpose} ({definition}), {count} messages

{examples}"""
GENERAL_PROMPT = """Rules written per audience:
{rules}

Messages carrying several purposes, each with its purposes in the order they appear:

{examples}

Write the rules that hold across every audience, and the rules for how self-01 combines purposes in one message (what comes first, how they are joined)."""
ANSWERING_CHARS = 300


def fmt_ex(e, n=None):
    if n is None:
        from . import settings
        n = settings.get("guide")["answering_chars"]
    return (f"(answering: {e['answered'][:n]})\n" if e["answered"] else "") + e["text"]


def sample(ex):
    """The examples the guide's prompts show, drawn by its fixed seed:
    ({audience: [(purpose, [exemplar])]}, [multi-purpose exemplar])."""
    from . import settings
    gs = settings.get("guide")
    rnd = random.Random("guide")
    by = defaultdict(lambda: defaultdict(list))
    for e in ex:
        for p in e["purposes"]:
            by[e["audience"]][p].append(e)
    per = {}
    for aud in voice.corpus_audiences():
        cells = by.get(aud)
        if not cells:
            continue
        per[aud] = []
        for p in [p for p in voice.purposes() if cells.get(p)]:
            xs = list(cells[p])
            rnd.shuffle(xs)
            per[aud].append((p, len(cells[p]), xs[:gs["per_purpose"]]))
    multi = [e for e in ex if len(e["purposes"]) > 1]
    rnd.shuffle(multi)
    return per, multi[:gs["combined"]]


def shown_file():
    return state.path("voice", "guide-shown.json")


def shown_ids(ex=None):
    """Ids of every message the guide's prompts showed, saved when the guide
    is written (or, for a guide written before this was kept, worked out once
    from the pool as it then was and saved): a message the guide saw is never
    held back later, so no draft is judged against a message its guide quoted."""
    d = state.read_json(shown_file(), None)
    if d is None:
        per, multi = sample(ex if ex is not None else pool.exemplars(voice.load()))
        ids = sorted({e["id"] for cells in per.values() for _, _, xs in cells for e in xs} | {e["id"] for e in multi})
        d = {"ids": ids}
        state.write_json(shown_file(), d)
    return set(d["ids"])


def write(log=print):
    voice.require_sendable()
    items = voice.load()
    ex = pool.exemplars(items)
    if not ex:
        raise SystemExit("voice-decision-pipeline: the exemplar pool is empty; run 'voice label' and 'voice holdout' first")
    from . import voicestats
    stats = voicestats.build(items, log=log)
    from . import settings
    gs = settings.get("guide")
    system = gs["system"] + struck_prompt(struck_for_prompt(log=log))
    defs = voice.purposes()
    per, multi = sample(ex)
    out = {"audiences": {}}
    for aud in voice.corpus_audiences():
        if aud not in per:
            log(f"  skip  {aud}: no exemplars")
            continue
        keys = [p for p, _, _ in per[aud]]
        parts = [settings.fill(gs["purpose_examples"], purpose=p, definition=defs.get(p, p), count=n,
                               examples="\n\n---\n\n".join(fmt_ex(e, gs["answering_chars"]) for e in xs))
                 for p, n, xs in per[aud]]
        prompt = settings.fill(gs["audience_prompt"], audience=aud,
                               stats=json.dumps(stats['audiences'].get(aud, {})),
                               examples="\n\n".join(parts), purposes=", ".join(keys))
        try:
            ans = model.call("guide", system, prompt, _rules_schema(keys), log=log)
        except model.UsageLimit as e:
            log(f"  stop  usage limit: {e}; run the same command again")
            return None
        out["audiences"][aud] = {"rules": ans["rules"],
                                 "purposes": {p: v for p, v in ans["purposes"].items() if v}}
        log(f"  ok    guide {aud}: {len(ans['rules'])} audience rules, {len(keys)} purposes")
    summary = json.dumps({a: v["rules"] for a, v in out["audiences"].items()})
    prompt = settings.fill(gs["general_prompt"], rules=summary, examples="\n\n---\n\n".join(
        f"[{e['audience']}; {', '.join(e['purposes'])}]\n{fmt_ex(e, gs['answering_chars'])}" for e in multi))
    try:
        ans = model.call("guide", system, prompt, GENERAL_SCHEMA, log=log)
    except model.UsageLimit as e:
        log(f"  stop  usage limit: {e}; run the same command again")
        return None
    out["general"], out["combinations"] = ans["general"], ans["combinations"]
    state.write_json(state.path("voice", "corpus-guide.json"), out)
    state.write_json(shown_file(), {"ids": sorted({e["id"] for cells in per.values() for _, _, xs in cells
                                                   for e in xs} | {e["id"] for e in multi})})
    state.write_json(state.path("voice", "stats.json"), stats)
    log("  ok    guide written to voice/corpus-guide.json")
    s = struck_summary(stats)
    if s["rules"] or s["never_say"]:
        log(f"  ok    struck: {s['rules_matched']} of {s['rules']} struck rules were written again word for "
            f"word and are left out; {s['never_say_matched']} of {s['never_say']} struck phrases are on the "
            "never-say list and are left out")
    return out


def assemble(build_time):
    """guide.json for a build: the owner's rules first, then the corpus guide
    without the rules they struck."""
    cg = state.read_json(state.path("voice", "corpus-guide.json"), None)
    if cg is None:
        raise SystemExit("voice-decision-pipeline: no guide written yet; run 'voice guide'")
    cg, _ = strike(cg)
    mine, jira = own_rules()
    out = {"schema_version": 1, "build_time": build_time, "own_rules": mine,
           "general": cg.get("general", []), "combinations": cg.get("combinations", []),
           "audiences": cg.get("audiences", {}), "jira": jira}
    by_aud = own_rules_audience()
    if by_aud:
        out["own_rules_audience"] = by_aud
    return out


# The default; the state's settings.json "style.quoted_rare_below" wins.
RARE_QUOTED = 0.02

# The wording round the guide a draft reads: the defaults; the state's
# settings.json "render" section wins. voice-runtime's guide is given the
# same wording in the build and gives the same text.
RENDER = {
    "own_rules": "self-01's own rules (these win over every rule below):",
    "notes": "How to write it:",
    "jira": "Jira comments:",
    "general": "Every audience:",
    "audience": "Writing to {audience}:",
    "purpose": "When the purpose is {purpose}:",
    "combining": "Combining purposes:",
    "measured": ("Measured, to {audience}: median {median_words} words (90% under {p90_words}); "
                 "{lowercase_start}% start lower case; {full_stop_end}% end with a full stop; "
                 "{exclamation_per_message} exclamation marks and {emoji_per_message} emoji per message."),
    "style": ("Share of self-01's messages to {audience} holding each: {shares}. Use each about as often "
              "as that: put one in only where the examples for this message have it, and keep it where they do."),
    "purpose_measured": ("Measured, to {audience} when the purpose is {purpose}: median {median_words} "
                         "words (90% under {p90_words}), over {messages} messages."),
    "quoted": ("Share of self-01's messages to {audience} holding each word quoted in the rules above: "
               "{shares}. Most messages use none of them: use one only where the examples for this message do "
               "(a word the brief needs is always fine)."),
    "never_say": "self-01 never or almost never writes: {phrases}",
    "never_say_max": 80,
}


def render(g, stats, audience, purposes, d=None):
    """The guide text a draft for audience and purposes reads, with the
    audience's drafting notes from the drafter's settings d (the state's
    voice/drafter.json by default) and the wording from the settings'
    render section. voice-runtime's `guide` gives the same text from the
    build (render_text is the rule both follow). Phrases the owner struck
    are left off the never-say list."""
    from . import drafter, settings
    d = d or drafter.load()
    stats, _ = strike_stats(stats)
    corpus = audience in settings.corpus_audiences()
    return render_text(g, stats, audience, purposes, d["notes"].get(audience, []),
                       audience in d["quoted_rates_for"], settings.get("style")["quoted_rare_below"],
                       settings.get("render"), corpus)


def render_text(g, stats, audience, purposes, notes, quoted_on, rare_below, w, corpus):
    """The guide text from its parts and the wording w. An audience with no
    corpus (Jira) gets the owner's rules, its notes and its own rules only."""
    from .settings import fill
    from .voicestats import quoted
    bl = lambda rs: "\n".join(f"- {r}" for r in rs)
    out = []
    own = list(g.get("own_rules") or []) + list((g.get("own_rules_audience") or {}).get(audience) or [])
    if own:
        out.append(w["own_rules"] + "\n" + bl(own))
    if notes:
        out.append(w["notes"] + "\n" + bl(notes))
    if not corpus:
        out.append(w["jira"] + "\n" + bl(g.get("jira", [])))
        return "\n\n".join(out)
    if g.get("general"):
        out.append(w["general"] + "\n" + bl(g["general"]))
    a = g.get("audiences", {}).get(audience, {})
    if a.get("rules"):
        out.append(fill(w["audience"], audience=audience) + "\n" + bl(a["rules"]))
    for p in purposes:
        if a.get("purposes", {}).get(p):
            out.append(fill(w["purpose"], purpose=p) + "\n" + bl(a["purposes"][p]))
    if len(purposes) > 1 and g.get("combinations"):
        out.append(w["combining"] + "\n" + bl(g["combinations"]))
    st = (stats or {}).get("audiences", {}).get(audience)
    if st:
        out.append(fill(w["measured"], audience=audience, median_words=st["median_words"],
                        p90_words=st["p90_words"], lowercase_start=int(st["lowercase_start"] * 100),
                        full_stop_end=int(st["full_stop_end"] * 100),
                        exclamation_per_message=st["exclamation_per_message"],
                        emoji_per_message=st["emoji_per_message"]))
        if st.get("style"):
            out.append(fill(w["style"], audience=audience,
                            shares=", ".join(f"{k} {v:.0%}" for k, v in st["style"].items())))
        for p in purposes:
            sp = st.get("purposes", {}).get(p)
            if sp:
                out.append(fill(w["purpose_measured"], audience=audience, purpose=p,
                                median_words=sp["median_words"], p90_words=sp["p90_words"],
                                messages=sp["messages"]))
    shown_rules = list(g.get("general", [])) + list(a.get("rules", []))
    for p in purposes:
        shown_rules += a.get("purposes", {}).get(p, [])
    if len(purposes) > 1:
        shown_rules += list(g.get("combinations", []))
    rates = (stats or {}).get("quoted", {}).get(audience, {}) if quoted_on else {}
    rare = sorted({q for r in shown_rules for q in quoted(r) if q in rates and rates[q] < rare_below},
                  key=lambda q: (rates[q], q))
    if rare:
        out.append(fill(w["quoted"], audience=audience,
                        shares=", ".join(f'"{q}" {rates[q]:.1%}' for q in rare)))
    ns = [x["phrase"] for x in (stats or {}).get("never_say", [])]
    if ns:
        out.append(fill(w["never_say"], phrases="; ".join(f'"{p}"' for p in ns[:w["never_say_max"]])))
    return "\n\n".join(out)
