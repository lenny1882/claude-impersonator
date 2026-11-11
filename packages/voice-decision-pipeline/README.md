# voice-decision-pipeline

Builds the corpus the voice and decision models are made from: Slack, Bitbucket
PRs, Claude Code transcripts and GSD records, with credentials redacted, an
anonymised copy of everything, per-source review batches, and a local
embedding index of the voice items.

Everything sent to the Anthropic API to build the models has to be anonymised
first, by local scripts, and nothing from a source may go until its first
batch has been read and approved. Done by hand in a session, real names leak:
a subagent that reads the export carries them into its prompt. This package
is the only thing that reads the sources, keeps the real-name corpus local,
and writes the anonymised copy that later passes send. This release covers
extraction only; nothing in it sends anything anywhere.

Part of [claude-impersonator](https://github.com/lenny1882/claude-impersonator), which holds several packages
that are each versioned, released and installed on their own.

## What you actually see

    $ voice-decision-pipeline init-inputs build-inputs.json
    $ voice-decision-pipeline extract all
    == extract slack
      ok    corpus/slack.jsonl: … records {'items': …, 'context': …}
      ok    credentials redacted, by type: {'password': 2, …}
    $ voice-decision-pipeline anonymise
      ner   500/9000 texts, 3.1 min, about 52 min left
      ok    … replacements {'person': …, 'client': …}; … mining candidates undecided
    $ voice-decision-pipeline review
      ok    review page at http://127.0.0.1:8765/

The review page lists the candidate client product, store and project names
to keep or strike, then shows each source's batches of 50 anonymised items
with every replacement highlighted. Approving a source's first batch is what
lets later passes send it (`voice-decision-pipeline sendable <source>`).

Every command logs to `/tmp/voice-decision-pipeline-<command>.log`.

## Install

Needs `embedding-lib` installed and set up first: the pipeline's venv is
built from its bundled Python 3.14, and `index` runs on its environment.
Also `curl`, `tar`, `jq`, about 2.4 GB free, and `pypi.org`,
`files.pythonhosted.org`, `download.pytorch.org` and `github.com` during
setup. At install, one question: download about 1.8 GB (spaCy, the
`en_core_web_trf` model and its CPU PyTorch) into
`~/.local/share/voice-decision-pipeline/`? From the newest release:

    v=$(curl -fsSL https://raw.githubusercontent.com/lenny1882/claude-impersonator/versions/versions.txt | awk '$1=="voice-decision-pipeline" {print $2}')
    curl -fsSL "https://github.com/lenny1882/claude-impersonator/releases/download/voice-decision-pipeline-v$v/voice-decision-pipeline.tar.gz" | tar -xz
    cd voice-decision-pipeline && ./install.sh

These lines never change between versions: `versions.txt` names the newest
stable release, and only once its tarball is uploaded. To pin a version,
download `.../releases/download/voice-decision-pipeline-vX.Y.Z/voice-decision-pipeline.tar.gz` instead.

Or from a clone of the whole repo:

    git clone https://github.com/lenny1882/claude-impersonator && cd claude-impersonator/packages/voice-decision-pipeline
    ./install.sh              # install
    ./install.sh --link       # or symlink, so edits in the checkout are live
    ./install.sh --dry-run    # show the settings change, write nothing
    ./install.sh --yes        # no prompts

Re-running the installer is safe and is how you upgrade. It merges into
`settings.json` rather than replacing it, backs the file up first, and only ever
touches its own entries. If Claude Code is already running, `/hooks` forces a
settings reload.

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

Uninstall refuses while the state holds files that can't be rebuilt — the
anonymising map, the mining and batch decisions, the inputs with their
`forget` changes — unless `--keep-state` is given.

## Commands

    setup [--yes]                build the venv; asks first unless --yes
    check                        spaCy finds both names in a made-up sentence
    init-inputs <file>           copy build-inputs.json into state
    pick-repos <ws/repo>... [--me <id>] [--remove <ws/repo>]
    extract <slack|transcripts|gsd|bitbucket|all> [--gsd-root <dir>]
    import-transcripts <dir> [--machine <name>]
    anonymise                    anonymised copies and mining candidates
    index                        embed James's voice items (embedding-lib)
    review [--port N] [--no-browser]
    batch <source>               draw the next batch of 50
    sendable <source>            exit 0 once its first batch is approved, else 5
    forget <person|conversation> remove their records; strike them
    status                       JSON: records, items, batches, sendable, modes
    paths                        where everything lives

Exit 4 means not set up, embedding-lib missing, or a venv built for another
embedding-lib Python or lock; the message says what to run.

## How it works

State is `~/.claude/voice-decision-pipeline/`, owner-only (directories 700,
files 600), never backed up:

| Path | What |
|---|---|
| `inputs.json` | build-inputs.json, moved in; struck lists, picked repos |
| `corpus/<source>.jsonl` | one record per message, real names, context as ids |
| `anon/<source>.jsonl` | the anonymised copy, replacements marked, ids hashed |
| `anonymising-map.json` | append-only: real id, aliases, role, pseudonym, origin |
| `mining-candidates.json`, `mining-decisions.json` | candidate names and James's keep or strike |
| `batches/`, `review-state.json` | drawn batches; per-source approvals and stops |
| `index/` | `vectors.npy`, `ids.json`, `identity.json` |
| `spacy-cache.jsonl` | spaCy's tags by text hash, so reruns tag only new text |

A record holds `id`, `source`, `conversation`, `author` (real id), `audience`,
`ts`, `text`, `tags`, `context_ids`, `reactions`, `source_fields` and
`schema_version`. `tags` carries code, log and link spans, and whole-record
tags: `item` (a corpus item: James's own message, or one he agreed with by
reaction), `bot`, `reaction:<name>`, `attachment`, `approval`, `ask-user`,
`command`, `no-voice`, `claude-discretion`.

- **Slack:** James's messages in the kept conversations, each with its thread,
  or the 2 hours before and after it up to 20 messages each way. Bot
  messages are context only; channel events are dropped. A thumbs-up, plus,
  tick or OK-hand reaction from James on someone else's message makes that
  message an item tagged `reaction:<name>`, never voice.
- **Transcripts:** each prompt James typed, with Claude's reply before it and a
  line per tool call; AskUserQuestion answers as items of their own. Main
  sessions only; task notifications, other sessions' messages, skill and
  hook injections and SDK runs are dropped. Other machines' copied
  `~/.claude/projects` directories are added with `import-transcripts`.
- **GSD:** each bullet under STATE.md's `### Decisions`, and each subsection
  of a CONTEXT.md `<decisions>` block, in every repo with `.planning/`.
- **Bitbucket:** in the picked repos (`extract` skips any whose `updated_on`
  is earlier than `2019-01-01`), the PRs James authored, commented on or approved; each comment with its PR and
  thread, inline comments with the code under them. Reads the REST token in
  `~/.netrc`; inline code needs `read:repository` on it.
- **Anonymising:** Slack mentions, emails and phone numbers; every name
  `users.json` gives each person; the client names in the inputs and the
  product names kept on the review page, inside URLs and channel names too;
  then names spaCy (`en_core_web_trf`) tags as people. Pseudonyms are
  role-tagged (`self-01`, `colleague-07`, `client-contact-02`, `client-03`,
  `product-04`, `person-05`) and one person keeps one across every source; a
  Bitbucket account is matched to its Slack person by name.
- **Gates:** no batch is drawn while a mining candidate is undecided, or after
  a decision until `anonymise` has run again.
- **Index:** James's Slack and Bitbucket voice items, each embedded with the
  message it answers, trimmed from the start of that message to fit 512
  tokens. Not transcripts, GSD records, reactions, approvals or the self-DM.

Two interpreters, both on embedding-lib's bundled Python 3.14: the pipeline's
venv runs everything but `index`, which runs on embedding-lib's venv so the
index is embedded by exactly the setup the voice runtime queries with. The
venv's stamp records embedding-lib's Python version and the lock's hash;
when either changes, every command refuses until `setup` rebuilds it.
`spacy-curated-transformers` is pinned to 0.3.0 because 0.3.1 refuses Python
3.14 and `en_core_web_trf` 3.8.0 needs a 0.x.

`~/.claude` is outside Claude Code's Bash sandbox, so the install adds
`voice-decision-pipeline *` to `sandbox.excludedCommands`; uninstall takes it
out.

## Tests

    VDP_TEST_HOME=<a home built by setup> ./test/run-tests.sh
    VDP_SKIP_REAL=1 ./test/run-tests.sh      # without the real-venv group

Redirects `HOME` and `CLAUDE_DIR` into a temp directory, so your real config is
never touched, and runs every step on made-up data (`test/fixtures.py`, and a
fake Bitbucket API in `test/fake_bitbucket.py`). The real-venv group runs
the installed command with spaCy and builds an index with embedding-lib.
Logs to `/tmp/voice-decision-pipeline-tests.log`. `./test/run-tests.sh` at
the repo root runs every package's.

`test/docker/e2e.sh` installs embedding-lib and this package for real in the
monorepo's Docker box and runs the whole flow through the installed command,
including the uninstall refusal (`test/docker/box.sh up` first; your own
terminal or `!`).

`tools/lock.sh <uv>` regenerates `pylib/requirements.txt` from
`pylib/requirements.in`; the lock is never edited by hand.

## Releasing

`/release voice-decision-pipeline` at the repo root — bump `packages/voice-decision-pipeline/VERSION` on `main`,
move `release/voice-decision-pipeline-vX.x` onto it, tag `voice-decision-pipeline-vX.Y.Z` there. The tag is what
publishes it. The release carries what `PAYLOAD` lists, and nothing else in
this directory.
