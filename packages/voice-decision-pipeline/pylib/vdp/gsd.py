"""GSD written records -> corpus/gsd.jsonl (PLAN §1).

Every repo with a .planning/ directory counts (James, 11 Nov 2026). Two
kinds of record are read: each bullet under "### Decisions" in STATE.md,
and each "###" subsection inside a phase CONTEXT.md's <decisions> block
(archived milestones included). A "Claude's Discretion" subsection is
tagged so the decision extraction can weight it by origin (PLAN §4.9).
Repos whose .planning/ holds neither yet are read once they do.
"""

import glob
import hashlib
import os
import re
from collections import Counter
from datetime import datetime, timezone

from . import inputs, record, textutil

DEFAULT_ROOTS = ["/mnt/sda/Development"]
MAX_DEPTH = 5
SKIP_DIRS = {"node_modules", ".git", "build", "dist", ".dart_tool", "Pods", "vendor"}


def find_repos(roots):
    repos = []
    for root in roots:
        base = root.rstrip(os.sep).count(os.sep)
        for d, dirs, _ in os.walk(root):
            if ".planning" in dirs:
                repos.append(d)
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".")
                       and d.count(os.sep) - base < MAX_DEPTH]
    return sorted(set(repos))


def mtime(p):
    return datetime.fromtimestamp(os.path.getmtime(p), tz=timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def section(text, heading_rx, stop_rx):
    m = re.search(heading_rx, text, re.M)
    if not m:
        return None
    rest = text[m.end():]
    s = re.search(stop_rx, rest, re.M)
    return rest[: s.start()] if s else rest


def state_decisions(text):
    body = section(text, r"^###\s+Decisions\s*$", r"^#{1,3}\s")
    if not body:
        return []
    out, cur = [], None
    for line in body.splitlines():
        if re.match(r"^\s{0,1}[-*]\s+", line):
            if cur:
                out.append(cur)
            cur = re.sub(r"^\s{0,1}[-*]\s+", "", line)
        elif cur is not None and line.strip():
            cur += "\n" + line.strip()
    if cur:
        out.append(cur)
    return [x.strip() for x in out if x.strip() and not x.strip().lower().startswith("none")]


def context_decisions(text):
    m = re.search(r"<decisions>(.*?)</decisions>", text, re.S)
    if not m:
        return []
    body = m.group(1)
    parts = re.split(r"^###\s+(.+?)\s*$", body, flags=re.M)
    out = []
    for i in range(1, len(parts), 2):
        title, content = parts[i].strip(), parts[i + 1].strip()
        if content:
            out.append((title, content))
    return out


def extract(d, counts=None, roots=None):
    counts = counts if counts is not None else Counter()
    me = inputs.me(d)
    roots = roots or d.get("gsd_roots") or DEFAULT_ROOTS
    stats = Counter()
    recs = []
    struck = set(d["struck_conversations"])
    for repo in find_repos(roots):
        stats["repos"] += 1
        name = os.path.relpath(repo, os.path.commonpath([repo] + roots)) if roots else repo
        conv = f"gsd:{os.path.basename(repo)}:{hashlib.sha1(repo.encode()).hexdigest()[:8]}"
        if conv in struck:
            continue
        plan = os.path.join(repo, ".planning")
        st = os.path.join(plan, "STATE.md")
        if os.path.exists(st):
            with open(st, encoding="utf-8", errors="replace") as f:
                for n, text in enumerate(state_decisions(f.read()), 1):
                    rid = f"{conv}:STATE.md:{n}"
                    recs.append(record.make(
                        id=rid, source="gsd", conversation=conv, author=me, audience=None,
                        ts=mtime(st), text=textutil.redact(text, counts),
                        flags=["item", "no-voice"],
                        source_fields={"repo": repo, "repo_name": name, "file": "STATE.md",
                                       "kind": "state-decision", "n": n}))
                    stats["state-decisions"] += 1
        for ctx in sorted(glob.glob(os.path.join(plan, "**", "*CONTEXT.md"), recursive=True)):
            rel = os.path.relpath(ctx, plan)
            with open(ctx, encoding="utf-8", errors="replace") as f:
                for n, (title, text) in enumerate(context_decisions(f.read()), 1):
                    discretion = "discretion" in title.lower()
                    rid = f"{conv}:{rel}:{n}"
                    recs.append(record.make(
                        id=rid, source="gsd", conversation=conv, author=me, audience=None,
                        ts=mtime(ctx), text=textutil.redact(f"{title}\n{text}", counts),
                        flags=["item", "no-voice"] + (["claude-discretion"] if discretion else []),
                        source_fields={"repo": repo, "repo_name": name, "file": rel,
                                       "kind": "context-decision", "section": title, "n": n}))
                    stats["context-decisions"] += 1
    return recs, stats
