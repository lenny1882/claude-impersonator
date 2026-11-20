"""The owner's voice items, as the voice build sends them (PLAN §3).

A voice item is one of the owner's own Slack or Bitbucket messages: never a
transcript, GSD record, reaction, silent approval or their self-DM (the
corpus index's rule, index.voice_item). Everything here is read from the
anonymised copies, the only text that is sent; the real corpus is read
only to find which message each item answers, since the anonymised ids are
hashes and can't be walked.

Audiences use the build's slugs (the contract with voice-runtime):
clients, project-team, technical-team, senior, one-to-one, and jira, which
has no items (PLAN §3.1).
"""

import re

from . import batches, state
from .anonymise import anon_id
from .index import VOICE_SOURCES, voice_item

AUDIENCES = {
    "clients": "clients",
    "project team": "project-team",
    "technical team": "technical-team",
    "senior/management": "senior",
    "1:1 colleagues": "one-to-one",
}
CORPUS_AUDIENCES = tuple(AUDIENCES.values())
ALL_AUDIENCES = CORPUS_AUDIENCES + ("jira",)

# PLAN §3.3: eleven purposes and "other", in this order.
PURPOSES = {
    "push-back": ("push back / disagree: objects to or corrects a proposal, a claim or a plan, "
                  "including stating a limit or requirement that rules out what someone wants. "
                  "A review comment suggesting a code change is ask, not push-back"),
    "decline": ("decline: says no to a request, an invitation or an offer of help, "
                "or puts something off for now"),
    "ask": "ask / request: asks a question or asks someone to do something",
    "chase": "chase / nudge: follows up on something asked before and not yet done",
    "status": "status / update: reports where something stands",
    "explain": ("explain / instruct: explains how something works, how to do it, why, "
                "or what follows from it, including the instructions or reasons inside a request. "
                "A report of what happened is status; a personal story is small talk"),
    "approve": "approve / agree: says yes, agrees or signs something off",
    "own-mistake": ("own a mistake / apologise: takes the blame for something or apologises for it. "
                    "A joking 'sorry' is small talk"),
    "thank": "thank / praise: thanks someone or praises their work",
    "escalate": ("escalate: flags that something is wrong and must be dealt with, raises it to "
                 "someone with more authority, or warns of a risk to the work. Asking a colleague "
                 "to look at an error is ask; guessing at a cause is explain; venting is small talk"),
    "small-talk": ("small talk / humour: social chat, jokes, banter, personal stories and venting, "
                   "alongside other purposes or on their own"),
    "other": ("other: none of the above. A bare link takes the purpose it serves in the "
              "conversation (sharing a result is status), and is other only when the "
              "conversation doesn't show one"),
}
CONTEXT_CHARS = 6000
MAX_CONTEXT = 20


class NotSendable(SystemExit):
    pass


def require_sendable():
    """Nothing from a source is sent until its own first batch is approved
    (PLAN §2.3), nor while the leak check has a term not fixed or cleared
    by hand (PLAN §5, §8.5)."""
    held = [s for s in VOICE_SOURCES if not batches.sendable(s)]
    if held:
        raise NotSendable(
            "voice-decision-pipeline: nothing is sent from " + ", ".join(held) +
            " until its first review batch is approved")
    from . import leaks
    why = leaks.gate()
    if why:
        raise NotSendable("voice-decision-pipeline: nothing is sent: " + why)


def answered_id(r, by_id):
    """The real id of the message r answers (index.answered's rule)."""
    sf = r.get("source_fields") or {}
    if r["source"] == "bitbucket":
        parent = sf.get("parent")
        if parent:
            pid = r["id"].rsplit(":c:", 1)[0] + f":c:{parent}"
            if pid in by_id:
                return pid
        pr = r["id"].split(":c:", 1)[0]
        return pr if pr in by_id and pr != r["id"] else None
    ctx = [by_id[c] for c in r.get("context_ids") or [] if c in by_id]
    earlier = [c for c in ctx if c["ts"] < r["ts"] and c.get("author") != r.get("author")]
    return earlier[-1]["id"] if earlier else None


def code_share(text, tags):
    spans = [t for t in tags or [] if t.get("type") in ("code", "log") and "start" in t]
    n = sum(t["end"] - t["start"] for t in spans)
    return n / max(1, len(text or ""))


