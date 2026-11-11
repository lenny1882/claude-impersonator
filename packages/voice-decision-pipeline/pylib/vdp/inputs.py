"""The pipeline's inputs: build-inputs.json, moved into state.

build-inputs.json holds the conversation list, audiences, the struck list,
the candidate client names and the Slack export path, all with real names
(PLAN §1). It was written by hand before the pipeline existed and lives in
the claude-impersonator checkout, gitignored; `init-inputs` copies it into
the pipeline's state, where every later step reads it, so the checkout copy
can be deleted and nothing with real names stays beside a public repo.

`forget` and `pick-repos` add to this copy; it is never rewritten from the
original after that, so `init-inputs` refuses to overwrite it unless told to.
"""

import re

from . import state

CANONICAL_AUDIENCES = {
    "clients": "clients",
    "project team": "project team",
    "technical team": "technical team",
    "senior/management": "senior/management",
    "1:1 colleagues": "1:1 colleagues",
}


def file():
    return state.path("inputs.json")


def load(required=True):
    d = state.read_json(file())
    if d is None and required:
        raise SystemExit("voice-decision-pipeline: no inputs yet; run "
                         "'voice-decision-pipeline init-inputs <build-inputs.json>'")
    d = d or {}
    d.setdefault("struck_conversations", [])
    d.setdefault("struck_authors", [])
    d.setdefault("bitbucket_repos", [])
    d.setdefault("transcript_imports", [])
    return d


def save(d):
    state.write_json(file(), d)


def audience(raw):
    """The canonical audience for a conversation, or None while it waits for
    James on the mapping page (PLAN §3.2: group DMs outside the senior set,
    and anything the hand-written list marks as conditional)."""
    if not raw:
        return None
    key = raw.strip().lower()
    if key in CANONICAL_AUDIENCES:
        return CANONICAL_AUDIENCES[key]
    # "project team (any other internal channel, PLAN 3.2)" is settled;
    # "senior/management if the same people ..., else unassigned" is not.
    m = re.match(r"^(project team|technical team|clients|1:1 colleagues)\b", key)
    if m and " if " not in key:
        return CANONICAL_AUDIENCES[m.group(1)]
    return None


def me(d):
    """James's Slack user id: his id in every source (PLAN §2.3, one
    pseudonym per person across sources)."""
    uid = d.get("james_user_id")
    if not uid:
        raise SystemExit("voice-decision-pipeline: inputs have no james_user_id")
    return uid


def struck(d, record):
    return (record.get("conversation") in set(d["struck_conversations"])
            or record.get("author") in set(d["struck_authors"]))
