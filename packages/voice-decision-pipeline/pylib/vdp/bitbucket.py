"""Bitbucket pull requests -> corpus/bitbucket.jsonl (PLAN §1, §2.1).

Only the repos picked with `pick-repos`; a repo whose updated_on is earlier
than CUTOFF is skipped (James, 11 Nov 2026). In each, the PRs James
authored, commented on or approved, approvals without a comment included
(James, 11 Nov 2026); a PR he was only added to as a reviewer is left out
(James, 12 Nov 2026). Which PRs those are is read from the PR list, and only
they are fetched. Each comment
keeps its PR title, description and thread; inline comments also keep the
code under them, which needs `read:repository` on the token (PLAN §9).

The token is the REST token in ~/.netrc under api.bitbucket.org, used as
HTTP basic auth and never printed. A 403 names the scope it lacked.
"""

import json
import netrc
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

from . import inputs, record, state, textutil

API = os.environ.get("VDP_BITBUCKET_API", "https://api.bitbucket.org/2.0")
CUTOFF = "2019-01-01"
CODE_CONTEXT = 5


class ApiError(SystemExit):
    pass


def _auth():
    host = urllib.parse.urlparse(API).hostname
    try:
        # The tests point VDP_NETRC at a made-up file; nothing else sets it.
        a = netrc.netrc(os.environ.get("VDP_NETRC") or None).authenticators(host)
    except (FileNotFoundError, netrc.NetrcParseError):
        a = None
    if not a:
        raise ApiError(f"voice-decision-pipeline: no ~/.netrc entry for {host}")
    import base64
    return "Basic " + base64.b64encode(f"{a[0]}:{a[2]}".encode()).decode()


