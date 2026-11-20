"""voice-runtime: the guide loader and exemplar search for drafts in the owner's
voice (PLAN §3.5, §3.6), and the record of every draft and the version they
approved (§3.8).

Why it exists. A draft in someone's voice needs two things a model can't
carry between sessions: the rules of how they write to each audience, and a
few real messages close to the one being written. Rules alone give flat
drafts; examples alone carry over phrasing tied to old clients (§3.5). The
pipeline builds both on one machine, builds-sync carries them to every
machine, and this package is what a drafting session calls on each of them.

Three things it must never do, each of which fails silently if simplified:

- Search an index embedded by a different embedding setup. The dot products
  still come out as numbers, just meaningless ones, so the closest messages
  are noise with no error. `search` compares the index's stored identity
  with embedding-lib's `identity()` and refuses a mismatch (§5).
- Read a half-installed build. `install-build` writes the new build beside
  the current one and writes `manifest.json` last; everything else reads
  only what the manifest names, so a build that dies halfway is never used.
- Read a file whose schema it doesn't know. Each command checks the schema
  version of every file it reads, and only those, and refuses an unknown one
  by name (§5 "Migration").

A refusal exits 3 with one line; the skill then tells the owner the voice model
is unavailable and why, and offers a draft marked as not in their voice (§5
"After a refusal").

Runs on embedding-lib's venv Python (3.14) for `install-build` and `search`,
which load `embedding_lib` from embedding-lib's install directory and check
EMBEDDING_LIB_API. The other commands touch no numpy and also run on a
system Python as old as 3.8, so nothing here uses newer syntax.
"""

import os

PKG = "voice-runtime"
VOICE_RUNTIME_API = 1
NEEDS_EMBEDDING_LIB_API = 1

# Schema versions this release reads (contract §1, §3).
ACCEPTED = {
    "manifest.json": (1,),
    "build.json": (1,),
    "guide.json": (1,),
    "exemplars.json": (1,),
    "stats.json": (1,),
}
BUILD_FILES = ("guide.json", "exemplars.json", "stats.json")
DRAFTS_SCHEMA = 1

AUDIENCES = ("clients", "project-team", "technical-team", "senior",
             "one-to-one", "jira")
PURPOSES = ("push-back", "decline", "ask", "chase", "status", "explain",
            "approve", "own-mistake", "thank", "escalate", "small-talk", "other")

# Used only when an embedding_lib module doesn't publish its own list.
DEFAULT_COMPARED = ("api", "model", "revision", "dimension", "normalised",
                    "python", "lock_sha256")


def claude_dir():
    return os.environ.get("CLAUDE_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def state_dir():
    return os.environ.get("VOICE_RUNTIME_STATE") or os.path.join(
        claude_dir(), "skills", PKG, "state")


def embedding_lib_home():
    return os.environ.get("EMBEDDING_LIB_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share", "embedding-lib")
