"""The drafter's settings (PLAN §3.7): what the drafting model and the brief
writer are told, and each audience's drafting notes. They live in the state,
in voice/drafter.json, so changing them needs no new release: edit the file,
run 'voice validate --batch', then 'voice pairs --redraw all'.

  draft_system      the drafter's system prompt, before the guide
  brief_system      the brief writer's system prompt
  draft_prompt      the drafter's per-message prompt; {examples}, {source},
                    {context}, {brief}, {audience}, {purposes}
  brief_prompt      the brief writer's per-message prompt; {context}, {message}
  draft_before_chars, brief_before_chars, answering_chars
                    how much conversation each is shown, and of the message
                    an example answers
  notes             {audience: [line]} shown as "How to write it" before the
                    guide's rules; an audience with none gets no section
  quoted_rates_for  audiences shown the share of messages holding each word
                    the guide's rules quote

Each corpus audience's draft method is a hash of what its drafts depend on:
both prompts, its notes, whether it is shown the quoted words' shares, the
voice settings that change the drafter's prompt or model where they differ
from their defaults (settings.draft_inputs: the render, style and stats
sections, the drafter's and brief writer's models), the per-message prompts
and context sizes where they differ from their defaults, and CODE, the
version of the code that builds the prompts round them. Changing one audience's notes
changes only that audience's method, so only it is drafted and paired again;
the other audiences' drafts, pairs and answers stand.

The file is written with the defaults below the first time it is read: the
two prompts, and no notes for any audience. Notes are local to the state.
LEGACY names methods from before the file existed whose rows still count:
"brief-8" rows were drafted with the default prompts, and with no notes for
every audience but those LEGACY_NOTED lists.
"""

import hashlib
import json

from . import state, voice

CODE = 1
SCHEMA = 1

DEFAULT_DRAFT_SYSTEM = """You draft a message as self-01, in self-01's own voice, following the guide below
and matching the example messages self-01 really wrote. Names are pseudonyms (colleague-07,
client-03, product-04); keep using them. [code] stands for code left out: write [code] where
self-01 would paste code. Reply with the message text only: no preamble, no quotation marks.

"""

DEFAULT_BRIEF_SYSTEM = """You write the brief for one message: what it says, never how it says it. The
writer is self-01; names are pseudonyms (colleague-07, client-03, product-04); keep them.
[url], [email], [code] and [REDACTED:...] stand for removed details; keep them where the
message has them. List each point the message makes, in the order it makes them, one short
note per line, in plain neutral words of your own: facts, questions, requests, decisions,
names, numbers, dates. Never quote or echo its wording, and say nothing about its length,
tone, punctuation, capitalisation, emoji or sign-off; where it greets, jokes or thanks, say
so in a few words of your own ("a greeting", "a joke about the train being late"). Where it
addresses someone, say how: an @mention, or their name in the text; where it names no one,
say nothing about who it is for. Add nothing the message doesn't say."""

DEFAULT_NOTES = {}

# The per-message prompts: {slots} filled once each (settings.fill).
DEFAULT_DRAFT_PROMPT = """Examples of messages self-01 wrote to this audience:

{examples}

Conversation so far ({source}):
{context}

What the message has to say (a brief, not its wording):
{brief}

Write self-01's next message, saying what the brief says in self-01's own words, and nothing more: no question, offer, mention, pleasantry or sign-off the brief doesn't list. Audience: {audience}. Purposes, in order: {purposes}."""

DEFAULT_BRIEF_PROMPT = """Conversation before it:
{context}

The message:
{message}

Write its brief."""

# Keys a file written before they existed takes from here.
PROMPT_DEFAULTS = {"draft_prompt": DEFAULT_DRAFT_PROMPT, "brief_prompt": DEFAULT_BRIEF_PROMPT,
                   "draft_before_chars": 4000, "brief_before_chars": 2000, "answering_chars": 300}

DEFAULTS = {"schema_version": SCHEMA, "draft_system": DEFAULT_DRAFT_SYSTEM,
            "brief_system": DEFAULT_BRIEF_SYSTEM, **PROMPT_DEFAULTS,
            "notes": DEFAULT_NOTES, "quoted_rates_for": []}
SLOTS = {"draft_prompt": ("examples", "brief"), "brief_prompt": ("message",)}