def without_code(text, tags):
    """text with every code and log span replaced by [code] (PLAN §3.5)."""
    spans = sorted((t for t in tags or [] if t.get("type") in ("code", "log") and "start" in t),
                   key=lambda t: t["start"])
    out, pos = [], 0
    for t in spans:
        if t["start"] < pos:
            continue
        out.append(text[pos:t["start"]])
        out.append("[code]")
        pos = t["end"]
    out.append(text[pos:])
    return re.sub(r"(?:\[code\]\s*){2,}", "[code] ", "".join(out)).strip()


def words(text):
    return len(re.findall(r"[A-Za-z0-9']+", text or ""))


FENCE = re.compile(r"```.*?```", re.S)
INLINE = re.compile(r"`[^`\n]+`")
SLACK_LINK = re.compile(r"<(\[url\]|https?://[^|>]+)(?:\|([^>]*))?>")
SLACK_SPECIAL = re.compile(r"<!(here|channel|everyone)(?:\|[^>]*)?>")
SLACK_MENTION = re.compile(r"<([@#])([^|>]+)(?:\|([^>]*))?>")
CODE_RUN = re.compile(r"\[code\](?:\s*\[code\])+")


def shown(text):
    """A message as both sides of a blind pair show it: code as [code], as
    the drafter was shown it, every link as [url], and Slack's mention markup
    as the words it displays, so neither side gives itself away by format."""
    t = FENCE.sub("[code]", text or "")
    t = INLINE.sub("[code]", t)
    # Every link shows as [url], labelled or not: the drafter writes a bare
    # [url], so a label would mark the real side.
    t = SLACK_LINK.sub("[url]", t)
    t = SLACK_SPECIAL.sub(lambda m: "@" + m.group(1), t)
    t = SLACK_MENTION.sub(lambda m: m.group(1) + (m.group(3) or m.group(2)), t)
    return CODE_RUN.sub("[code]", t)


def shown_words(text):
    """Words a reader sees once code and links are shown as [code] and [url]."""
    return words(re.sub(r"\[(?:url|code)\]", " ", shown(text)))


def load():
    """[item] for every voice item, each a dict: id (anonymised), real_id,
    source, audience (slug), text, tags, answered (anonymised text of the
    message it answers, or ""), before and after ([(author, text)] of its
    context, anonymised), ts."""
    real, anon = {}, {}
    for s in VOICE_SOURCES:
        for r in state.read_jsonl(state.corpus_file(s)):
            real[r["id"]] = r
        for r in state.read_jsonl(state.anon_file(s)):
            anon[r["id"]] = r
    out = []
    for rid, r in real.items():
        if not voice_item(r):
            continue
        a = anon.get(anon_id(rid))
        aud = AUDIENCES.get(r.get("audience") or "")
        if a is None or aud is None:
            continue
        ans = answered_id(r, real)
        ans_a = anon.get(anon_id(ans)) if ans else None
        ctx = sorted((anon[c] for c in a.get("context_ids") or [] if c in anon),
                     key=lambda c: c.get("ts") or "")
        before = [(c["author"], c.get("text") or "") for c in ctx if (c.get("ts") or "") < (a.get("ts") or "")]
        after = [(c["author"], c.get("text") or "") for c in ctx if (c.get("ts") or "") > (a.get("ts") or "")]
        if r["source"] == "bitbucket" and ans_a and not before:
            before = [(ans_a["author"], ans_a.get("text") or "")]
        out.append({"id": a["id"], "real_id": rid, "source": r["source"], "audience": aud,
                    "text": a.get("text") or "", "tags": a.get("tags") or [],
                    "answered": (ans_a or {}).get("text") or "",
                    "answered_tags": (ans_a or {}).get("tags") or [],
                    "before": before[-MAX_CONTEXT:], "after": after[:MAX_CONTEXT],
                    "ts": a.get("ts") or ""})
    out.sort(key=lambda x: (x["ts"], x["id"]))
    return out


def render_context(lines, limit=CONTEXT_CHARS, keep="end"):
    text = "\n".join(f"[{a}] {t}" for a, t in lines)
    if len(text) <= limit:
        return text
    return ("…" + text[-limit:]) if keep == "end" else (text[:limit] + "…")
