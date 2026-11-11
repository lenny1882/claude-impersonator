"""forget <person|conversation> (PLAN §2.2).

Removes the person's or conversation's records from the corpus, the
anonymised copies and the corpus index, and adds them to the struck lists in
the inputs, so later extractions skip them. The person's anonymising-map
entry is kept, so mentions of them in other people's messages are still
replaced and their pseudonym number never passes to someone else (James,
11 Nov 2026). Records that only mention them stay; their names in those are
replaced as before.
"""

import os

from . import SOURCES, inputs, state
from .anonmap import Map
from .anonymise import anon_id


def resolve(d, who):
    """(kind, ids) for a Slack user or conversation id, a Bitbucket id, a
    GSD conversation, or a name in the map or the conversation list."""
    convs = {c["id"]: c for c in d.get("conversations", [])}
    if who in convs or who.startswith(("gsd:", "transcripts:")) or "#" in who or "/" in who:
        return "conversation", {who}
    amap = Map.load()
    e = amap.get(who)
    if e and e["kind"] == "person":
        return "person", {e["real_id"], *e.get("ids", [])}
    low = who.lower()
    named = [c["id"] for c in convs.values() if (c.get("name") or "").lower() == low]
    if named:
        return "conversation", set(named)
    people = [x for x in amap.entries if x["kind"] == "person"
              and (low in (a.lower() for a in x["aliases"]) or low == x["pseudonym"])]
    if len(people) == 1:
        return "person", {people[0]["real_id"], *people[0].get("ids", [])}
    if len(people) > 1:
        raise SystemExit("voice-decision-pipeline: more than one person matches "
                         f"{who!r}: " + ", ".join(p["real_id"] for p in people))
    raise SystemExit(f"voice-decision-pipeline: nothing matches {who!r}")


def run(who, log=print):
    d = inputs.load()
    if who == d.get("james_user_id"):
        raise SystemExit("voice-decision-pipeline: that is James; forgetting him empties the corpus")
    kind, ids = resolve(d, who)
    key = "author" if kind == "person" else "conversation"
    dropped = set()
    for s in SOURCES:
        recs = list(state.read_jsonl(state.corpus_file(s)))
        keep = [r for r in recs if r.get(key) not in ids]
        gone = {r["id"] for r in recs} - {r["id"] for r in keep}
        if gone:
            state.write_jsonl(state.corpus_file(s), [
                dict(r, context_ids=[c for c in r["context_ids"] if c not in gone])
                for r in keep])
            dropped |= gone
    gone_anon = {anon_id(i) for i in dropped}
    for s in SOURCES:
        if os.path.exists(state.anon_file(s)):
            recs = list(state.read_jsonl(state.anon_file(s)))
            keep = [dict(r, context_ids=[c for c in r["context_ids"] if c not in gone_anon])
                    for r in recs if r["id"] not in gone_anon]
            if len(keep) != len(recs):
                state.write_jsonl(state.anon_file(s), keep)
    from .index import drop_rows
    rows = drop_rows(dropped)
    lst = d["struck_authors"] if kind == "person" else d["struck_conversations"]
    for i in sorted(ids):
        if i not in lst:
            lst.append(i)
    inputs.save(d)
    log(f"  ok    forgot {kind} ({len(ids)} id(s)): {len(dropped)} records, {rows} index rows; "
        "added to the struck list")
    return len(dropped)
