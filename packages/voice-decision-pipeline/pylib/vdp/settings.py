"""Every setting that is tuned rather than built (PLAN §8.2), read from the
state's settings.json, so changing one needs no new release. The drafter's
own prompts and notes are in voice/drafter.json (drafter.py); the exemplar
pool's thresholds and the holdout share in voice-config.json (pool.py).

  audiences  [{slug, name, corpus, match_prefix, routing}], in order: the
             slug builds and voice-runtime use, the name the mapping page
             and inputs.json use, whether it has messages in the corpus
             (jira has none: its guide is the owner's Jira rules), whether a
             hand-written audience starting with the name maps to it, and
             where a draft goes for it (voice-runtime's routing table)
  labels     purposes {id: definition}; system (the labelling prompt,
             "{purposes}" replaced by the list); item, batch_end (each
             item's and the call's closing text); before_chars, after_chars;
             batch (items a call); sample, sample_max_wrong (the owner's
             label check); disagree_sample
  guide      system; audience_prompt, purpose_examples, general_prompt (the
             guide writer's task prompts); per_purpose, combined (examples
             shown); answering_chars
  render     the wording round the guide a draft reads (guide.render), and
             never_say_max; voice-runtime's guide gives the same
  judge      system, grades {"5": ... "1": ...}, prompt, before_chars
  pass_rule  overall_bar, audience_bar, sure, unsure, grades_all,
             grades_audience, pairs_per_audience, exemplar_counts,
             judge_review_worst, judge_review_random. Each change is
             recorded with the run it applies to, in
             validation/pass-rule.jsonl.
  style      marks {name: {pattern, flags}}; quoted_rare_below; never_say
             {rare_rate, ratio, colleague_min, colleague_top}
  stats      purpose_min (messages a purpose needs for its own lengths);
             spelling [[british, american]]; generic_phrases (the generic
             never-say list)
  build      default_exemplar_count (before validation has picked one)
  calls      retries, timeout (seconds), limit_words (how Claude Code
             words a usage limit, matched in lower case)
  extraction slack_window_seconds, slack_window_max, bitbucket_cutoff,
             bitbucket_code_context, transcript_reply_cap,
             transcript_summary_cap; a change shows in the next extract
  review     batch_size, mining_max_clients
  models     {role: model id} for labeller, second, drafter, judge, brief,
             guide

Prompt templates name their slots as {name}; each slot is filled once, so
text put in a slot is never read for slots itself.

The file is written with the defaults the first time it is read. A section
or key left out takes its default; an unknown one is refused, as is a
malformed value. What changes the drafter's prompt or model (render, style,
stats, the drafter's and brief writer's models) joins each audience's draft
method (drafter.py) wherever it differs from the defaults: change one and
every audience is drafted and paired again, while the defaults leave every
method as it was. The labeller's item text and context sizes join the label
prompt version the same way.
"""

import copy
import json
import os
import re

from . import state

SCHEMA = 1
SECTIONS = ("audiences", "labels", "guide", "render", "judge", "pass_rule", "style", "stats",
            "build", "calls", "extraction", "review", "models")
# Keys whose value is replaced whole, not merged key by key.
WHOLE = {("labels", "purposes"), ("judge", "grades"), ("style", "marks"), ("style", "never_say")}
FLAGS = {"i": re.I, "m": re.M}
SLOT = re.compile(r"\{([a-z][a-z0-9_]*)\}")

_DEFAULTS = None
_CACHE = {}


def file():
    return state.path("settings.json")


def fill(template, **slots):
    """template with each {name} replaced by slots[name], in one pass."""
    return SLOT.sub(lambda m: str(slots[m.group(1)]) if m.group(1) in slots else m.group(0), template)


def generic_default():
    p = os.path.join(os.path.dirname(__file__), "data", "generic-phrases.txt")
    with open(p, encoding="utf-8") as f:
        return [l.strip().lower() for l in f if l.strip() and not l.startswith("#")]


