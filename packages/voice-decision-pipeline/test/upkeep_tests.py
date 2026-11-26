"""The upkeep's behaviour (PLAN §3.8) on made-up drafts against the voice
fixtures' corpus (voice_fixtures.py), with the stand-in claude:

    python upkeep_tests.py

VDP_STATE, VDP_CLAUDE and PYTHONPATH are set by run-tests.sh. Prints one
"ok <name>" or "FAIL <name>: <why>" line per check.
"""

import datetime
import json
import os
import subprocess
import sys

from vdp import guide, labels, settings, state, upkeep, voice, voicereview

ST = os.environ["VDP_STATE"]
RESULTS = []


def check(name, cond, why=""):
    RESULTS.append(name)
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f": {why}"), flush=True)


def rec(i, kind, dest, text, ts, status, aud="clients", ps=("ask",)):
    return {"id": i, "ts": ts, "kind": kind, "audience": aud, "purposes": list(ps), "destination": dest,
            "text": text, "status": status, "build_time": None, "host": "h", "schema_version": 1}


def draft(i, dest, first, final, fts, status="approved", aud="clients", dts=None):
    out = [rec(i, "draft", dest, first, dts or fts, "drafted", aud)]
    if status:
        out.append(rec(i, "final", dest, final, fts, status, aud))
    return out


# The fixtures' owner messages: item i in conversation C<i % 5>, at 2024-01-01T01:MM:SS, with the
# text of line i % 9 (and " (item i)" from 9 on).
RECS = []
RECS += draft("d0", "slack:C0", "Hi all, can you look at the release notes before Friday?",
           "Hi all, can you look at the release notes before Friday?", "2024-01-01T00:59:30Z")
RECS += draft("d5", "slack:C0", "Hi all, ok go ahead, approved", "Hi all, ok go ahead, approved", "2024-01-01T00:59:40Z")
RECS += draft("d10", "slack:C0", "Hi all, can you look at the release notes before Friday? (item 45)",
           "Hi all, can you look at the release notes before Friday? (item 45)", "2024-01-01T00:59:50Z")
# Sent as approved: matched, not edited.
RECS += draft("d1", "slack:C1", "status: the build is green and the fix is merged",
           "status: the build is green and the fix is merged", "2024-01-01T00:59:00Z", aud="project-team")
# Approved two days before it was sent: no match within the hour, held as a near-copy.
RECS += draft("d2", "slack:C2", "thanks for sorting the deploy, much quicker than I expected",
           "thanks for sorting the deploy, much quicker than I expected", "2023-12-30T00:00:00Z",
           aud="technical-team", dts="2023-12-30T00:00:00Z")
RECS += draft("dx", "slack:C3", "Dear team, I regret to inform you", "Dear team, I regret to inform you",
           "2024-01-01T00:10:00Z", status="discarded", aud="senior")
RECS += draft("dj", "jira:ABC-1", "Looks good to me, merging now.", "Looks good, merging.", "2024-01-01T00:10:00Z", aud="jira")
# Written after every fixture message: nothing can be a copy of it.
RECS += draft("dlate", "slack:C0", "can you look at the release notes before Friday?",
           "can you look at the release notes before Friday?", "2024-06-01T00:00:00Z")
src = os.path.join(ST, "..", "drafts-in.jsonl")
with open(src, "w") as f:
    for r in RECS:
        f.write(json.dumps(r) + "\n")
upkeep.import_records(src, log=lambda *a: None)
check("import reads every record", len(list(state.read_jsonl(upkeep.records_file()))) == len(RECS))

# What anonymise writes for drafts; the fixtures hold no real names.
state.write_jsonl(upkeep.anon_file(), [{"id": x["id"], "audience": x["audience"], "purposes": x["purposes"],
                                        "status": x["status"], "first": x["first"], "final": x["final"]}
                                       for x in upkeep.drafts().values()])
