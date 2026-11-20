"""Made-up state for the voice build's tests (no real person or message):

    python voice_fixtures.py <state dir> <bin dir> <pylib dir>

writes into <state dir> a corpus and its anonymised copy of 90 voice items
across the five corpus audiences, inputs, an anonymising map and an
approved first batch for Slack and Bitbucket; into <bin dir> a stand-in
`claude`; into <pylib dir> a stand-in `embedding_lib` (a deterministic
hash embedding, no model).

The stand-in claude answers by the JSON schema it is given: labels (a "?"
makes "ask", else "status"; the second model also adds "thank" to messages
holding "thanks", so the two disagree there), guide rules, a draft, judge
scores (the draft made with 5 exemplars scores best). FAKE_CLAUDE_LIMIT=<n>
makes the n-th call and after answer with a usage limit (worded as
FAKE_CLAUDE_LIMIT_TEXT when set); calls are counted
in FAKE_CLAUDE_COUNT (a file).
"""

import hashlib
import json
import os
import sys

STATE, BIN, PYLIB = sys.argv[1:4]
AUDS = ["clients", "project team", "technical team", "senior/management", "1:1 colleagues"]
LINES = [
    "can you look at the release notes before Friday?",
    "status: the build is green and the fix is merged",
    "thanks for sorting the deploy, much quicker than I expected",
    "no, we're not doing that this sprint, the risk is too high",
    "here is how the cache works: [see below] it expires after ten minutes",
    "ok go ahead, approved",
    "did you get a chance to send the log?",
    "ok",
    "```\nTraceback\n  line 1\n```",
]


def anon_id(rid):
    return "r" + hashlib.sha1(rid.encode()).hexdigest()[:16]