def defaults():
    """The settings the code ships, built from each module's own constants."""
    global _DEFAULTS
    if _DEFAULTS is None:
        from . import (anonymise, batches, bitbucket, guide, labels, model, slack, transcripts, validate,
                       voice, voicebuild, voicestats)
        _DEFAULTS = {
            "schema_version": SCHEMA,
            "audiences": copy.deepcopy(voice.AUDIENCE_LIST),
            "labels": {"purposes": dict(voice.PURPOSES), "system": labels.SYSTEM,
                       "item": labels.ITEM, "batch_end": labels.BATCH_END,
                       "before_chars": labels.BEFORE_CHARS, "after_chars": labels.AFTER_CHARS,
                       "batch": labels.BATCH, "sample": labels.SAMPLE,
                       "sample_max_wrong": labels.SAMPLE_MAX_WRONG, "disagree_sample": labels.DISAGREE_SAMPLE},
            "guide": {"system": guide.SYSTEM, "audience_prompt": guide.AUDIENCE_PROMPT,
                      "purpose_examples": guide.PURPOSE_EXAMPLES, "general_prompt": guide.GENERAL_PROMPT,
                      "per_purpose": guide.PER_PURPOSE, "combined": guide.COMBINED,
                      "answering_chars": guide.ANSWERING_CHARS},
            "render": dict(guide.RENDER),
            "judge": {"system": validate.JUDGE_BASE, "grades": {str(k): v for k, v in validate.GRADES.items()},
                      "prompt": validate.JUDGE_PROMPT, "before_chars": validate.JUDGE_BEFORE_CHARS},
            "pass_rule": {"overall_bar": validate.OVERALL_BAR, "audience_bar": validate.AUDIENCE_BAR,
                          "sure": validate.SURE, "unsure": validate.UNSURE,
                          "grades_all": validate.GRADES_ALL, "grades_audience": validate.GRADES_AUDIENCE,
                          "pairs_per_audience": validate.PAIRS_PER_AUDIENCE,
                          "exemplar_counts": list(validate.COUNTS),
                          "judge_review_worst": validate.WORST, "judge_review_random": validate.RANDOM},
            "style": {"marks": {k: {"pattern": r.pattern, "flags": "".join(f for f, v in FLAGS.items() if r.flags & v)}
                                for k, r in voicestats.STYLE.items()},
                      "quoted_rare_below": guide.RARE_QUOTED,
                      "never_say": {"rare_rate": voicestats.RARE_RATE, "ratio": voicestats.RATIO,
                                    "colleague_min": voicestats.COLLEAGUE_MIN,
                                    "colleague_top": voicestats.COLLEAGUE_TOP}},
            "stats": {"purpose_min": voicestats.PURPOSE_MIN,
                      "spelling": [list(p) for p in voicestats.SPELLING],
                      "generic_phrases": generic_default()},
            "build": {"default_exemplar_count": voicebuild.DEFAULT_COUNT},
            "calls": {"retries": model.RETRIES, "timeout": model.TIMEOUT, "limit_words": list(model.LIMIT_WORDS)},
            "extraction": {"slack_window_seconds": slack.WINDOW_SECONDS, "slack_window_max": slack.WINDOW_MAX,
                           "bitbucket_cutoff": bitbucket.CUTOFF, "bitbucket_code_context": bitbucket.CODE_CONTEXT,
                           "transcript_reply_cap": transcripts.REPLY_CAP,
                           "transcript_summary_cap": transcripts.SUMMARY_CAP},
            "review": {"batch_size": batches.BATCH_SIZE, "mining_max_clients": anonymise.MINING_MAX_CLIENTS},
            "models": dict(model.MODELS),
        }
    return copy.deepcopy(_DEFAULTS)


def _bad(why):
    raise SystemExit(f"voice-decision-pipeline: {file()}: {why}")


def _num(sec, k, v, lo=None, hi=None, integer=False):
    if isinstance(v, bool) or not isinstance(v, int if integer else (int, float)):
        _bad(f"{sec}.{k} must be {'a whole number' if integer else 'a number'}")
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        _bad(f"{sec}.{k} must be between {lo} and {hi}")


def _text(sec, k, v):
    if not isinstance(v, str) or not v.strip():
        _bad(f"{sec}.{k} must be a non-empty string")


def _strings(sec, k, v, empty=False):
    if not isinstance(v, list) or (not v and not empty) or not all(isinstance(x, str) and x.strip() for x in v):
        _bad(f"{sec}.{k} must be a list of non-empty strings")


def _slots(sec, k, v, need):
    _text(sec, k, v)
    missing = [s for s in need if "{" + s + "}" not in v]
    if missing:
        _bad(f"{sec}.{k} must hold " + ", ".join("{" + s + "}" for s in missing))


