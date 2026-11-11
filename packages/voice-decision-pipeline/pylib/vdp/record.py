"""The corpus record (PLAN §2.2): one per message, one file per source,
context held as ids.

Fields: id, source, conversation, author (real id), audience, ts (ISO 8601,
UTC), text, tags, context_ids, reactions, source_fields, schema_version.

`tags` holds span tags ({"type", "start", "end"}, from textutil.tag) and
whole-record tags with no span:
  item          a corpus item: James's own message, or a message he agreed
                with by reaction. Everything else is context only.
  bot           a bot message, kept as context only (PLAN §2.1)
  reaction:<n>  a message James reacted to with an agreement reaction
  attachment    file names, in source_fields.files
  approval      a Bitbucket approval with no text
  ask-user      an AskUserQuestion answer in a transcript
  command       a slash command typed in a transcript
  no-voice      kept for decisions, never voice (James's self-DM, PLAN §3.2)
"""

from datetime import datetime, timezone

from . import SCHEMA_VERSION
from .textutil import tag


def iso(epoch):
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def make(*, id, source, conversation, author, audience, ts, text, flags=(),
         context_ids=(), reactions=(), source_fields=None):
    tags = [{"type": f} for f in flags] + tag(text)
    return {
        "id": id,
        "source": source,
        "conversation": conversation,
        "author": author,
        "audience": audience,
        "ts": ts,
        "text": text or "",
        "tags": tags,
        "context_ids": list(context_ids),
        "reactions": list(reactions),
        "source_fields": source_fields or {},
        "schema_version": SCHEMA_VERSION,
    }


def flags(r):
    return {t["type"] for t in r["tags"] if "start" not in t}


def is_item(r):
    return "item" in flags(r)