def get(url, raw=False, _auth_header=[]):
    if not url.startswith("http"):
        url = API + url
    if not _auth_header:
        _auth_header.append(_auth())
    req = urllib.request.Request(url, headers={"Authorization": _auth_header[0],
                                               "Accept": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read().decode("utf-8", errors="replace")
                return body if raw else json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(min(60, 2 ** attempt * 5))
                continue
            detail = e.read().decode("utf-8", errors="replace")[:300]
            if e.code == 403:
                raise ApiError(
                    f"voice-decision-pipeline: Bitbucket refused {url.split('?')[0]} (403). "
                    "Reading repositories and PR diffs needs the read:repository scope on "
                    f"the token in ~/.netrc (PLAN §9). Response: {detail}")
            raise ApiError(f"voice-decision-pipeline: Bitbucket {e.code} on "
                           f"{url.split('?')[0]}: {detail}")
    raise ApiError(f"voice-decision-pipeline: Bitbucket kept failing on {url.split('?')[0]}")


def pages(url):
    while url:
        page = get(url)
        yield from page.get("values", [])
        url = page.get("next")


def user_ids(u):
    u = u or {}
    return {x for x in (u.get("uuid"), u.get("account_id"), u.get("nickname"),
                        u.get("display_name")) if x}


def is_me(u, me_ids):
    return bool(user_ids(u) & me_ids)


def acted(p, me_ids):
    """A participant entry that is James and shows he did something: approved,
    asked for changes, or commented (Bitbucket sets participated_on then).
    Being added as a reviewer alone leaves all three empty."""
    return is_me(p.get("user"), me_ids) and bool(
        p.get("approved") or p.get("state") or p.get("participated_on"))


def involved(pr, me_ids):
    """James authored the PR, or commented on or approved it. Decided from the
    PR list's fields, so PRs he wasn't in are never fetched one by one."""
    return is_me(pr.get("author"), me_ids) or any(
        acted(p, me_ids) for p in pr.get("participants") or [])


def code_under(diff, path, line_to, line_from):
    """The lines around an inline comment, from the PR's unified diff."""
    if not diff or not path:
        return None
    files = re.split(r"^diff --git ", diff, flags=re.M)
    for f in files:
        if not re.search(rf"^\+\+\+ b/{re.escape(path)}$|^--- a/{re.escape(path)}$", f, re.M):
            continue
        lines, old, new = [], 0, 0
        for ln in f.splitlines():
            m = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", ln)
            if m:
                old, new = int(m.group(1)), int(m.group(2))
                continue
            if not old and not new:
                continue
            if ln.startswith("+") and not ln.startswith("+++"):
                lines.append((None, new, ln)); new += 1
            elif ln.startswith("-") and not ln.startswith("---"):
                lines.append((old, None, ln)); old += 1
            elif ln.startswith(" "):
                lines.append((old, new, ln)); old += 1; new += 1
        for i, (o, n, _) in enumerate(lines):
            if (line_to and n == line_to) or (not line_to and line_from and o == line_from):
                a, b = max(0, i - CODE_CONTEXT), i + CODE_CONTEXT + 1
                return "\n".join(x[2] for x in lines[a:b])
    return None


def people_file():
    return state.path("bitbucket-people.json")


def extract(d, counts=None):
    counts = counts if counts is not None else Counter()
    me = inputs.me(d)
    me_ids = set(d.get("bitbucket_me") or [])
    if not me_ids:
        raise SystemExit("voice-decision-pipeline: say which Bitbucket account is James's: "
                         "voice-decision-pipeline pick-repos --me <account_id|uuid|nickname>")
    repos = d.get("bitbucket_repos") or []
    if not repos:
        raise SystemExit("voice-decision-pipeline: no Bitbucket repos picked; run "
                         "voice-decision-pipeline pick-repos <workspace/repo>...")
    struck = set(d["struck_conversations"])
    struck_authors = set(d["struck_authors"])
    stats = Counter()
    people = state.read_json(people_file(), {}) or {}
    recs = {}

    def author_of(u):
        if is_me(u, me_ids):
            return me
        key = (u or {}).get("uuid") or (u or {}).get("account_id") or "unknown"
        people[key] = {"display_name": (u or {}).get("display_name"),
                       "nickname": (u or {}).get("nickname"),
                       "account_id": (u or {}).get("account_id")}
        return f"bitbucket:{key}"

    for slug in repos:
        if slug in struck:
            continue
        meta = get(f"/repositories/{slug}?fields=full_name,updated_on")
        if (meta.get("updated_on") or "")[:10] < CUTOFF:
            stats["repos-before-2019"] += 1
            print(f"  skip  {slug}: last updated {meta.get('updated_on')}, before 2019")
            continue
        stats["repos"] += 1
        q = "&".join(f"state={s}" for s in ("OPEN", "MERGED", "DECLINED", "SUPERSEDED"))
        fields = ("next,values.id,values.author,values.participants.user,"
                  "values.participants.approved,values.participants.participated_on,"
                  "values.participants.state")
        for pr_stub in pages(f"/repositories/{slug}/pullrequests?{q}&pagelen=50&fields={fields}"):
            stats["prs-seen"] += 1
            if not involved(pr_stub, me_ids):
                if any(is_me(p.get("user"), me_ids) for p in pr_stub.get("participants") or []):
                    stats["prs-added-only"] += 1
                continue
            pr = get(f"/repositories/{slug}/pullrequests/{pr_stub['id']}")
            parts = pr.get("participants") or []
            authored = is_me(pr.get("author"), me_ids)
            stats["prs"] += 1
            conv = f"{slug}#{pr['id']}"
            pr_id = f"bitbucket:{slug}:pr:{pr['id']}"
            pr_author = author_of(pr.get("author"))
            if pr_author in struck_authors:
                continue
            desc = f"{pr.get('title') or ''}\n\n{pr.get('description') or ''}".strip()
            comments = [c for c in pages(
                f"/repositories/{slug}/pullrequests/{pr['id']}/comments?pagelen=100")
                if not c.get("deleted")]
            diff = None
            if any(c.get("inline") for c in comments):
                try:
                    diff = get(f"/repositories/{slug}/pullrequests/{pr['id']}/diff", raw=True)
                except ApiError as e:
                    stats["diffs-refused"] += 1
                    print(f"  warn  {e}")
            by_id = {c["id"]: c for c in comments}

            def root_of(c):
                while c.get("parent") and c["parent"].get("id") in by_id:
                    c = by_id[c["parent"]["id"]]
                return c["id"]
            threads = defaultdict(list)
            for c in comments:
                threads[root_of(c)].append(c)

            sf_pr = {"repo": slug, "pr": pr["id"], "title": pr.get("title"),
                     "state": pr.get("state"), "author_name": (pr.get("author") or {}).get("display_name"),
                     "source_branch": ((pr.get("source") or {}).get("branch") or {}).get("name"),
                     "destination_branch": ((pr.get("destination") or {}).get("branch") or {}).get("name")}
            recs[pr_id] = record.make(
                id=pr_id, source="bitbucket", conversation=conv, author=pr_author,
                audience="technical team", ts=pr.get("created_on"),
                text=textutil.redact(desc, counts),
                flags=(["item"] if authored else []),
                context_ids=[], source_fields=dict(sf_pr, kind="pr"))
            for c in comments:
                a = author_of(c.get("user"))
                if a in struck_authors:
                    continue
                cid = f"bitbucket:{slug}:pr:{pr['id']}:c:{c['id']}"
                mine = a == me
                sf = dict(sf_pr, kind="comment", comment=c["id"],
                          parent=(c.get("parent") or {}).get("id"),
                          author_name=(c.get("user") or {}).get("display_name"))
                inl = c.get("inline")
                if inl:
                    sf["inline"] = {"path": inl.get("path"), "from": inl.get("from"),
                                    "to": inl.get("to")}
                    code = code_under(diff, inl.get("path"), inl.get("to"), inl.get("from"))
                    if code:
                        sf["inline"]["code"] = textutil.redact(code, counts)
                ctx = [pr_id] + [f"bitbucket:{slug}:pr:{pr['id']}:c:{x['id']}"
                                 for x in threads[root_of(c)] if x["id"] != c["id"]]
                recs[cid] = record.make(
                    id=cid, source="bitbucket", conversation=conv, author=a,
                    audience="technical team", ts=c.get("created_on"),
                    text=textutil.redact((c.get("content") or {}).get("raw") or "", counts),
                    flags=(["item"] if mine else []),
                    context_ids=ctx if mine else [], source_fields=sf)
                stats["comments-by-james" if mine else "comments-context"] += 1
            for p in parts:
                if p.get("approved") and is_me(p.get("user"), me_ids) and not authored:
                    aid = f"bitbucket:{slug}:pr:{pr['id']}:approval"
                    recs[aid] = record.make(
                        id=aid, source="bitbucket", conversation=conv, author=me,
                        audience="technical team",
                        ts=p.get("participated_on") or pr.get("updated_on"),
                        text="", flags=["item", "approval", "no-voice"],
                        context_ids=[pr_id] + [f"bitbucket:{slug}:pr:{pr['id']}:c:{c['id']}"
                                               for c in comments],
                        source_fields=dict(sf_pr, kind="approval"))
                    stats["approvals"] += 1
    state.write_json(people_file(), people)
    out = sorted(recs.values(), key=lambda r: (r["conversation"], r["ts"] or ""))
    return out, stats
