"""Claude Code transcripts -> corpus/transcripts.jsonl (PLAN §2.1).

Technical decisions only, never voice. Each record is one prompt James
typed, with the text of Claude's reply before it (usually what he was
correcting), a one-line summary of each tool call in between, the project
and the date. AskUserQuestion answers are records of their own, since each
is a decision stated outright.

Main sessions only: sidechain (subagent) transcripts are left out, because
their text is Claude's and James's own words are all in the main sessions
(James, 11 Nov 2026). Prompts that James didn't type are dropped: task
notifications, messages from other sessions, hook and skill injections,
SDK runs started by scripts.

Transcripts from James's other machines arrive as copies of their
~/.claude/projects directories; `import-transcripts <dir>` records each and
every extraction reads them alongside this machine's (James, 11 Nov 2026).
"""

import glob
import json
import os
import re
from collections import Counter

from . import inputs, record, textutil

NOT_TYPED = ("<task-notification>", "<agent-message", "<local-command",
             "<bash-stdout>", "<bash-stderr>", "Caveat:", "[Request interrupted",
             "<tool-use-id>", "<task-id>", "<summary>", "<to ",
             "This session is being continued from a previous conversation")
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
COMMAND = re.compile(r"<command-name>(.*?)</command-name>", re.S)
COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)
BASH_INPUT = re.compile(r"<bash-input>(.*?)</bash-input>", re.S)
REPLY_CAP = 8000
SUMMARY_CAP = 160


def default_roots():
    return [os.path.join(os.environ.get("CLAUDE_DIR") or os.path.expanduser("~/.claude"),
                         "projects")]


def session_files(root):
    """Main-session transcripts under a projects directory. Subagent
    transcripts live in <session>/subagents/ and are never read."""
    return sorted(f for f in glob.glob(os.path.join(root, "*", "*.jsonl"))
                  if os.sep + "subagents" + os.sep not in f)


def prompt_text(rec):
    """(text, flags) for a prompt James typed, or None."""
    if rec.get("type") != "user" or rec.get("isMeta") or rec.get("isSidechain"):
        return None
    origin = rec.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
        return None
    if str(rec.get("entrypoint") or "").startswith("sdk"):
        return None
    c = (rec.get("message") or {}).get("content")
    if isinstance(c, list):
        if any(b.get("type") == "tool_result" for b in c if isinstance(b, dict)):
            return None
        c = "\n".join(b.get("text", "") for b in c
                      if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(c, str):
        return None
    c = REMINDER.sub("", c).strip()
    if not c or c.startswith(NOT_TYPED):
        return None
    m = COMMAND.search(c)
    if m and c.lstrip().startswith(("<command-name>", "<command-message>")):
        name = m.group(1).strip()
        am = COMMAND_ARGS.search(c)
        args = (am.group(1) if am else "").strip()
        return (f"{name} {args}".strip(), ["command"])
    m = BASH_INPUT.search(c)
    if m:
        return ("! " + m.group(1).strip(), ["command"])
    return (c, [])


def tool_summary(block):
    name = block.get("name", "?")
    i = block.get("input") or {}
    detail = (i.get("file_path") or i.get("command") or i.get("pattern")
              or i.get("url") or i.get("skill") or i.get("description")
              or i.get("query") or i.get("prompt") or "")
    detail = " ".join(str(detail).split())
    if len(detail) > SUMMARY_CAP:
        detail = detail[:SUMMARY_CAP] + "…"
    return f"{name}: {detail}" if detail else name


def extract_file(path, machine, me, counts, out):
    project = None
    reply = []
    tools = []
    pending_ask = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("isSidechain"):
                continue
            project = os.path.basename(rec.get("cwd") or "") or project
            t = rec.get("type")
            if t == "assistant":
                for b in (rec.get("message") or {}).get("content") or []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text" and b.get("text", "").strip():
                        reply.append(b["text"].strip())
                    elif b.get("type") == "tool_use":
                        tools.append(tool_summary(b))
                        if b.get("name") == "AskUserQuestion":
                            pending_ask[b.get("id")] = b.get("input") or {}
                continue
            if t != "user":
                continue
            tur = rec.get("toolUseResult")
            if isinstance(tur, dict) and "answers" in tur:
                answers = tur.get("answers") or {}
                if not answers:
                    continue
                qs = tur.get("questions") or []
                text = "\n\n".join(f"Q: {q}\nA: {a}" for q, a in answers.items())
                rid = f"transcripts:{rec.get('sessionId')}:{rec.get('uuid')}"
                out[rid] = record.make(
                    id=rid, source="transcripts", conversation=rec.get("sessionId"),
                    author=me, audience=None, ts=rec.get("timestamp"),
                    text=textutil.redact(text, counts), flags=["item", "ask-user", "no-voice"],
                    source_fields={
                        "machine": machine, "project": project, "cwd": rec.get("cwd"),
                        "questions": [{"question": q.get("question"), "header": q.get("header"),
                                       "options": [o.get("label") for o in q.get("options") or []]}
                                      for q in qs],
                        "answers": answers,
                        "annotations": tur.get("annotations") or {},
                        "preceding_reply": textutil.redact(
                            "\n\n".join(reply)[-REPLY_CAP:], counts),
                    })
                continue
            p = prompt_text(rec)
            if p is None:
                continue
            text, fl = p
            rid = f"transcripts:{rec.get('sessionId')}:{rec.get('uuid')}"
            out[rid] = record.make(
                id=rid, source="transcripts", conversation=rec.get("sessionId"),
                author=me, audience=None, ts=rec.get("timestamp"),
                text=textutil.redact(text, counts), flags=["item", "no-voice"] + fl,
                source_fields={
                    "machine": machine, "project": project, "cwd": rec.get("cwd"),
                    "git_branch": rec.get("gitBranch"),
                    "preceding_reply": textutil.redact("\n\n".join(reply)[-REPLY_CAP:], counts),
                    "tool_calls": [textutil.redact(x, counts) for x in tools],
                })
            reply, tools = [], []


def extract(d, counts=None, roots=None):
    counts = counts if counts is not None else Counter()
    me = inputs.me(d)
    out = {}
    stats = Counter()
    sources = [(r, "local") for r in (roots or default_roots())]
    sources += [(i["dir"], i.get("machine") or os.path.basename(i["dir"].rstrip("/")))
                for i in d.get("transcript_imports", [])]
    for root, machine in sources:
        if not os.path.isdir(root):
            stats[f"missing-dir:{root}"] += 1
            continue
        for f in session_files(root):
            extract_file(f, machine, me, counts, out)
            stats["files"] += 1
    struck = set(d["struck_conversations"])
    recs = [r for r in out.values() if r["conversation"] not in struck]
    recs.sort(key=lambda r: (r["ts"] or "", r["id"]))
    stats["items"] = len(recs)
    return recs, stats
