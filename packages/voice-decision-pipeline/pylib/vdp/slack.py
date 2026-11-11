"""Slack export -> corpus/slack.jsonl (PLAN §2.1).

Corpus items are James's own messages in the kept conversations, plus
messages by others that James gave an agreement reaction (tagged
reaction:<name>, never voice). Each item keeps its context: its thread if it
is in one, otherwise the conversation's messages in the 2 hours before and
after it, up to 20 each way (James, 9 Nov 2026). Context messages are stored
as records of their own and referenced by id, so each message is stored
once however many windows it falls in.

Bot messages are context only, tagged `bot`. Channel events (joins, room
created, topic and canvas changes) are dropped (James, 11 Nov 2026).
"""

import glob
import json
import os
from collections import Counter, defaultdict

from . import inputs, record, textutil

WINDOW_SECONDS = 2 * 3600
WINDOW_MAX = 20

EVENT_SUBTYPES = {
    "channel_join", "channel_leave", "group_join", "group_leave",
    "sh_room_created", "sh_room_shared", "channel_topic", "channel_purpose",
    "channel_name", "channel_canvas_updated", "tabbed_canvas_updated",
    "channel_archive", "channel_unarchive", "pinned_item", "unpinned_item",
    "reminder_add", "tombstone", "automatic_ai_huddle_notes_enabled",
    "huddle_thread", "bot_add", "bot_remove", "channel_convert_to_private",
}

# Thumbs-up, plus, tick and OK-hand kinds (James, 11 Nov 2026). A
# workspace's own custom emoji of those kinds are listed in the inputs, under
# agreement_reactions_extra, so they stay out of this public repo.
AGREEMENT = {
    "+1", "thumbsup", "heavy_plus_sign", "heavy_check_mark",
    "white_check_mark", "ballot_box_with_check", "ok_hand", "ok", "check",
}


def reaction_base(name):
    return name.split("::", 1)[0]


def load_messages(folder):
    msgs = []
    for f in sorted(glob.glob(os.path.join(folder, "*.json"))):
        with open(f, encoding="utf-8") as fh:
            msgs.extend(json.load(fh))
    msgs = [m for m in msgs if m.get("type") == "message" and m.get("ts")]
    msgs.sort(key=lambda m: float(m["ts"]))
    return msgs


def is_bot(m):
    return m.get("subtype") == "bot_message" or bool(m.get("bot_id"))


def is_reply(m):
    t = m.get("thread_ts")
    return bool(t) and t != m["ts"]


def thread_key(m):
    return m.get("thread_ts") or m["ts"]


def conversation_meta(export):
    """id -> metadata from channels/groups/dms/mpims.json."""
    meta = {}
    for name in ("channels.json", "groups.json", "dms.json", "mpims.json"):
        p = os.path.join(export, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                for c in json.load(fh):
                    meta[c["id"]] = c
    return meta


def extract(d, counts=None):
    counts = counts if counts is not None else Counter()
    export = d.get("slack_export")
    if not export or not os.path.isdir(export):
        raise SystemExit(f"voice-decision-pipeline: Slack export not found at {export!r}")
    me = inputs.me(d)
    meta = conversation_meta(export)
    struck = set(d["struck_conversations"])
    struck_authors = set(d["struck_authors"])
    agreement = AGREEMENT | set(d.get("agreement_reactions_extra") or [])
    out = {}
    stats = Counter()

    for conv in d.get("conversations", []):
        if conv.get("status") != "kept" or conv["id"] in struck:
            continue
        folder = os.path.join(export, conv.get("folder") or conv["id"])
        if not os.path.isdir(folder):
            stats["missing-folder"] += 1
            continue
        members = set((meta.get(conv["id"]) or {}).get("members") or [])
        self_dm = conv.get("kind") == "DM" and members and members <= {me}
        audience = None if self_dm else inputs.audience(conv.get("audience"))
        msgs = [m for m in load_messages(folder)
                if m.get("subtype") not in EVENT_SUBTYPES]
        by_ts = {m["ts"]: m for m in msgs}
        threads = defaultdict(list)
        for m in msgs:
            if m.get("thread_ts"):
                threads[m["thread_ts"]].append(m)
        top = [m for m in msgs if not is_reply(m)]
        top_index = {m["ts"]: i for i, m in enumerate(top)}

        def rid(m):
            return f"slack:{conv['id']}:{m['ts']}"

        def context_of(m):
            if m.get("thread_ts") and len(threads[m["thread_ts"]]) > 1:
                return [x for x in threads[m["thread_ts"]] if x["ts"] != m["ts"]]
            i = top_index.get(m["ts"])
            if i is None:
                return []
            t0 = float(m["ts"])
            before = [x for x in top[max(0, i - WINDOW_MAX):i]
                      if t0 - float(x["ts"]) <= WINDOW_SECONDS]
            after = [x for x in top[i + 1:i + 1 + WINDOW_MAX]
                     if float(x["ts"]) - t0 <= WINDOW_SECONDS]
            return before + after

        def agreed(m):
            if m.get("user") == me or is_bot(m):
                return None
            for r in m.get("reactions") or []:
                if me in (r.get("users") or []) and reaction_base(r["name"]) in agreement:
                    return reaction_base(r["name"])
            return None

        wanted = {}   # ts -> set of flags
        items = []
        for m in msgs:
            if m.get("user") in struck_authors:
                continue
            if m.get("user") == me and not is_bot(m):
                items.append((m, ["item"] + (["no-voice"] if self_dm else [])))
            else:
                r = agreed(m)
                if r:
                    items.append((m, ["item", f"reaction:{r}"]))
        for m, fl in items:
            ctx = [x for x in context_of(m) if x.get("user") not in struck_authors]
            wanted.setdefault(m["ts"], set()).update(fl)
            for x in ctx:
                wanted.setdefault(x["ts"], set())
            m["_ctx"] = [rid(x) for x in ctx]

        for ts, fl in wanted.items():
            m = by_ts[ts]
            text = textutil.redact(m.get("text") or "", counts)
            bot = is_bot(m)
            flg = sorted(fl) + (["bot"] if bot else [])
            files = [f.get("name") or f.get("title") for f in m.get("files") or []
                     if f.get("name") or f.get("title")]
            if files:
                flg.append("attachment")
            if "item" in fl and "no-voice" not in fl and audience is None:
                stats["items-without-audience"] += 1
            sf = {
                "slack_ts": m["ts"],
                "thread_ts": m.get("thread_ts"),
                "reply": is_reply(m),
                "subtype": m.get("subtype"),
                "conversation_name": conv.get("name"),
                "conversation_kind": conv.get("kind"),
            }
            if files:
                sf["files"] = files
            links = [a.get("from_url") or a.get("original_url") or a.get("title_link")
                     for a in m.get("attachments") or []]
            links = [x for x in links if x]
            if links:
                sf["attachment_links"] = links
            if bot:
                sf["bot_name"] = (m.get("bot_profile") or {}).get("name") or m.get("username")
            out[rid(m)] = record.make(
                id=rid(m), source="slack", conversation=conv["id"],
                author=m.get("user") or m.get("bot_id"), audience=audience,
                ts=record.iso(m["ts"]), text=text, flags=flg,
                context_ids=m.get("_ctx", []),
                reactions=[{"name": r["name"], "count": r.get("count", 0),
                            "users": r.get("users", [])}
                           for r in m.get("reactions") or []],
                source_fields=sf)
            stats["items" if "item" in fl else "context"] += 1
    recs = sorted(out.values(), key=lambda r: (r["conversation"], r["ts"]))
    return recs, stats
