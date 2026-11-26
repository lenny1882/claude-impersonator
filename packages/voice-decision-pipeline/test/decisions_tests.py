"""Decision extraction (PLAN §4.9) on made-up anonymised records added to the
voice fixtures' state, with the stand-in claude:

    python decisions_tests.py

VDP_STATE, VDP_CLAUDE and PYTHONPATH are set by run-tests.sh. Prints one
"ok <name>" or "FAIL <name>: <why>" line per check.
"""

import json
import os

from vdp import decisions, decisionsreview, gsd, settings, state

RESULTS = []


def check(name, cond, why=""):
    RESULTS.append(name)
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f": {why}"), flush=True)


def rec(i, conv, ts, text, author="self-01", source="transcripts", flags=("item", "no-voice"), sf=None):
    return {"id": i, "source": source, "conversation": conv, "author": author, "audience": None, "ts": ts,
            "text": text, "tags": [{"type": f} for f in flags], "context_ids": [], "reactions": [],
            "source_fields": sf or {}, "replacements": [], "schema_version": 1}


T = []
# A session: Claude offers two numbered choices; the owner answers "2";
# then ordinary messages, one far enough on to start no unit of its own.
T.append(rec("t1", "s1", "2024-02-01T10:00:00Z", "2",
             sf={"preceding_reply": "Which store?\n1. postgres (recommended)\n2. sqlite\nWhich one?", "project": "proj-01"}))
for k in range(2, 12):
    T.append(rec(f"t{k}", "s1", f"2024-02-01T10:{k:02d}:00Z", f"carry on with step {k}",
                 sf={"preceding_reply": f"done step {k}", "project": "proj-01"}))
# An AskUserQuestion answer, in another session.
T.append(rec("t20", "s2", "2024-02-02T09:00:00Z", "",
             flags=("item", "ask-user", "no-voice"),
             sf={"questions": [{"question": "Which test runner should the store layer use?", "header": "Test runner",
                                "options": ["vitest (Recommended)", "jest"]}],
                 "answers": {"Which test runner should the store layer use?": "vitest (Recommended)"},
                 "preceding_reply": "", "project": "proj-01"}))
# A correction.
T.append(rec("t30", "s3", "2024-02-03T09:00:00Z", "no, don't add a cache there",
             sf={"preceding_reply": "I added a cache.", "project": "proj-01"}))
state.write_jsonl(state.anon_file("transcripts"), T)
G = [rec("g1", "gsd-1", "2024-02-05T00:00:00Z", "Test runner\nUse vitest for the store layer, rather than jest.",
         source="gsd", sf={"kind": "context-decision", "file": "phases/01/01-CONTEXT.md", "section": "Test runner",
                           "repo_name": "proj-01"}),
     rec("g2", "gsd-1", "2024-02-05T00:00:00Z", "[Rule 3 - Blocking] Installed jose\n- **Fix:** npm install jose",
         source="gsd", flags=("item", "no-voice", "deviation:rule-3"),
         sf={"kind": "deviation", "file": "phases/01/01-01-SUMMARY.md", "rule": 3, "repo_name": "proj-01"})]
state.write_jsonl(state.anon_file("gsd"), G)

us = decisions.units(log=lambda *a: None)
by = {tuple(u["records"]): u for u in us}
t_units = [u for u in us if u["source"] == "transcripts"]
first = next(u for u in t_units if "t1" in u["records"])
check("a numbered-choice reply and its answer start a unit with the next 6 messages",
      first["candidate"] and first["records"] == [f"t{k}" for k in range(1, 8)], first["records"])
check("messages after that window are sample-pool units of their own",
      all(not u["candidate"] and len(u["records"]) == 1 for u in t_units if u["records"][0] in ("t8", "t9", "t10", "t11")))
check("an AskUserQuestion answer is a candidate, its question and answer in the text",
      any(u["candidate"] and "[Claude asked] Which test runner" in u["text"] and "vitest (Recommended)" in u["text"]
          for u in t_units))
check("a correction is a candidate", any(u["candidate"] and "t30" in u["records"] for u in t_units))
g = [u for u in us if u["source"] == "gsd"]
check("every GSD record is a candidate unit", len(g) == 2 and all(u["candidate"] for u in g))
check("a CONTEXT.md decision carries its discuss session's question",
      any("[from its discuss session]" in u["text"] and "Which test runner" in u["text"] for u in g))