def w(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(obj, str):
            f.write(obj)
        else:
            json.dump(obj, f, indent=1)


def jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")


def tags_for(text):
    if text.startswith("```"):
        return [{"type": "code", "start": 0, "end": len(text)}]
    return []


real, anon = [], []
for i in range(90):
    aud = AUDS[i % 5]
    conv = f"C{i % 5}"
    other_id, me_id = f"slack:{conv}:o{i}", f"slack:{conv}:m{i}"
    ts_o, ts_m = f"2024-01-01T00:{i // 60:02d}:{i % 60:02d}.000Z", f"2024-01-01T01:{i // 60:02d}:{i % 60:02d}.000Z"
    text = LINES[i % len(LINES)] + ("" if i < 9 else f" (item {i})")
    if i % len(LINES) == len(LINES) - 1:
        text = LINES[-1]
    q = f"question {i} from a colleague about the work?"
    base = {"source": "slack", "conversation": conv, "audience": aud, "reactions": [],
            "source_fields": {}, "schema_version": 1}
    real.append({**base, "id": other_id, "author": "UOTHER", "ts": ts_o, "text": q,
                 "tags": [], "context_ids": [me_id]})
    real.append({**base, "id": me_id, "author": "UME", "ts": ts_m, "text": text,
                 "tags": [{"type": "item"}] + tags_for(text), "context_ids": [other_id]})
    anon.append({**base, "id": anon_id(other_id), "conversation": anon_id(conv), "author": "colleague-01",
                 "ts": ts_o, "text": q, "tags": [], "context_ids": [anon_id(me_id)], "replacements": []})
    anon.append({**base, "id": anon_id(me_id), "conversation": anon_id(conv), "author": "self-01",
                 "ts": ts_m, "text": text, "tags": [{"type": "item"}] + tags_for(text),
                 "context_ids": [anon_id(other_id)], "replacements": []})
jsonl(f"{STATE}/corpus/slack.jsonl", real)
jsonl(f"{STATE}/anon/slack.jsonl", anon)
jsonl(f"{STATE}/corpus/bitbucket.jsonl", [])
jsonl(f"{STATE}/anon/bitbucket.jsonl", [])
w(f"{STATE}/inputs.json", {"self_user_id": "UME", "conversations": [], "slack_export": "/nowhere",
                           "struck_conversations": [], "struck_authors": [], "bitbucket_repos": [],
                           "transcript_imports": []})
w(f"{STATE}/anonymising-map.json", {"schema_version": 1, "counters": {"self": 1, "colleague": 1, "client": 1},
                                    "entries": [
    {"real_id": "UME", "aliases": ["Sam Fixture"], "kind": "person", "role": "self", "pseudonym": "self-01", "origin": "users.json"},
    {"real_id": "UOTHER", "aliases": ["Robin Madeup"], "kind": "person", "role": "colleague", "pseudonym": "colleague-01", "origin": "users.json"},
    {"real_id": "client:zarnwick", "aliases": ["Zarnwick"], "kind": "client", "role": "client", "pseudonym": "client-01", "origin": "list"}]})
w(f"{STATE}/leak-report.json", {"terms_checked": 3, "undecided_names": 0, "hits": 0, "terms": []})
w(f"{STATE}/review-state.json", {s: {"batches": [], "approved": 1 if s in ("slack", "bitbucket") else 0, "stopped": False}
                           for s in ("slack", "transcripts", "bitbucket", "gsd")})

w(f"{BIN}/claude", r'''#!/usr/bin/env python3
import json, os, re, sys
args = sys.argv[1:]
schema = json.loads(args[args.index("--json-schema") + 1])
model = args[args.index("--model") + 1]
prompt = sys.stdin.read()
cf = os.environ.get("FAKE_CLAUDE_COUNT")
n = 0
if cf:
    try: n = int(open(cf).read() or 0)
    except FileNotFoundError: n = 0
    n += 1
    open(cf, "w").write(str(n))
lim = int(os.environ.get("FAKE_CLAUDE_LIMIT") or 0)
if lim and n >= lim:
    print(json.dumps({"type": "result", "is_error": True, "result": os.environ.get("FAKE_CLAUDE_LIMIT_TEXT") or "Claude AI usage limit reached|1700000000"}))
    sys.exit(1)
props = schema.get("properties", {})
if "items" in props:
    out = []
    for m in re.finditer(r"### Item (\d+).*?Message by self-01:\n(.*?)\n(?=After:|### Item|\nGive)", prompt + "\n### Item", re.S):
        t = m.group(2)
        ps = ["ask"] if "?" in t else ["status"]
        if "opus" in model and "thanks" in t:
            ps = ps + ["thank"]
        out.append({"n": int(m.group(1)), "purposes": ps})
    ans = {"items": out}
elif "purposes" in props and "rules" in props:
    ans = {"rules": ["keep it short", "no greeting"],
           "purposes": {k: [f"for {k}: say it plainly"] for k in props["purposes"]["required"]}}
elif "general" in props:
    ans = {"general": ["write in lower case at the start"], "combinations": ["news before the objection"]}
elif "brief" in props:
    ans = {"brief": "brief: " + prompt.split("The message:\n")[1].split("\n\nWrite its brief")[0][:40]}
elif "text" in props:
    k = prompt.split("Examples of messages")[1].count("---") + 1
    ans = {"text": f"draft with {k} examples" + (" from a brief" if "\nbrief: " in prompt else "")}
elif "scores" in props:
    ds = re.findall(r"Draft (\d+):\ndraft with (\d+) examples", prompt)
    assert "The brief the drafts were written from:\nbrief: " in prompt
    ans = {"scores": [{"draft": int(d), "score": 4 if k == "5" else 3, "reason": "fake"} for d, k in ds]}
else:
    ans = {}
print(json.dumps({"type": "result", "is_error": False, "result": json.dumps(ans), "structured_output": ans}))
''')
os.chmod(f"{BIN}/claude", 0o755)

w(f"{PYLIB}/embedding_lib/__init__.py", '''"""Stand-in embedding_lib for the tests: a hash embedding, no model."""
import hashlib
import numpy as np
EMBEDDING_LIB_API = 1
def identity():
    return {"api": 1, "model": "fake-hash", "revision": "0", "dimension": 16, "normalised": True}
def embed(texts, batch_size=32):
    out = []
    for t in texts:
        v = np.frombuffer(hashlib.sha256(t.encode()).digest()[:16], dtype=np.uint8).astype("float32") - 127.5
        out.append(v / np.linalg.norm(v))
    return np.vstack(out) if out else np.zeros((0, 16), "float32")
def count_tokens(texts):
    return [len(t.split()) for t in texts]
''')
