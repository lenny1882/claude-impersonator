"""Made-up voice builds and a stand-in embedding_lib for the tests. Nothing
here comes from a real corpus: every message, rule and figure is invented.

  fixtures.py build <dir> <build-time> [--variant a|b] [--schema FILE=N]
                    [--listed FILE=N]
      writes a voice-runtime build directory as the pipeline would
      (contract §1). Variant b changes one exemplar's text and adds one, so
      an install of b after a must embed exactly two pairs.
  fixtures.py fake-el <dir>
      writes <dir>/pylib/embedding_lib: a deterministic bag-of-words embed
      (64 dimensions, each word hashed to one), an identity() whose `python`
      comes from FAKE_EL_PYTHON, and a log of every text embedded
      (FAKE_EMBED_LOG), so the suite needs no model.
"""

import hashlib
import json
import os
import sys

EXEMPLARS_A = [
    ("ex-001", "technical-team", ["status"],
     "the deploy pipeline is green again, migration ran fine on staging",
     "how is the staging deploy looking"),
    ("ex-002", "technical-team", ["ask"],
     "can you take a look at the retry logic in the queue worker",
     ""),
    ("ex-003", "technical-team", ["push-back"],
     "another cache layer won't help here, the database query is the slow part",
     "should we put a cache in front of the reports endpoint"),
    ("ex-004", "technical-team", ["status", "ask"],
     "tests pass locally now, could someone review the branch before lunch",
     ""),
    ("ex-005", "clients", ["decline"],
     "We won't be able to fit the export change into this sprint, but it is first in the next one.",
     "Could the export change go in this week?"),
    ("ex-006", "clients", ["status"],
     "The new release is live on staging for you to try.",
     ""),
    ("ex-007", "project-team", ["chase"],
     "any news on the design files for the onboarding screens",
     ""),
]


def pair(answered, text):
    return answered + "\n\n" + text


def exemplar(i, aud, purposes, text, answered):
    return {"id": i, "audience": aud, "purposes": purposes, "text": text,
            "answered": answered,
            "hash": hashlib.sha256(pair(answered, text).encode("utf-8")).hexdigest()}


def build(out, bt, variant="a", schema=None, listed=None):
    schema = schema or {}
    listed = listed or {}
    rows = list(EXEMPLARS_A)
    if variant == "b":
        rows[1] = ("ex-002", "technical-team", ["ask"],
                   "can you look at the retry logic in the queue worker today please", "")
        rows.append(("ex-008", "technical-team", ["thank"],
                     "thanks for jumping on the flaky test so quickly", ""))
    os.makedirs(out, exist_ok=True)
    files = {
        "guide.json": {
            "schema_version": 1, "build_time": bt,
            "own_rules": ["OWN-RULE never sign off with a name"],
            "general": ["GENERAL-RULE short sentences"],
            "combinations": ["COMBINE-RULE news before the ask"],
            "audiences": {
                "technical-team": {"rules": ["TECH-RULE lower case start is fine"],
                                   "purposes": {"status": ["TECH-STATUS-RULE say what ran"],
                                                "ask": ["TECH-ASK-RULE one ask per message"]}},
                "clients": {"rules": ["CLIENT-RULE full sentences, never 'kindly'"],
                            "purposes": {"decline": ["CLIENT-DECLINE-RULE offer a date"]}},
            },
            "jira": ["JIRA-RULE state the outcome first"],
        },
        "exemplars.json": {"schema_version": 1,
                           "exemplars": [exemplar(*r) for r in rows]},
        "stats.json": {
            "schema_version": 1,
            "audiences": {"technical-team": {
                "messages": 40, "median_words": 14, "p90_words": 41,
                "lowercase_start": 0.8, "full_stop_end": 0.2,
                "exclamation_per_message": 0.05, "emoji_per_message": 0.1,
                "style": {"spaced dash": 0.14, "exclamation mark": 0.06},
                "openings": [["hi", 5]], "signoffs": [["thanks", 2]]}},
            "quoted": {"clients": {"kindly": 0.001}, "technical-team": {"kindly": 0.001}},
            "drafting": {"notes": {"clients": ["CLIENT-NOTE as few words"]},
                         "quoted_rates_for": ["clients"], "rare_below": 0.02},
            "spelling": {"british": 30, "american": 1},
            "never_say": [{"phrase": "hope this helps", "self": 0,
                           "reference": "generic", "reference_count": 0}],
        },
    }
    for name, v in schema.items():
        if name != "build.json":
            files[name]["schema_version"] = v
    lst = {"guide.json": 1, "exemplars.json": 1, "stats.json": 1}
    lst.update(listed)
    files["build.json"] = {"schema_version": schema.get("build.json", 1), "build_time": bt,
                           "files": lst, "embedding_identity": {"model": "fake"},
                           "exemplar_count": 3}
    for name, obj in files.items():
        with open(os.path.join(out, name), "w") as f:
            json.dump(obj, f, indent=1)


FAKE_EL = r'''"""Stand-in embedding_lib for voice-runtime's tests."""
import hashlib, json, os
import numpy as np

EMBEDDING_LIB_API = int(os.environ.get("FAKE_EL_API", "1"))
DIMENSION = 64
MAX_TOKENS = int(os.environ.get("FAKE_EL_MAX_TOKENS", "512"))
COMPARED = ("api", "model", "revision", "dimension", "normalised", "python", "lock_sha256")


class Mismatch(ValueError):
    pass


def identity():
    return {"api": EMBEDDING_LIB_API, "model": "fake-bag-of-words", "revision": "0",
            "dimension": DIMENSION, "normalised": True,
            "python": os.environ.get("FAKE_EL_PYTHON", "3.14.10"),
            "lock_sha256": "0" * 64, "libraries": {}}


def _log(texts):
    p = os.environ.get("FAKE_EMBED_LOG")
    if p:
        with open(p, "a") as f:
            for t in texts:
                f.write(json.dumps(t) + "\n")


def embed(texts, batch_size=32):
    if os.environ.get("FAKE_EL_FAIL"):
        raise RuntimeError("fake embed failure")
    texts = list(texts)
    _log(texts)
    out = np.zeros((len(texts), DIMENSION), dtype=np.float32)
    for i, t in enumerate(texts):
        for w in t.lower().split():
            w = w.strip(".,?!")
            if w:
                out[i, int(hashlib.md5(w.encode()).hexdigest(), 16) % DIMENSION] += 1
        n = np.linalg.norm(out[i])
        if n:
            out[i] /= n
    return out


def count_tokens(texts):
    return [len(t.split()) + 2 for t in texts]
'''


def fake_el(out):
    d = os.path.join(out, "pylib", "embedding_lib")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "__init__.py"), "w") as f:
        f.write(FAKE_EL)


def kv(items):
    out = {}
    for it in items:
        k, v = it.split("=", 1)
        out[k] = int(v) if v.lstrip("-").isdigit() else v
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "build":
        opts = {"--variant": "a", "--schema": [], "--listed": []}
        rest = a[3:]
        while rest:
            k, v = rest[0], rest[1]
            rest = rest[2:]
            if isinstance(opts[k], list):
                opts[k].append(v)
            else:
                opts[k] = v
        build(a[1], a[2], opts["--variant"], kv(opts["--schema"]), kv(opts["--listed"]))
    elif a[0] == "fake-el":
        fake_el(a[1])
    else:
        sys.exit("unknown fixture " + a[0])
