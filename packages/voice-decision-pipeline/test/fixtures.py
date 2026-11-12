"""Made-up inputs for the tests: a Slack export, a build-inputs.json, a
Claude Code projects directory, a GSD repo and a fake Bitbucket API's data.
No real person, client or message appears anywhere in here.

    python3 fixtures.py <dir>     writes everything under <dir>
"""

import json
import os
import sys

ME = "UJAMESAAA"
DAY = 24 * 3600
TEAM = "T0HOME"


def w(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(obj, str):
            f.write(obj)
        else:
            json.dump(obj, f, indent=1)


def user(uid, real, first, last, team=TEAM, bot=False, handle=None):
    return {"id": uid, "team_id": team, "name": handle or f"{first}.{last}".lower(),
            "real_name": real, "is_bot": bot, "deleted": False,
            "profile": {"real_name": real, "display_name": real, "first_name": first,
                        "last_name": last, "email": f"{first.lower()}@example.org"}}


def msg(ts, user, text, **kw):
    m = {"type": "message", "ts": f"{ts:.6f}", "user": user, "text": text}
    m.update(kw)
    return m


def slack(root):
    exp = os.path.join(root, "export")
    w(f"{exp}/users.json", [
        user(ME, "Jamie Testperson", "Jamie", "Testperson"),
        user("UCOLPRIYA", "Priya Raman", "Priya", "Raman"),
        user("UCOLTOMBB", "Tom Baker", "Tom", "Baker", handle="tom"),
        user("UCLIGREGR", "Gregor Whitfield", "Gregor", "Whitfield", team="T0CLIENT"),
        user("UBOTDEPLY", "Deploy Bot", "Deploy", "Bot", bot=True),
    ])
    w(f"{exp}/channels.json", [
        {"id": "CPROJACME", "name": "proj-acmecorp", "members": [ME, "UCOLPRIYA", "UCOLTOMBB"]},
        {"id": "CSTRUCKXX", "name": "random-chat", "members": [ME, "UCOLPRIYA"]},
    ])
    w(f"{exp}/groups.json", [
        {"id": "GCLIENTAC", "name": "ext-acmecorp-shared", "members": [ME, "UCLIGREGR", "UCOLPRIYA"]},
    ])
    w(f"{exp}/dms.json", [
        {"id": "DSELFNOTE", "members": [ME]},
        {"id": "DPRIYADMX", "members": [ME, "UCOLPRIYA"]},
    ])
    w(f"{exp}/mpims.json", [
        {"id": "GMPIMTRIO", "name": "mpdm-jamie.testperson--priya.raman--tom-1", "members": [ME, "UCOLPRIYA", "UCOLTOMBB"]},
    ])
    t = 17.0 * 10 ** 8
    w(f"{exp}/CPROJACME/2023-11-14.json", [
        msg(t, "UCOLPRIYA", "Morning, the build for Acme Corp is red again",
            reactions=[{"name": "bigthumb", "users": [ME], "count": 1}]),
        {"type": "message", "subtype": "channel_join", "ts": f"{t+5:.6f}", "user": "UCOLTOMBB",
         "text": "<@UCOLTOMBB> has joined the channel"},
        msg(t + 60, ME, "Looking. <@UCOLPRIYA> can you send me the log? Priya, also ping Gregor Whitfield"),
        {"type": "message", "subtype": "bot_message", "ts": f"{t+90:.6f}", "bot_id": "BBOTDEPLY",
         "text": "Build 412 failed on main", "bot_profile": {"name": "Deploy Bot"}},
        msg(t + 120, "UCOLTOMBB", "```\nTraceback (most recent call last):\n  File \"x.py\", line 1\n```"),
        msg(t + 180, ME, "Fixed it. The deploy key was password=hunter2secret and AKIAABCDEFGHIJKLMNOP leaked, rotating",
            thread_ts=f"{t+180:.6f}", reply_count=1),
        msg(t + 240, "UCOLPRIYA", "Thanks, all green now", thread_ts=f"{t+180:.6f}"),
        msg(t + 3 * 3600, "UCOLTOMBB", "Shall we move standup to 10?",
            reactions=[{"name": "+1::skin-tone-3", "users": [ME], "count": 1},
                       {"name": "eyes", "users": ["UCOLPRIYA"], "count": 1}]),
        msg(t + 3 * 3600 + 30, "UCOLPRIYA", "lunch?",
            reactions=[{"name": "joy", "users": [ME], "count": 1}]),
        msg(t + 10 * 3600, "UCOLPRIYA", "Far later message, outside every window"),
    ])
    w(f"{exp}/GCLIENTAC/2023-11-15.json", [
        msg(t + DAY, "UCLIGREGR", "The Zephyrline launch needs the Zephyrline banner on acmecorp.com"),
        msg(t + DAY + 60, ME, "We'll have Zephyrline ready Friday. Mail " + "gregor" + "@" + "acmecorp.com"
            + " or call +44 7700 900123 "
            "and see https://staging.acmecorp.com/zephyrline"),
        msg(t + DAY + 120, "UCLIGREGR", "Great, Zephyrline it is"),
    ])
    w(f"{exp}/DSELFNOTE/2023-11-16.json", [msg(t + 2 * DAY, ME, "note to self: check Zephyrline caching")])
    w(f"{exp}/DPRIYADMX/2023-11-16.json", [
        msg(t + 2 * DAY, "UCOLPRIYA", "Can I take Friday off?"),
        msg(t + 2 * DAY + 30, ME, "Yes, of course")])
    w(f"{exp}/GMPIMTRIO/2023-11-17.json", [
        msg(t + 3 * DAY, "UCOLTOMBB", "Who is on call this weekend?"),
        msg(t + 3 * DAY + 30, ME, "I am, swap with me next week")])
    w(f"{exp}/CSTRUCKXX/2023-11-16.json", [msg(t + 2 * DAY, ME, "struck conversation message")])
    inputs = {
        "_about": "test fixture",
        "slack_export": exp,
        "james_user_id": ME,
        "conversations": [
            {"id": "CPROJACME", "folder": "CPROJACME", "kind": "channel", "name": "proj-acmecorp",
             "status": "kept", "audience": "project team", "james_messages": 2},
            {"id": "GCLIENTAC", "folder": "GCLIENTAC", "kind": "private channel",
             "name": "ext-acmecorp-shared", "status": "kept", "audience": "clients", "james_messages": 1},
            {"id": "DSELFNOTE", "folder": "DSELFNOTE", "kind": "DM", "name": "DM (no name)",
             "status": "kept", "audience": None, "james_messages": 1},
            {"id": "DPRIYADMX", "folder": "DPRIYADMX", "kind": "DM", "name": "DM Priya Raman",
             "status": "kept", "audience": "1:1 colleagues", "james_messages": 1},
            {"id": "GMPIMTRIO", "folder": "GMPIMTRIO", "kind": "group DM", "name": "mpdm-jamie.testperson--priya.raman--tom-1",
             "status": "kept", "audience": "senior/management if the same people, else unassigned",
             "james_messages": 1},
            {"id": "CSTRUCKXX", "folder": "CSTRUCKXX", "kind": "channel", "name": "random-chat",
             "status": "struck", "audience": None, "james_messages": 1},
        ],
        "struck_conversations": ["random-chat"],
        "anonymiser_additions_candidates": {"names": ["Acme Corp"], "note": "test"},
        "group_dms_without_audience": "none",
        "agreement_reactions_extra": ["bigthumb"],
    }
    w(f"{root}/build-inputs.json", inputs)


def transcripts(root):
    p = os.path.join(root, "projects", "-work-proj")
    sid = "session-local"
    recs = [
        {"type": "user", "sessionId": sid, "uuid": "u1", "timestamp": "2026-11-01T10:00:00Z",
         "cwd": "/work/proj", "origin": {"kind": "human"}, "promptSource": "typed",
         "message": {"role": "user", "content": "Use pytest, not unittest, for the new tests"}},
        {"type": "assistant", "sessionId": sid, "uuid": "a1", "message": {"content": [
            {"type": "text", "text": "I'll write them with unittest as the repo does."},
            {"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "/work/proj/test_x.py"}},
            {"type": "tool_use", "id": "t2", "name": "AskUserQuestion", "input": {"questions": [
                {"question": "Which database for the cache?", "header": "DB", "multiSelect": False,
                 "options": [{"label": "Redis (Recommended)"}, {"label": "Postgres"}]}]}}]}},
        {"type": "user", "sessionId": sid, "uuid": "u2", "timestamp": "2026-11-01T10:01:00Z",
         "cwd": "/work/proj", "message": {"content": [{"type": "tool_result", "tool_use_id": "t2",
                                                       "content": "answered"}]},
         "toolUseResult": {"questions": [{"question": "Which database for the cache?", "header": "DB",
                                          "options": [{"label": "Redis (Recommended)"}, {"label": "Postgres"}]}],
                           "answers": {"Which database for the cache?": "Postgres"}, "annotations": {}}},
        {"type": "user", "sessionId": sid, "uuid": "u3", "timestamp": "2026-11-01T10:02:00Z",
         "cwd": "/work/proj", "origin": {"kind": "task-notification"},
         "message": {"content": "<task-notification>done</task-notification>"}},
        {"type": "user", "sessionId": sid, "uuid": "u4", "timestamp": "2026-11-01T10:03:00Z",
         "cwd": "/work/proj", "isMeta": True, "message": {"content": "Base directory for this skill"}},
        {"type": "user", "sessionId": sid, "uuid": "u5", "timestamp": "2026-11-01T10:04:00Z",
         "cwd": "/work/proj", "isSidechain": True, "message": {"content": "sidechain prompt"}},
        {"type": "user", "sessionId": sid, "uuid": "u6", "timestamp": "2026-11-01T10:05:00Z",
         "cwd": "/work/proj", "origin": {"kind": "human"},
         "message": {"content": "<command-name>/gsd:quick</command-name>\n<command-args>fix the token sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV</command-args>"}},
    ]
    w(f"{p}/{sid}.jsonl", "".join(json.dumps(r) + "\n" for r in recs))
    w(f"{p}/{sid}/subagents/agent-x.jsonl", json.dumps(
        {"type": "user", "sessionId": "sub", "uuid": "s1", "origin": {"kind": "human"},
         "message": {"content": "subagent prompt"}}) + "\n")
    other = os.path.join(root, "other-machine", "-home-x-proj2")
    w(f"{other}/session-other.jsonl", json.dumps(
        {"type": "user", "sessionId": "session-other", "uuid": "o1",
         "timestamp": "2026-10-01T09:00:00Z", "cwd": "/home/x/proj2", "origin": {"kind": "human"},
         "message": {"content": "Prompt typed on the other machine"}}) + "\n")


def gsd(root):
    r = os.path.join(root, "dev", "client_acme-corp", "acme-corp-api", ".planning")
    w(f"{r}/STATE.md", """# Project State

## Accumulated Context

### Decisions

- [Phase 1]: Mock HTTP with nock, not msw
- [Phase 2]: Keep tokens in the keychain
  because the web build has no secure store

### Blockers/Concerns

- none
""")
    w(f"{r}/phases/01-setup/01-CONTEXT.md", """# Phase 1: Setup - Context

<decisions>
## Implementation Decisions

### Test runner
- Vitest, matching the other services

### Claude's Discretion
- Folder names
</decisions>
""")
    w(os.path.join(root, "dev", "plain", "no-gsd", "README.md"), "nothing")


def bitbucket(root):
    me = {"uuid": "{me-uuid}", "account_id": "acc-me", "nickname": "jamie", "display_name": "Jamie Testperson"}
    priya = {"uuid": "{priya-uuid}", "account_id": "acc-priya", "nickname": "priya", "display_name": "Priya Raman"}
    stranger = {"uuid": "{zed-uuid}", "account_id": "acc-zed", "nickname": "zed", "display_name": "Zed Okonkwo"}
    base = "/2.0/repositories/ws/new-repo"
    diff = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,4 +1,5 @@
 import os
-import sys
+import json
+import logging
 def main():
     return 1
"""
    routes = {
        "/2.0/repositories/ws/new-repo": {"full_name": "ws/new-repo", "updated_on": "2024-05-01T00:00:00Z"},
        "/2.0/repositories/ws/old-repo": {"full_name": "ws/old-repo", "updated_on": "2017-03-01T00:00:00Z"},
        # Its PR list has no route, so an extract that reaches it fails there:
        # the stand-in for a run stopped partway.
        "/2.0/repositories/ws/broken-repo": {"full_name": "ws/broken-repo", "updated_on": "2024-05-01T00:00:00Z"},
        # The list carries author and participants. PRs 3 and 4 have no route of
        # their own: fetching either one would 404 and fail the extract.
        base + "/pullrequests": {"values": [
            {"id": 1, "author": priya,
             "participants": [{"user": me, "approved": True, "role": "REVIEWER",
                               "participated_on": "2024-04-02T10:00:00Z"}]},
            {"id": 2, "author": me, "participants": [{"user": priya, "approved": False}]},
            {"id": 3, "author": stranger, "participants": [{"user": priya, "approved": True}]},
            {"id": 4, "author": stranger,
             "participants": [{"user": me, "approved": False, "role": "REVIEWER",
                               "participated_on": None, "state": None},
                              {"user": priya, "approved": True,
                               "participated_on": "2024-04-06T10:00:00Z"}]},
        ]},
        base + "/pullrequests/1": {"id": 1, "title": "Add retries", "description": "Retries the Acme Corp sync",
                                   "state": "MERGED", "author": priya, "created_on": "2024-04-01T10:00:00Z",
                                   "participants": [{"user": me, "approved": True, "role": "REVIEWER",
                                                     "participated_on": "2024-04-02T10:00:00Z"}]},
        base + "/pullrequests/1/comments": {"values": []},
        base + "/pullrequests/2": {"id": 2, "title": "Switch to json logging", "description": "Uses json, cc Priya Raman",
                                   "state": "MERGED", "author": me, "created_on": "2024-04-03T10:00:00Z",
                                   "participants": [{"user": priya, "approved": False, "role": "PARTICIPANT"}]},
        base + "/pullrequests/2/comments": {"values": [
            {"id": 21, "user": priya, "created_on": "2024-04-03T11:00:00Z",
             "content": {"raw": "Why json here?"}, "inline": {"path": "src/app.py", "from": None, "to": 2}},
            {"id": 22, "user": me, "created_on": "2024-04-03T12:00:00Z", "parent": {"id": 21},
             "content": {"raw": "Structured logs for the aggregator"}},
            {"id": 23, "user": priya, "created_on": "2024-04-03T13:00:00Z", "deleted": True,
             "content": {"raw": "deleted"}},
        ]},
        base + "/pullrequests/2/diff": {"__raw__": diff},
    }
    w(f"{root}/bitbucket-routes.json", routes)
    w(f"{root}/test-netrc", "machine 127.0.0.1 login tester password secret-token\n")
    os.chmod(f"{root}/test-netrc", 0o600)


if __name__ == "__main__":
    d = sys.argv[1]
    slack(d)
    transcripts(d)
    gsd(d)
    bitbucket(d)