check("the sample grows step by step, each step holding the one before",
      decisions.sample(us, 1) <= decisions.sample(us, 2) and len(decisions.sample(us, 2)) >= len(decisions.sample(us, 1)))

# Approval.
try:
    decisions.run("first", log=lambda *a: None)
    ran = True
except SystemExit as e:
    ran = "isn't approved" not in str(e)
check("no pass runs before the prompt is approved", not ran)
page = decisionsreview.get("/decisions/prompt")
check("the prompt page shows the prompt, the kinds and an approve button",
      "libraries-tooling" in page and "Approve this prompt" in page and "A decision is a choice" in page)
decisionsreview.post("/api/decisions/approve", {"version": decisions.prompt_version()})
check("approving records the prompt version", decisions.approved())
s = settings.load()
s["decisions"]["kinds"] = {**s["decisions"]["kinds"], "other": "anything else at all"}
state.write_json(settings.file(), s)
check("a changed kind definition needs approving again", not decisions.approved())
decisionsreview.post("/api/decisions/approve", {"version": decisions.prompt_version()})

# The passes.
rc1 = decisions.run("first", log=lambda *a: None)
rc2 = decisions.run("second", log=lambda *a: None)
f, s2 = decisions.read_pass("first"), decisions.read_pass("second")
sent = decisions.to_send(decisions.units(log=lambda *a: None))
check("both passes read every candidate and sampled unit", rc1 == rc2 == 0 and len(f) == len(s2) == len(sent),
      (rc1, rc2, len(f), len(s2), len(sent)))
cf = os.environ.get("FAKE_CLAUDE_COUNT")
before = int(open(cf).read()) if cf and os.path.exists(cf) else None
decisions.run("first", log=lambda *a: None)
check("a rerun sends nothing already read", before is None or int(open(cf).read()) == before)
ds = decisions.disagreements()
check("a unit the passes read differently is a disagreement, naming the field",
      ds and all(d["fields"] == ["kind"] for d in ds), ds)
d = decisions.draw_disagreements()
c = decisions.draw_check()
check("the disagreement sample and the case check are drawn", d["ids"] and c["ids"], (d, c))
check("the final reading is the second pass's", all(cs and cs[0]["kind"] in decisions.cfg()["kinds"]
                                                     for cs in decisions.final().values() if cs))
u = d["ids"][0]
decisionsreview.post("/api/decisions/disagree", {"unit": u, "pick": "first"})
check("a disagreement graded for the first pass takes its reading",
      decisions.final()[u][0]["kind"] == f[u]["decisions"][0]["kind"])
decisionsreview.post("/api/decisions/disagree", {"unit": u, "pick": "neither"})
check("a unit graded Neither is left out", u not in decisions.final())
for ref in c["ids"]:
    decisionsreview.post("/api/decisions/check", {"ref": ref, "verdict": "right"})
r = decisions.check_result()
check("a case check with nothing wrong passes", r["done"] and r["passed"], r)
for pg in ("/decisions", "/decisions/check", "/decisions/disagree"):
    html = decisionsreview.get(pg)
    check(f"page {pg} renders", html and "Traceback" not in html)
k = decisions.catch_rate()
check("the catch rate is worked out from the sample", "state" in k and k.get("read", 0) >= 0, k)
decisions.sample_more(log=lambda *a: None)
check("sample-more adds a step", decisions.sample_state()["step"] == 2)

# Deviation entries in SUMMARY.md, in the formats seen.
txt = """## Deviations from Plan

**1. [Rule 1 - Bug] Fixed a thing**
- **Fix:** it

**2. [Rule 3 — Blocking] `x` installed; more words
- **Fix:** ran it

**3. [Rule 4 deferred, asked the owner] Kept the old API.** detail

**4. [Rule 1] Short**
---
**Total deviations:** 4
"""
dv = gsd.deviations(txt)
check("deviation entries are read in every format seen",
      [(x[0], x[2]) for x in dv] == [(1, "Fixed a thing"), (3, "`x` installed; more words"),
                                     (4, "Kept the old API. detail"), (1, "Short")], dv)
check("a deviation's body stops at the rule line", "Total deviations" not in dv[-1][3])
print(f"{len(RESULTS)} decisions checks")
