"""`show bitbucket [--repo <workspace/repo>]`: James's Bitbucket items as text.

The corpus is one JSON record per line; this writes the items James can
check by eye, grouped by repo and PR: each PR's title, author, state and
branches, then his description, comments (with the comment each answers,
and the file, line and code under an inline one) and approvals, by date.
Real names, so it goes to the state (owner-only), never to the log.
"""

from collections import defaultdict

from . import state
from .record import flags


def view_file(name):
    return state.path("views", f"{name}.txt")


def bitbucket(repo=None):
    recs = list(state.read_jsonl(state.corpus_file("bitbucket")))
    if not recs:
        raise SystemExit("voice-decision-pipeline: no Bitbucket records; run 'extract bitbucket' first")
    by_id = {r["id"]: r for r in recs}
    prs = defaultdict(list)
    for r in recs:
        if repo is None or r["conversation"].startswith(repo + "#"):
            prs[r["conversation"]].append(r)
    if not prs:
        raise SystemExit(f"voice-decision-pipeline: no Bitbucket records for {repo}")

    def key(conv):
        slug, _, num = conv.rpartition("#")
        return slug, int(num) if num.isdigit() else 0
    lines, items, shown = [], 0, 0
    for conv in sorted(prs, key=key):
        rs = prs[conv]
        mine = sorted((r for r in rs if "item" in flags(r)), key=lambda r: r.get("ts") or "")
        if not mine:
            continue
        shown += 1
        pr = next((r for r in rs if r["source_fields"].get("kind") == "pr"), None)
        sf = (pr or mine[0])["source_fields"]
        lines += ["", "=" * 78,
                  f"{conv}  [{sf.get('state')}]  {sf.get('title')}",
                  f"  by {sf.get('author_name')}  {((pr or {}).get('ts') or '')[:10]}  "
                  f"{sf.get('source_branch')} -> {sf.get('destination_branch')}"]
        for r in mine:
            items += 1
            s = r["source_fields"]
            kind = s.get("kind")
            day = (r.get("ts") or "")[:10]
            if kind == "pr":
                lines += ["", "  [your PR description]"]
                lines += [f"    {x}" for x in (r.get("text") or "(empty)").splitlines()]
            elif kind == "approval":
                lines += ["", f"  [you approved, {day}]"]
            else:
                head = f"  [your comment, {day}]"
                inl = s.get("inline") or {}
                if inl:
                    head += f"  on {inl.get('path')} line {inl.get('to') or inl.get('from')}"
                lines += ["", head]
                par = by_id.get(f"bitbucket:{s.get('repo')}:pr:{s.get('pr')}:c:{s.get('parent')}") \
                    if s.get("parent") else None
                if par:
                    pinl = par["source_fields"].get("inline") or {}
                    where = (f" on {pinl.get('path')} line {pinl.get('to') or pinl.get('from')}"
                             if pinl else "")
                    lines.append(f"    replying to {par['source_fields'].get('author_name')}{where}: "
                                 f"{(par.get('text') or '')[:200]!r}")
                    if not inl:
                        inl = pinl
                lines += [f"    | {x}" for x in (inl.get("code") or "").splitlines()]
                lines += [f"    {x}" for x in (r.get("text") or "").splitlines()]
    out = view_file("bitbucket" if repo is None else "bitbucket-" + repo.replace("/", "__"))
    state.write_text(out, "\n".join(lines).lstrip("\n") + "\n")
    print(f"  ok    {items} of your items in {shown} PRs written to {out}")
    return out