items_before = {it["id"] for it in voice.load()}
m = upkeep.match(log=lambda *a: None)["drafts"]
from vdp.anonymise import anon_id
check("a draft sent within the hour is matched to its message", m["d0"]["sent"] == anon_id("slack:C0:m0"), m["d0"])
check("the match is the message closest in wording", m["d10"]["sent"] == anon_id("slack:C0:m45") and m["d0"]["sent"] != m["d10"]["sent"], m["d10"])
check("a removed greeting makes a draft edited", m["d0"]["edited"] and m["d5"]["edited"])
check("a draft sent as approved is not edited", m["d1"]["sent"] and not m["d1"]["edited"], m["d1"])
check("a draft sent days later isn't matched", m["d2"]["sent"] is None, m["d2"])
check("but its message is held as a near-copy", anon_id("slack:C2:m2") in m["d2"]["near"], m["d2"])
check("a message sent before a draft was written is never its near-copy", m["dlate"]["near"] == [], m["dlate"])
check("a Jira draft is never matched, and is edited by its approved text", m["dj"]["sent"] is None and m["dj"]["edited"])
check("normalising: Slack mentions, links and entities match a draft's @name and text",
      not upkeep.edited("Thanks @Robin, see the docs & logs", "Thanks <@U123>, see <https://x.example/d|the docs> &amp; logs"))
check("an edit to capitals or the end mark counts",
      upkeep.edited("ok, done.", "ok, done") and upkeep.edited("Ok done", "ok done"))
held = upkeep.held_ids()
items = {it["id"] for it in voice.load()}
check("held messages are left out of the voice items", held and not (held & items) and items == items_before - held,
      (len(held), len(items), len(items_before)))
d = state.read_json(upkeep.path("due.json"))
check("no session is due under 20 edited drafts and inside 4 weeks", d["due"] is False and d["edited"] == 4, d)
check("the SessionStart line prints nothing when no session is due",
      subprocess.run([os.environ["DUE_HOOK"]], capture_output=True, text=True).stdout == "")

# Due: at 3 edited drafts the line shows.
s = settings.load()
s["upkeep"]["due_items"] = 3
state.write_json(settings.file(), s)
d = upkeep.due(log=lambda *a: None)
check("a session is due once the edited drafts reach due_items", d["due"] and "4 edited drafts" in d["line"], d)
out = subprocess.run([os.environ["DUE_HOOK"]], capture_output=True, text=True).stdout
check("the SessionStart line shows it as one systemMessage",
      json.loads(out) == {"systemMessage": d["line"]}, out)

# Suggestions: one stand-in call; a line from fewer than recur_min drafts is dropped.
cf = os.path.join(ST, "..", "upkeep-calls")
os.environ["FAKE_CLAUDE_COUNT"] = cf
sg = upkeep.suggest(log=lambda *a: None)
calls = int(open(cf).read())
check("suggestions take one call", calls == 1, calls)
check("the removed greeting is counted in 3 drafts",
      any(c["edit"] == 'removed "hi all," at the start' and len(c["drafts"]) == 3 for c in sg["counts"]), sg["counts"])
check("only lines from at least 3 drafts are kept, under their one audience's section",
      [(x["line"], x["section"]) for x in sg["suggestions"]] == [("Don't open with a greeting.", "clients")],
      sg["suggestions"])
upkeep.suggest(log=lambda *a: None)
check("the same drafts are never sent twice", int(open(cf).read()) == 1)

# The review page and its answers.
page = voicereview.get("/voice/upkeep")
check("the upkeep page lists the suggestion, the held messages and the discarded draft",
      "open with a greeting" in page and "Accept as an exemplar" in page and "Wrong in voice" in page)
key = sg["suggestions"][0]["key"]
voicereview.post("/api/voice/upkeep-suggestion", {"key": key, "verdict": "accepted"})
check("an accepted line goes into the rules file under the audience's section",
      guide.own_rules_audience() == {"clients": ["Don't open with a greeting."]} and guide.own_rules()[0] == [],
      (guide.own_rules(), guide.own_rules_audience()))
