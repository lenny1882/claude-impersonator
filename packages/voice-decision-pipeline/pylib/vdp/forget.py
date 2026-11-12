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


def source_people(d):
    """Every person the sources name, before or after anonymise has built the
    map: (ids, names) per Slack user from users.json, and per Bitbucket
    account from bitbucket-people.json. A Bitbucket account whose display name
    or nickname is a Slack user's name joins that user, as anonymise matches
    them."""
    from .anonymise import slack_users
    from .bitbucket import people_file
    people = []
    by_name = {}
    for u in slack_users(d):
        if u.get("is_bot"):
            continue
        p = u.get("profile") or {}
        names = {x.strip().lower() for x in (u.get("real_name"), p.get("real_name"),
                 p.get("display_name"), u.get("name"),
                 f"{p.get('first_name') or ''} {p.get('last_name') or ''}") if x and x.strip()}
        entry = ({u["id"]}, names)
        people.append(entry)
        for n in names:
            by_name.setdefault(n, entry)
    for key, p in (state.read_json(people_file(), {}) or {}).items():
        bid = f"bitbucket:{key}"
        names = {x.strip().lower() for x in (p.get("display_name"), p.get("nickname"))
                 if x and x.strip()}
        same = next((by_name[n] for n in names if n in by_name), None)
        if same:
            same[0].add(bid)
            same[0].update(x for x in (key, p.get("account_id")) if x)
        else:
            people.append(({bid}, names | {key.lower()}))
    return people


def resolve(d, who):
    """(kind, ids, prefixes) for a Slack user or conversation id, a Bitbucket
    repo, PR or account, a GSD or transcript conversation, or a name in the
    sources, the map or the conversation list. A repo is matched as the
    prefix of its PRs' conversations (<repo>#<id>)."""
    convs = {c["id"]: c for c in d.get("conversations", [])}
    if who in set(d.get("bitbucket_repos") or []) or ("/" in who and "#" not in who
                                                      and not who.startswith(("gsd:", "transcripts:"))):
        return "conversation", {who}, {who + "#"}
    if who in convs or who.startswith(("gsd:", "transcripts:")) or "#" in who:
        return "conversation", {who}, set()
    low = who.lower()
    named = [c["id"] for c in convs.values() if (c.get("name") or "").lower() == low]
    if named:
        return "conversation", set(named), set()
    amap = Map.load()
    e = amap.get(who)
    if e and e["kind"] == "person":
        return "person", {e["real_id"], *e.get("ids", [])}, set()
    found = [ids for ids, names in source_people(d)
             if who in ids or f"bitbucket:{who}" in ids or low in names]
    found += [{x["real_id"], *x.get("ids", [])} for x in amap.entries
              if x["kind"] == "person"
              and (low in (a.lower() for a in x["aliases"]) or low == x["pseudonym"])]
    merged = []
    for ids in found:
        for m in merged:
            if m & ids:
                m |= ids
                break
        else:
            merged.append(set(ids))
    if len(merged) == 1:
        return "person", merged[0], set()
    if len(merged) > 1:
        raise SystemExit("voice-decision-pipeline: more than one person matches "
                         f"{who!r}: " + "; ".join(", ".join(sorted(m)) for m in merged))
    raise SystemExit(f"voice-decision-pipeline: nothing matches {who!r}")


def run(who, log=print):
    d = inputs.load()
    me = d.get("james_user_id")
    if who == me:
        raise SystemExit("voice-decision-pipeline: that is James; forgetting him empties the corpus")
    kind, ids, prefixes = resolve(d, who)
    if kind == "person" and (me in ids or ids & set(d.get("bitbucket_me") or [])):
        raise SystemExit("voice-decision-pipeline: that is James; forgetting him empties the corpus")
    key = "author" if kind == "person" else "conversation"

    def gone_rec(r):
        v = r.get(key)
        return v in ids or any(str(v or "").startswith(p) for p in prefixes)
    dropped = set()
    for s in SOURCES:
        recs = list(state.read_jsonl(state.corpus_file(s)))
        keep = [r for r in recs if not gone_rec(r)]
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