def _check(d):
    au = d["audiences"]
    if not isinstance(au, list) or not au:
        _bad("audiences must be a list of {slug, name, corpus, match_prefix, routing}")
    keys = {"slug", "name", "corpus", "match_prefix", "routing"}
    for a in au:
        if not isinstance(a, dict) or set(a) != keys:
            _bad("each audience must have exactly slug, name, corpus, match_prefix and routing")
        if not re.fullmatch(r"[a-z][a-z0-9-]*", str(a["slug"])):
            _bad(f"audiences: {a['slug']!r} is not a slug (lower case letters, digits and hyphens)")
        _text("audiences", a["slug"] + ".name", a["name"])
        if not isinstance(a["corpus"], bool) or not isinstance(a["match_prefix"], bool):
            _bad(f"audiences: {a['slug']}: corpus and match_prefix must be true or false")
        _strings("audiences", a["slug"] + ".routing", a["routing"], empty=True)
    for f in ("slug", "name"):
        vs = [str(a[f]).lower() for a in au]
        if len(set(vs)) != len(vs):
            _bad(f"audiences: two audiences have the same {f}")
    if not any(a["corpus"] for a in au):
        _bad("audiences: at least one must have corpus true")
    lb = d["labels"]
    ps = lb["purposes"]
    if not isinstance(ps, dict) or not ps:
        _bad("labels.purposes must map each purpose id to its definition")
    for p, v in ps.items():
        if not re.fullmatch(r"[a-z][a-z0-9-]*", p):
            _bad(f"labels.purposes: {p!r} is not an id (lower case letters, digits and hyphens)")
        _text("labels.purposes", p, v)
    _slots("labels", "system", lb["system"], ["purposes"])
    _slots("labels", "item", lb["item"], ["n", "message"])
    _slots("labels", "batch_end", lb["batch_end"], ["n"])
    for k, lo, hi in (("before_chars", 0, 100000), ("after_chars", 0, 100000), ("batch", 1, 200),
                      ("sample", 1, 10000), ("sample_max_wrong", 0, 10000), ("disagree_sample", 0, 10000)):
        _num("labels", k, lb[k], lo, hi, True)
    g = d["guide"]
    _text("guide", "system", g["system"])
    _slots("guide", "audience_prompt", g["audience_prompt"], ["audience", "examples"])
    _slots("guide", "purpose_examples", g["purpose_examples"], ["purpose", "examples"])
    _slots("guide", "general_prompt", g["general_prompt"], ["examples"])
    _num("guide", "per_purpose", g["per_purpose"], 1, 100, True)
    _num("guide", "combined", g["combined"], 0, 200, True)
    _num("guide", "answering_chars", g["answering_chars"], 0, 100000, True)
    rd = d["render"]
    for k, v in rd.items():
        if k == "never_say_max":
            _num("render", k, v, 0, 10000, True)
        else:
            _text("render", k, v)
    j = d["judge"]
    _text("judge", "system", j["system"])
    if not isinstance(j["grades"], dict) or sorted(j["grades"]) != ["1", "2", "3", "4", "5"]:
        _bad('judge.grades must give a meaning for each of "1" to "5"')
    for k, v in j["grades"].items():
        _text("judge.grades", k, v)
    _slots("judge", "prompt", j["prompt"], ["message", "drafts"])
    _num("judge", "before_chars", j["before_chars"], 0, 100000, True)
    r = d["pass_rule"]
    for k in ("overall_bar", "audience_bar", "sure", "unsure", "grades_all", "grades_audience"):
        _num("pass_rule", k, r[k], 0, 1)
    if r["unsure"] > r["sure"]:
        _bad("pass_rule.unsure must not be above pass_rule.sure")
    for k in ("pairs_per_audience", "judge_review_worst", "judge_review_random"):
        _num("pass_rule", k, r[k], 0 if k != "pairs_per_audience" else 1, 1000, True)
    c = r["exemplar_counts"]
    if not isinstance(c, list) or not c or len(set(c)) != len(c):
        _bad("pass_rule.exemplar_counts must be a list of different whole numbers")
    for x in c:
        _num("pass_rule", "exemplar_counts", x, 1, 50, True)
    s = d["style"]
    if not isinstance(s["marks"], dict):
        _bad("style.marks must map a name to {pattern, flags}")
    for k, v in s["marks"].items():
        if not isinstance(v, dict) or set(v) - {"pattern", "flags"} or not isinstance(v.get("pattern"), str):
            _bad(f"style.marks.{k} must be {{\"pattern\": regex, \"flags\": \"\"}}")
        if set(v.get("flags", "")) - set(FLAGS):
            _bad(f"style.marks.{k}.flags may hold only i and m")
        try:
            re.compile(v["pattern"])
        except re.error as e:
            _bad(f"style.marks.{k}.pattern is not a regular expression: {e}")
    _num("style", "quoted_rare_below", s["quoted_rare_below"], 0, 1)
    ns = s["never_say"]
    if not isinstance(ns, dict) or set(ns) != set(defaults()["style"]["never_say"]):
        _bad("style.never_say must give rare_rate, ratio, colleague_min and colleague_top")
    _num("style.never_say", "rare_rate", ns["rare_rate"], 0, 1)
    _num("style.never_say", "ratio", ns["ratio"], 0, 1)
    _num("style.never_say", "colleague_min", ns["colleague_min"], 1, 100000, True)
    _num("style.never_say", "colleague_top", ns["colleague_top"], 0, 100000, True)
    st = d["stats"]
    _num("stats", "purpose_min", st["purpose_min"], 1, 100000, True)
    if not isinstance(st["spelling"], list) or not all(
            isinstance(p, list) and len(p) == 2 and all(isinstance(w, str) and re.fullmatch(r"[a-z]+", w) for w in p)
            for p in st["spelling"]):
        _bad("stats.spelling must be a list of [british, american] pairs of lower-case words")
    _strings("stats", "generic_phrases", st["generic_phrases"], empty=True)
    _num("build", "default_exemplar_count", d["build"]["default_exemplar_count"], 1, 50, True)
    ca = d["calls"]
    _num("calls", "retries", ca["retries"], 1, 20, True)
    _num("calls", "timeout", ca["timeout"], 10, 7200, True)
    _strings("calls", "limit_words", ca["limit_words"])
    ex = d["extraction"]
    for k, lo, hi in (("slack_window_seconds", 0, 7 * 86400), ("slack_window_max", 0, 1000),
                      ("bitbucket_code_context", 0, 1000), ("transcript_reply_cap", 100, 10 ** 6),
                      ("transcript_summary_cap", 10, 10 ** 5)):
        _num("extraction", k, ex[k], lo, hi, True)
    if not isinstance(ex["bitbucket_cutoff"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", ex["bitbucket_cutoff"]):
        _bad("extraction.bitbucket_cutoff must be a date, YYYY-MM-DD")
    _num("review", "batch_size", d["review"]["batch_size"], 1, 10000, True)
    _num("review", "mining_max_clients", d["review"]["mining_max_clients"], 1, 1000, True)
    m = d["models"]
    if not isinstance(m, dict) or set(m) != set(defaults()["models"]):
        _bad("models must name a model for each of " + ", ".join(defaults()["models"]))
    for k, v in m.items():
        _text("models", k, v)


def _merge(raw):
    d = defaults()
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA:
        _bad(f"schema_version must be {SCHEMA}")
    extra = sorted(set(raw) - set(SECTIONS) - {"schema_version"})
    if extra:
        _bad("unknown section " + ", ".join(extra))
    for sec in SECTIONS:
        if sec not in raw:
            continue
        v = raw[sec]
        if sec == "audiences":
            d[sec] = v
            continue
        if not isinstance(v, dict):
            _bad(f"{sec} must be an object")
        unknown = sorted(set(v) - set(d[sec]))
        if unknown:
            _bad(f"{sec}: unknown {'role' if sec == 'models' else 'key'} {', '.join(unknown)}")
        for k, x in v.items():
            d[sec][k] = x if (sec, k) in WHOLE or not isinstance(x, dict) else {**d[sec][k], **x}
    _check(d)
    return d


def load():
    """The settings, the file's over the defaults; the file is written with
    the defaults if there is none. Read again only when the file changes."""
    f = file()
    if not os.path.exists(f):
        state.write_json(f, defaults())
    st = os.stat(f)
    stamp = (f, st.st_mtime_ns, st.st_size)
    if _CACHE.get("stamp") != stamp:
        _CACHE.update(stamp=stamp, d=_merge(state.read_json(f, None)))
    return copy.deepcopy(_CACHE["d"])


def get(section):
    return load()[section]


def purposes():
    return get("labels")["purposes"]


def model(role):
    return get("models")[role]


def audiences():
    return get("audiences")


def corpus_audiences():
    return tuple(a["slug"] for a in audiences() if a["corpus"])


def audience_slugs():
    """{mapping-page name: slug} of the corpus audiences."""
    return {a["name"]: a["slug"] for a in audiences() if a["corpus"]}


def style_marks():
    """{name: compiled regex} of the marks of style."""
    out = {}
    for k, v in get("style")["marks"].items():
        fl = 0
        for c in v.get("flags", ""):
            fl |= FLAGS[c]
        out[k] = re.compile(v["pattern"], fl)
    return out


def _nondefault(cur, base):
    return {k: v for k, v in cur.items() if v != base[k]}


def draft_inputs(d=None):
    """What of these settings changes the drafter's prompt or model, where it
    differs from the defaults: {} under the defaults, so every method stays
    as it was."""
    d = d or load()
    dd = defaults()
    pick = lambda x: {"style": x["style"], "render": x["render"], "stats": x["stats"],
                      "drafter_model": x["models"]["drafter"], "brief_model": x["models"]["brief"]}
    return _nondefault(pick(d), pick(dd))


def label_inputs(d=None):
    """The labeller's item text and context sizes, where they differ from
    the defaults: they join the label prompt version."""
    d = d or load()
    dd = defaults()
    ks = ("item", "batch_end", "before_chars", "after_chars")
    return _nondefault({k: d["labels"][k] for k in ks}, {k: dd["labels"][k] for k in ks})


def changed(d=None):
    """[section.key] that differ from the defaults, for `voice settings`."""
    d = d or load()
    dd = defaults()
    out = ["audiences"] if d["audiences"] != dd["audiences"] else []
    for s in SECTIONS:
        if s == "audiences":
            continue
        out += [f"{s}.{k}" for k in d[s] if d[s][k] != dd[s].get(k)]
    return out


def pass_rule_log():
    return state.path("validation", "pass-rule.jsonl")


def record_pass_rule(run):
    """Append the pass rule to validation/pass-rule.jsonl with the run it
    applies to, when it differs from the last one recorded. Returns the run
    the current rule has applied from."""
    rule = get("pass_rule")
    last = None
    for r in state.read_jsonl(pass_rule_log()):
        last = r
    if last is not None and last["rule"] == rule:
        return last["run"]
    import time
    row = {"run": run, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "rule": rule}
    with open(pass_rule_log(), "a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")
    os.chmod(pass_rule_log(), 0o600)
    return run


# -- saved copies ------------------------------------------------------------
#
# The history of the hand-edited files: each one whose text differs from its
# newest saved copy is copied to the next number beside it (settings-11.json,
# voice/drafter-7.json, own-rules-1.md), owner-only, and settings-history.md
# gets a line saying what was saved when. Every command does this before it
# runs (__main__.main), so each version a run used is kept; `voice settings
# --save` does it on demand and says what it left unchanged.

SAVED = (("settings.json", ""), ("drafter.json", "voice"), ("labelling-notes.md", ""),
         ("own-rules.md", ""), ("struck-rules.md", ""))


def history_file():
    return state.path("settings-history.md")


def _copies(name, sub):
    stem, ext = os.path.splitext(name)
    d = os.path.dirname(state.path(sub, name)) if sub else state.root()
    rx = re.compile(re.escape(stem) + r"-(\d+)" + re.escape(ext) + r"$")
    found = sorted((int(m.group(1)), f) for f in os.listdir(d) for m in [rx.match(f)] if m)
    return d, stem, ext, found


def save_copies(log=print, quiet=False):
    """[(saved path, source path)]: the next numbered copy of each file whose
    text has changed since its newest copy. Files that don't exist are skipped."""
    import time
    out = []
    for name, sub in SAVED:
        src = state.path(sub, name) if sub else state.path(name)
        if not os.path.exists(src):
            continue
        with open(src, encoding="utf-8") as f:
            text = f.read()
        d, stem, ext, found = _copies(name, sub)
        if found:
            with open(os.path.join(d, found[-1][1]), encoding="utf-8") as f:
                if f.read() == text:
                    if not quiet:
                        log(f"  --    {name}: unchanged since {found[-1][1]}")
                    continue
        n = found[-1][0] + 1 if found else 1
        dest = os.path.join(d, f"{stem}-{n}{ext}")
        state.write_text(dest, text)
        out.append((dest, src))
        log(f"  ok    {name} saved as {os.path.relpath(dest, state.root())}")
    if out:
        hf = history_file()
        head = "## Saved with voice settings --save"
        cur = open(hf, encoding="utf-8").read() if os.path.exists(hf) else "# Settings history\n"
        if head not in cur:
            cur = cur.rstrip("\n") + "\n\n" + head + "\n\n"
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cur += "".join(f"- {os.path.relpath(dst, state.root())}: copy of {os.path.relpath(s, state.root())}, {ts}\n"
                       for dst, s in out)
        state.write_text(hf, cur)
    return out