voicereview.post("/api/voice/upkeep-suggestion", {"key": key, "verdict": "accepted"})
check("accepting it again doesn't add it twice", guide.own_rules_audience()["clients"] == ["Don't open with a greeting."])
w = settings.get("render")
g = {"own_rules": ["be brief"], "own_rules_audience": guide.own_rules_audience(), "general": [], "audiences": {}, "jira": []}
check("an audience's own lines follow the lines for all, in that audience's guide only",
      "- be brief\n- Don't open with a greeting." in guide.render_text(g, {}, "clients", ["ask"], [], False, 0.02, w, True)
      and "greeting" not in guide.render_text(g, {}, "senior", ["ask"], [], False, 0.02, w, True))
g0 = {"own_rules": ["be brief"], "general": [], "audiences": {}, "jira": []}
check("with no audience sections the guide text is as before",
      guide.render_text(g0, {}, "clients", ["ask"], [], False, 0.02, w, True)
      == guide.render_text({**g0, "own_rules_audience": {}}, {}, "clients", ["ask"], [], False, 0.02, w, True))

a = anon_id("slack:C0:m0")
try:
    voicereview.post("/api/voice/upkeep-message", {"id": a, "verdict": "accepted", "audience": "clients", "purposes": []})
    refused = False
except ValueError:
    refused = True
check("a message isn't accepted without a purpose", refused)
voicereview.post("/api/voice/upkeep-message", {"id": a, "verdict": "accepted", "audience": "senior",
                                               "purposes": ["status"]})
it = {x["id"]: x for x in voice.load()}.get(a)
check("an accepted message joins the voice items with the audience and purposes confirmed",
      it is not None and it["audience"] == "senior" and labels.final().get(a) == ["status"], it)
r = anon_id("slack:C2:m2")
voicereview.post("/api/voice/upkeep-message", {"id": r, "verdict": "rejected", "audience": "clients", "purposes": []})
check("a rejected message stays out", r not in {x["id"] for x in voice.load()})
voicereview.post("/api/voice/upkeep-discarded", {"id": "dx", "verdict": "voice"})
check("a discarded draft marked wrong in voice counts as edited", "dx" in upkeep.pending()["discarded_voice"])
check("its pair has nothing kept", ("dx", "senior", "Dear team, I regret to inform you", "") in upkeep.session_pairs())

voicereview.post("/api/voice/upkeep-end", {})
p = upkeep.pending()
check("ending the session marks its drafts reviewed and nothing is due",
      p["edited"] == [] and p["discarded_voice"] == [] and not state.read_json(upkeep.path("due.json"))["due"], p)

# Four weeks with nothing to review: no line, and the clock starts again.
for i in list(upkeep.held_messages()):
    rv = upkeep.review()
    rv["messages"].setdefault(i, {"verdict": "rejected", "audience": "clients", "purposes": []})
    upkeep.save_review(rv)
rv = upkeep.review()
old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
rv["clock"] = old
upkeep.save_review(rv)
d = upkeep.due(log=lambda *a: None)
check("after 4 weeks with nothing to review no session is due and the clock restarts",
      not d["due"] and d["items"] == 0 and upkeep.review()["clock"] != old, d)
# Four weeks with one item: due.
R2 = draft("dn", "slack:C4", "one more", "one more!", "2024-01-01T00:59:00Z", status="discarded", aud="one-to-one")
with open(src, "w") as f:
    for x in R2:
        f.write(json.dumps(x) + "\n")
upkeep.import_records(src, log=lambda *a: None)
rv = upkeep.review()
rv["clock"] = old
upkeep.save_review(rv)
upkeep.match(log=lambda *a: None)
d = state.read_json(upkeep.path("due.json"))
check("after 4 weeks with one item to review a session is due", d["due"] and "1 items" in d["line"], d)
# A struck conversation's drafts are dropped.
inp = state.read_json(state.path("inputs.json"))
inp["struck_conversations"] = ["C4"]
state.write_json(state.path("inputs.json"), inp)
upkeep.match(log=lambda *a: None)
check("a struck conversation's drafts are left out", "dn" not in upkeep.matches())
print(f"{len(RESULTS)} upkeep checks")