def file():
    return state.path("voice", "drafter.json")


def _bad(why):
    raise SystemExit(f"voice-decision-pipeline: {file()}: {why}")


def load():
    """The drafter's settings, written with the defaults if there is no file."""
    d = state.read_json(file(), None)
    if d is None:
        state.write_json(file(), DEFAULTS)
        d = DEFAULTS
    if not isinstance(d, dict) or d.get("schema_version") != SCHEMA:
        _bad(f"schema_version must be {SCHEMA}")
    for k in ("draft_system", "brief_system"):
        if not isinstance(d.get(k), str) or not d[k].strip():
            _bad(f"{k} must be a non-empty string")
    notes = d.get("notes", {})
    if not isinstance(notes, dict) or not all(
            isinstance(a, str) and isinstance(v, list) and all(isinstance(x, str) for x in v)
            for a, v in notes.items()):
        _bad("notes must map an audience to a list of strings")
    bad = sorted(set(notes) - set(voice.all_audiences()))
    if bad:
        _bad(f"notes for an unknown audience: {', '.join(bad)}")
    q = d.get("quoted_rates_for", [])
    if not isinstance(q, list) or not all(isinstance(a, str) for a in q):
        _bad("quoted_rates_for must be a list of audiences")
    unknown = sorted(set(d) - set(DEFAULTS))
    if unknown:
        _bad("unknown key " + ", ".join(unknown))
    p = {k: d.get(k, v) for k, v in PROMPT_DEFAULTS.items()}
    for k, slots in SLOTS.items():
        if not isinstance(p[k], str) or any("{" + s + "}" not in p[k] for s in slots):
            _bad(f"{k} must be a string holding " + ", ".join("{" + s + "}" for s in slots))
    for k in ("draft_before_chars", "brief_before_chars", "answering_chars"):
        if isinstance(p[k], bool) or not isinstance(p[k], int) or not 0 <= p[k] <= 100000:
            _bad(f"{k} must be a whole number from 0 to 100000")
    return {"draft_system": d["draft_system"], "brief_system": d["brief_system"], **p,
            "notes": {a: list(v) for a, v in notes.items()}, "quoted_rates_for": sorted(q)}


def _hash(draft, brief, notes, quoted, extra=None):
    h = {"code": CODE, "draft": draft, "brief": brief, "notes": list(notes), "quoted": bool(quoted)}
    if extra:
        h["settings"] = extra
    blob = json.dumps(h, sort_keys=True, ensure_ascii=False)
    return "d-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:10]


def method(audience, d=None):
    """The audience's draft method under settings d (the file's by default)."""
    from . import settings
    d = d or load()
    extra = settings.draft_inputs()
    prompts = {k: d[k] for k in PROMPT_DEFAULTS if d[k] != PROMPT_DEFAULTS[k]}
    if prompts:
        extra = {**extra, "prompts": prompts}
    return _hash(d["draft_system"], d["brief_system"], d["notes"].get(audience, []),
                 audience in d["quoted_rates_for"], extra)


def methods(d=None):
    d = d or load()
    return {a: method(a, d) for a in voice.corpus_audiences()}


LEGACY = {"brief-8": _hash(DEFAULT_DRAFT_SYSTEM, DEFAULT_BRIEF_SYSTEM, [], False)}
LEGACY_NOTED = {"brief-8": ("clients",)}


def normal(m, audience):
    """A row's method as this module names it: a LEGACY name as its hash,
    for an audience it drafted without notes."""
    if m in LEGACY and audience not in LEGACY_NOTED.get(m, ()):
        return LEGACY[m]
    return m


def for_build(d=None):
    """What a build carries in stats.json so voice-runtime drafts as
    validation did: the drafter's base prompt, the notes, the purposes'
    ids in order, and the quoted-word cutoff."""
    from . import settings
    d = d or load()
    return {"draft_system": d["draft_system"],
            "notes": {a: list(v) for a, v in sorted(d["notes"].items())},
            "quoted_rates_for": list(d["quoted_rates_for"]),
            "rare_below": settings.get("style")["quoted_rare_below"],
            "render": settings.get("render"),
            "purposes": list(settings.purposes()),
            "audiences": [{"slug": a["slug"], "corpus": a["corpus"], "routing": a["routing"]}
                          for a in settings.audiences()],
            "methods": methods(d)}
