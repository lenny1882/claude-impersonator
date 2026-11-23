# voice-runtime

The voice guide and exemplar search Claude uses to draft Slack messages, PR
descriptions, PR review comments and Jira comments in your voice, and the
record of each draft and the version you approved.

The guide and exemplars are built by `voice-decision-pipeline` and carried
to every machine by `builds-sync`. This package installs a build, refuses
one it can't read correctly (an index embedded by a different embedding
setup, a half-installed build, a file format it doesn't know), and records
the drafts the next build uses.

Needs [`embedding-lib`](../embedding-lib/) installed and set up first, for
`install-build` and `search`; the rest runs without it.

Part of [claude-impersonator](https://github.com/lenny1882/claude-impersonator), which holds several packages
that are each versioned, released and installed on their own.

## What you actually see

Before any draft for other people, the skill shows the audience and purposes
it worked out, for you to correct:

    Audience: technical-team · Purposes: status, ask

then drafts from the guide and the closest exemplars, saves the draft, and
waits for your approval of the exact text. Nothing is sent without it. Once
you approve or drop it, the final version is recorded.

`guide` gives the owner's own rules, the audience's drafting notes where
the build has them, the guide's rules for the audience and purposes, and the
measured style: length, capitals, end marks, and the share of messages
holding each mark of style (spaced dash, exclamation mark, emoji, emphasis,
list, swear word); for an audience the build names, the share of messages
holding each word the rules quote.

When the voice model can't be used, the skill says so first, with the reason
and its fix, and offers a draft marked as not in your voice:

    voice-runtime: voice model unavailable: no voice build is installed on this machine yet. Fix: builds-sync install

The commands:

    voice-runtime install-build <dir> --build-time <YYYYMMDDTHHMMSSZ>   (builds-sync runs this)
    voice-runtime guide --audience <a> --purposes <p,...>              guide text for the prompt
    voice-runtime search --audience <a> --purposes <p,...> --situation <text> [--k N]
                                                                       closest exemplars, JSON
    voice-runtime save-draft --audience <a> --purposes <p,...> --destination <d> --text-file <f>
                                                                       prints the draft's id
    voice-runtime save-final --id <id> --text-file <f> [--status approved|discarded]
    voice-runtime status                                               installed build, usable or why not

Exit 3 is a refusal, with one line saying why: no build installed yet, an
index embedded by an embedding-lib setup unlike this machine's, or a file
whose schema version this release doesn't read (naming the file, the
version found and the versions accepted). Exit 1 is a bad call or a broken
build, exit 2 an unknown command.

## Install

Needs `curl`, `tar` and `jq`. From the newest release:

    v=$(curl -fsSL https://raw.githubusercontent.com/lenny1882/claude-impersonator/versions/versions.txt | awk '$1=="voice-runtime" {print $2}')
    curl -fsSL "https://github.com/lenny1882/claude-impersonator/releases/download/voice-runtime-v$v/voice-runtime.tar.gz" | tar -xz
    cd voice-runtime && ./install.sh

These lines never change between versions: `versions.txt` names the newest
stable release, and only once its tarball is uploaded. To pin a version,
download `.../releases/download/voice-runtime-vX.Y.Z/voice-runtime.tar.gz` instead.

Or from a clone of the whole repo:

    git clone https://github.com/lenny1882/claude-impersonator && cd claude-impersonator/packages/voice-runtime
    ./install.sh              # install
    ./install.sh --link       # or symlink, so edits in the checkout are live
    ./install.sh --dry-run    # show the settings change, write nothing
    ./install.sh --yes        # no prompts

Re-running the installer is safe and is how you upgrade; the state and the
installed build stay. It merges into `settings.json` rather than replacing
it, backs the file up first, and only ever touches its own entries. If Claude
Code is already running, `/hooks` forces a settings reload. Then
`builds-sync install` installs the newest build.

## Update

    ./update.sh            check, ask, upgrade, reinstall
    ./update.sh --check    report what is available and stop

Reads this package's line in `versions.txt`, so pre-releases, and releases of
the other packages in the repo, are never offered. Works from a downloaded
tarball as well as a clone — no git needed.

## Uninstall

    ./uninstall.sh                 ask before editing settings.json
    ./uninstall.sh --keep-settings leave settings.json alone
    ./uninstall.sh --keep-state    keep the package's state for a later reinstall

## How it works

Installed:

| Path | What |
|---|---|
| `~/.claude/skills/voice-runtime/SKILL.md` | when and how to draft in your voice |
| `~/.local/bin/voice-runtime` | the command |
| `~/.local/share/voice-runtime/pylib/` | its Python module |
| `sandbox.excludedCommands`: `voice-runtime *` | the state is under `~/.claude`, outside the Bash sandbox |

State, `~/.claude/skills/voice-runtime/state/`, owner-only (directories 700,
files 600):

    builds/<build-time>/   guide.json exemplars.json stats.json build.json
                           index/vectors.npy index/ids.json index/hashes.json index/identity.json
    manifest.json          the current build and each file's schema version, written last
    drafts.jsonl           every draft and final, append-only; the newest line per id wins

**Install of a build.** `install-build` checks every file's schema version
before anything is written, copies the build into a staging directory, and
embeds the exemplars there with embedding-lib. Each exemplar's text is the
message it answered, a blank line and your message, with words dropped
from the start of the answered message until the pair fits the model's 512
tokens. Rows of the previous build's index are reused by each exemplar's
`hash`, unless the previous index's identity differs from embedding-lib's
`identity()`, in which case everything is embedded again; reinstalling the
current build is how an index is re-embedded after embedding-lib changes.
The staging directory then becomes `builds/<build-time>/`, `manifest.json`
is written, and only then is the previous build deleted. Every reader goes
through the manifest, so a build that dies halfway is never read.

**Search** keeps the exemplars of the audience that carry any of the asked
purposes, takes the closest k by dot product with the situation's embedding,
and fills up to k from the same audience, any purpose, when there are
fewer. k is the build's `exemplar_count` unless `--k` is given. Each
exemplar comes back with `matched`: `purpose` or `audience`.

**Interpreter.** `install-build` and `search` run on embedding-lib's venv
Python, `~/.local/share/embedding-lib/venv/bin/python` (moved with
`EMBEDDING_LIB_HOME`), with `embedding_lib` loaded from its install
directory and `EMBEDDING_LIB_API` checked. The other commands run there too
and fall back to the system `python3` (3.8 or later) when embedding-lib is
missing, so the guide still loads.

**Uninstall** refuses while `drafts.jsonl` exists, unless `--keep-state`:
no build can regenerate the drafts.

## Tests

    ./test/run-tests.sh

Redirects `HOME` and `CLAUDE_DIR` into a temp directory, so your real config is
never touched, uses made-up builds only (`test/fixtures.py`), and logs to
`/tmp/voice-runtime-tests.log`. The behaviour tests embed with a stand-in
`embedding_lib` (a hash-based embed and an `identity()`) reached through
`EMBEDDING_LIB_HOME`, on embedding-lib's venv Python for numpy, or on
`VR_TEST_PY`. A last group installs and searches with the real model when
embedding-lib is set up on the machine; `VR_SKIP_REAL=1` leaves it out.
`./test/run-tests.sh` at the repo root runs every package's.

## Releasing

`/release voice-runtime` at the repo root — bump `packages/voice-runtime/VERSION` on `main`,
move `release/voice-runtime-vX.x` onto it, tag `voice-runtime-vX.Y.Z` there. The tag is what
publishes it. The release carries what `PAYLOAD` lists, and nothing else in
this directory.
