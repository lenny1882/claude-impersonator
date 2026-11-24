"""The voice settings that are tuned rather than built (PLAN §8.2), read from
the state's voice/settings.json, so changing one needs no new release. The
drafter's own prompts and notes are in voice/drafter.json (drafter.py).

  labels     purposes    {id: definition}, in the order the labeller is
                         shown them; the ids are what labels, pairs and
                         builds carry
             system      the labeller's and the second pass's system
                         prompt; "{purposes}" is replaced by the list
  guide      system      the guide writer's system prompt
             per_purpose examples shown per audience and purpose
             combined    multi-purpose examples shown for the combining rules
  judge      system      the judge's system prompt, before the grade line
             grades      {"5": meaning, ... "1": meaning}: the judge's scale,
                         and the owner's grade buttons
  pass_rule  the validation pass rule (validate.py): overall_bar,
             audience_bar, sure, unsure, grades_all, grades_audience,
             pairs_per_audience, exemplar_counts, judge_review_worst,
             judge_review_random. Each change is recorded with the run it
             applies to, in validation/pass-rule.jsonl.
  style      marks       {name: {"pattern": regex, "flags": "i"/"m"/""}}:
                         the marks of style whose share per audience the
                         drafter is shown
             quoted_rare_below  a word a rule quotes is shown with its share
                         when fewer messages than this hold it
             never_say   rare_rate, ratio, colleague_min, colleague_top
                         (voicestats.py)
  models     {role: model id} for labeller, second, drafter, judge, brief,
             guide

The file is written with the defaults the first time it is read. A section
or key left out takes its default; an unknown one is refused. The style
section and the drafter's and brief writer's models change what the drafter
is shown, so they join each audience's draft method (drafter.py) wherever
they differ from the defaults: change one and every audience is drafted and
paired again, while the defaults leave every method as it was.
"""

import copy
import json
import os
import re

from . import state

SCHEMA = 1
SECTIONS = ("labels", "guide", "judge", "pass_rule", "style", "models")
# Keys whose value is replaced whole, not merged key by key.
WHOLE = {("labels", "purposes"), ("judge", "grades"), ("style", "marks"), ("style", "never_say")}
FLAGS = {"i": re.I, "m": re.M}

_DEFAULTS = None
_CACHE = {}


def file():
    return state.path("voice", "settings.json")


def defaults():
    """The settings the code ships, built from each module's own constants."""
    global _DEFAULTS
    if _DEFAULTS is None:
        from . import guide, labels, model, validate, voice, voicestats
        _DEFAULTS = {
            "schema_version": SCHEMA,
            "labels": {"purposes": dict(voice.PURPOSES), "system": labels.SYSTEM},
            "guide": {"system": guide.SYSTEM, "per_purpose": guide.PER_PURPOSE, "combined": guide.COMBINED},
            "judge": {"system": validate.JUDGE_BASE, "grades": {str(k): v for k, v in validate.GRADES.items()}},
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


def _check(d):
    lb = d["labels"]
    ps = lb["purposes"]
    if not isinstance(ps, dict) or not ps:
        _bad("labels.purposes must map each purpose id to its definition")
    for p, v in ps.items():
        if not re.fullmatch(r"[a-z][a-z0-9-]*", p):
            _bad(f"labels.purposes: {p!r} is not an id (lower case letters, digits and hyphens)")
        _text("labels.purposes", p, v)
    _text("labels", "system", lb["system"])
    if "{purposes}" not in lb["system"]:
        _bad("labels.system must hold {purposes}, where the purpose list goes")
    g = d["guide"]
    _text("guide", "system", g["system"])
    _num("guide", "per_purpose", g["per_purpose"], 1, 100, True)
    _num("guide", "combined", g["combined"], 0, 200, True)
    j = d["judge"]
    _text("judge", "system", j["system"])
    if not isinstance(j["grades"], dict) or sorted(j["grades"]) != ["1", "2", "3", "4", "5"]:
        _bad('judge.grades must give a meaning for each of "1" to "5"')
    for k, v in j["grades"].items():
        _text("judge.grades", k, v)
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
        if not isinstance(v, dict):
            _bad(f"{sec} must be an object")
        if sec == "models":
            unknown = sorted(set(v) - set(d[sec]))
            if unknown:
                _bad(f"models: unknown role {', '.join(unknown)}")
            d[sec].update(v)
            continue
        unknown = sorted(set(v) - set(d[sec]))
        if unknown:
            _bad(f"{sec}: unknown key {', '.join(unknown)}")
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


def style_marks():
    """{name: compiled regex} of the marks of style."""
    out = {}
    for k, v in get("style")["marks"].items():
        fl = 0
        for c in v.get("flags", ""):
            fl |= FLAGS[c]
        out[k] = re.compile(v["pattern"], fl)
    return out


def draft_inputs(d=None):
    """What of these settings changes the drafter's prompt, where it differs
    from the defaults: {} under the defaults, so every method stays as it was."""
    d = d or load()
    dd = defaults()
    cur = {"style": d["style"], "drafter_model": d["models"]["drafter"], "brief_model": d["models"]["brief"]}
    base = {"style": dd["style"], "drafter_model": dd["models"]["drafter"], "brief_model": dd["models"]["brief"]}
    return {k: v for k, v in cur.items() if v != base[k]}


def changed(d=None):
    """[section.key] that differ from the defaults, for `voice settings`."""
    d = d or load()
    dd = defaults()
    return [f"{s}.{k}" for s in SECTIONS for k in d[s] if d[s][k] != dd[s].get(k)] + \
           [f"{s}.{k}" for s in SECTIONS for k in dd[s] if k not in d[s]]


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
