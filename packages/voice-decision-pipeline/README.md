# voice-decision-pipeline

Builds the corpus the voice and decision models are made from: Slack, Bitbucket
PRs, Claude Code transcripts and GSD records, with credentials redacted, an
anonymised copy of everything, per-source review batches, and a local
embedding index of the voice items. Then builds the voice model from it:
purpose labels, the voice guide, statistics and never-say list, exemplars,
validation against held-back messages, and a leak-checked build that
`builds-sync` carries to every machine's `voice-runtime`.

Everything sent to the Anthropic API to build the models has to be anonymised
first, by local scripts, and nothing from a source may go until its first
batch has been read and approved. Done by hand in a session, real names leak:
a subagent that reads the export carries them into its prompt. This package
is the only thing that reads the sources, keeps the real-name corpus local,
and writes the anonymised copy that the voice passes send. Only the `voice`
steps send anything, and only anonymised text, through `claude -p` on your
own login, after each source's first batch is approved.

Part of [claude-impersonator](https://github.com/lenny1882/claude-impersonator), which holds several packages
that are each versioned, released and installed on their own.

## What you actually see

    $ voice-decision-pipeline init-inputs build-inputs.json
    $ voice-decision-pipeline extract all
    == extract slack
      ok    corpus/slack.jsonl: … records {'items': …, 'context': …}
      ok    credentials redacted, by type: {'password': …, …}
    $ voice-decision-pipeline anonymise
      ner   …/… texts, … min, about … min left
      ok    … replacements {'person': …, 'client': …}; … mining candidates undecided
      ok    … single words only spaCy took for a name, … undecided: mark each on the review page's Names
    $ voice-decision-pipeline review
      ok    review page at http://127.0.0.1:8765/

The review page lists the Slack conversations the inputs leave without an
audience (group DMs outside the senior set) for you to assign, the single
words only spaCy took for a name to mark a name or not a name, the candidate
client product, store and project names to keep or strike, a form to add a
client name the lists missed, with its other spellings and identifiers, then
each source's batches of 50 anonymised items
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
    index                        embed your voice items (embedding-lib)
    review [--port N] [--no-browser]
    batch <source>               draw the next batch of 50
    sendable <source>            exit 0 once its first batch is approved, else 5
    forget <person|conversation> remove their records; strike them. A person by
                                 name or id, before or after anonymise; a
                                 conversation, Bitbucket repo or <repo>#<pr>
    show bitbucket [--repo <ws/repo>]
                                 your Bitbucket items as text, in views/
    status                       JSON: records, items, batches, sendable, modes
    paths                        where everything lives

    voice label [--second] [--redo <purposes>] [--new-sample]
    voice holdout [--fresh]
    voice rules
    voice guide
    voice validate [--limit N]
    voice pairs [--more <audience> | --drop <pair,...>]
    voice build
    voice publish
    voice status

Exit 4 means not set up, embedding-lib missing, or a venv built for another
embedding-lib Python or lock; the message says what to run.

## Building the voice model

Run in order, each in your own shell (each logs to
`/tmp/voice-decision-pipeline-voice-<step>.log`):

1. `voice label`: Sonnet 5.5 labels every voice item's purposes, 20 items a
   call, sent anonymised with its context. `voice label --second`: Opus 5.5
   labels them all again, blind. A usage limit stops either cleanly (exit 6)
   after the last finished batch; the same command resumes. `--redo
   <purposes>` sends again the items either model gave one of them; the list
   is fixed the first time it is worked out for that prompt, so the labeller's
   and the second model's redo send the same items, and a stopped redo skips
   what it already labelled under the current prompt.
2. On the review page's Voice build: the label check (120 items spread over
   audiences and purposes; more than 6 wrong fails, then the prompt is
   changed through `labelling-notes.md` in the state, the pass rerun with
   `--redo <purposes>` or in full, and `--new-sample` drawn), and 60 of the
   second model's disagreements to grade. `--new-sample` draws both samples
   afresh from the current labels, keeping earlier rounds' answers in their
   files. The disagreement rate per purpose is on the same page.
3. `voice holdout`: 10% of each audience held back for validation.
4. `voice rules` creates `own-rules.md` in the state; each `- ` line is one
   of your rules, its `## Jira` section the Jira guide. `voice guide` writes
   the statistics, the never-say list and the corpus guide (Opus 5.5).
5. `voice validate`: for every held-back message, a brief of what it says
   in neutral words (Sonnet 5.5), then drafts from that brief with 3, 5 and 8
   exemplars (Opus 5.5), judged against the real one (Fable 5.2); the best
   mean score sets the build's exemplar count. Only held-back messages the
   exemplar pool's own rule would keep (at least 4 words, under half code)
   are drafted, scored and paired. Four calls a message;
   `--limit N` does the first N, and a later run carries on from there.
6. `voice pairs`, then on the review page: 60 blind pairs (12 per audience),
   the judge's 20 worst and 10 random drafts, and the report: counts,
   spotting rate with its 95% range, confidence the pass holds.
   `voice pairs --drop p002,p010` leaves those pairs out of the result and
   draws as many new ones for the same audiences; the dropped pairs and their
   answers stay in the files, marked.
7. `voice build`: guide.json, exemplars.json, stats.json and build.json in a
   tarball in the state; the leak check reads them first and stops on any
   real name. `voice publish` sends it through `builds-sync` once the label
   check and the validation run have passed.

Each call turns off tools, settings, MCP servers and slash commands, so it
carries about 1,100 tokens of Claude Code's own overhead.

## How it works

State is `~/.claude/voice-decision-pipeline/`, owner-only (directories 700,
files 600), never backed up:

| Path | What |
|---|---|
| `inputs.json` | build-inputs.json, moved in; struck lists, picked repos |
| `corpus/<source>.jsonl` | one record per message, real names, context as ids |
| `anon/<source>.jsonl` | the anonymised copy, replacements marked, ids hashed |
| `anonymising-map.json` | append-only: real id, aliases, role, pseudonym, origin |
| `mining-candidates.json`, `mining-decisions.json` | candidate names and your keep or strike |
| `added-clients.json` | clients added by hand, with their other spellings and identifiers |
| `name-candidates.json`, `name-decisions.json` | single words only spaCy took for a name, with counts; your name or not a name |
| `batches/`, `review-state.json` | drawn batches; per-source approvals and stops |
| `index/` | `vectors.npy`, `ids.json`, `identity.json` |
| `leak-report.json` | real names the leak check found in the anonymised copies, with where |
| `leak-cleared.json` | the hits you marked cleared by hand, each with its count then |
| `views/` | `show bitbucket`'s text, real names |
| `spacy-cache.jsonl` | spaCy's tags by text hash, so reruns tag only new text |
| `bitbucket-progress/` | each finished repo of an `extract bitbucket` still running or stopped |
| `labels/` | each pass's labels, and every disagreement between them |
| `labelling-notes.md` | additions to the labelling prompt |
| `label-check.json`, `disagreement-grades.json` | your label check and disagreement grades |
| `holdouts.json` | the held-back items and the validation run |
| `own-rules.md` | your own rules, first in the guide |
| `voice/` | the corpus guide, statistics, builds and the build leak report |
| `validation/` | drafts, judge scores, blind pairs and their key, the judge review |
| `validation-answers.jsonl` | every answer you give on the validation pages, as you give it |

A record holds `id`, `source`, `conversation`, `author` (real id), `audience`,
`ts`, `text`, `tags`, `context_ids`, `reactions`, `source_fields` and
`schema_version`. `tags` carries code, log and link spans, and whole-record
tags: `item` (a corpus item: your own message, or one you agreed with by
reaction), `bot`, `reaction:<name>`, `attachment`, `approval`, `ask-user`,
`command`, `no-voice`, `claude-discretion`.

- **Slack:** your messages in the kept conversations, each with its thread,
  or the 2 hours before and after it up to 20 messages each way. Bot
  messages are context only; channel events are dropped. A thumbs-up, plus,
  tick or OK-hand reaction from you on someone else's message makes that
  message an item tagged `reaction:<name>`, never voice.
- **Transcripts:** each prompt you typed, with Claude's reply before it and a
  line per tool call; AskUserQuestion answers as items of their own. Main
  sessions only; task notifications, other sessions' messages, skill and
  hook injections and SDK runs are dropped. Other machines' copied
  `~/.claude/projects` directories are added with `import-transcripts`.
- **GSD:** each bullet under STATE.md's `### Decisions`, and each subsection
  of a CONTEXT.md `<decisions>` block, in every repo with `.planning/`.
- **Bitbucket:** in the picked repos (`extract` skips any whose `updated_on`
  is earlier than `2019-01-01`), the PRs you authored, commented on or approved, not
  those you were only added to as a reviewer. Which PRs those are is read from the PR
  list, so only they are fetched one by one; each comment with its PR and
  thread, inline comments with the code under them. Reads the REST token in
  `~/.netrc`, which must be readable by you only (`chmod 600`: Python's
  `netrc` refuses any other, though `curl` reads it); inline code needs
  `read:repository` on it. Prints a line per
  repo (PRs seen, kept, added-only, calls) and saves each finished repo to
  `bitbucket-progress/`, so a run stopped partway starts again at the first
  unfinished repo; the saved repos are cleared once `corpus/bitbucket.jsonl`
  is written.
- **URLs:** every URL whose host isn't on the public list in
  `pylib/vdp/urls.py` (code hosts and package registries, Q&A sites,
  platform, infrastructure and payment docs, `localhost`) becomes `[url]`,
  path and all: a URL with a scheme, Slack's `<url|label>` (the label stays),
  a bare host with a known top-level domain (`api.example.com/v1`) and an
  IPv4 address. A subdomain counts with its host. A URL on a public host
  stays, names in its path replaced like any other text. A bare host needs a
  lower-case top-level domain not followed by `.word`, so file names
  (`main.dart`, `settings.local.json`) stay.
- **Anonymising:** Slack mentions, emails and phone numbers; every name
  `users.json` gives each person, a first name in any case unless it is an
  ordinary word, and a first name two people share as their role
  (`colleague`, or `person` when their roles differ); the client names in
  the inputs, the clients added by hand on the review page (each with its
  other spellings and identifiers, all one pseudonym; a name on the client
  list joins that client) and the
  product names kept on the review page, inside URLs and channel names too,
  with up to three spaces, hyphens, dots or underscores between their words
  (`Acme - Store`, `acme-store`, `AcmeStore`);
  each handle in a group DM's name (`mpdm-a--b-1`), however short; then names
  spaCy (`en_core_web_trf`) tags as people, unless a client or kept product
  has the same name once spaces, hyphens, dots and underscores are dropped;
  then that form is replaced as the client or product ("Acme Corp" for a
  client listed as "AcmeCorp"). A name of two or more words is replaced wherever it
  appears, in any case. A single word is listed on the review page's Names
  with how often spaCy tagged it and how often it appears capitalised and
  in lower case (outside URLs and paths), and a suggestion: not a name when
  the lower-case count is at least the tagged count. Until you mark it, it
  is replaced only where spaCy tagged it; marked a name, everywhere in any
  case; marked not a name, nowhere. Dictionary keys inside source fields
  and reaction names are replaced too. Pseudonyms are
  role-tagged (`self-01`, `colleague-07`, `client-contact-02`, `client-03`,
  `product-04`, `person-05`) and one person keeps one across every source; a
  Bitbucket account is matched to its Slack person by name.
- **Leak check:** the last step of `anonymise` searches what is sent of
  every anonymised record (text, source fields with their keys, reactions,
  author; not the source name, tag types, ids or timestamps) for every full
  name, handle of 3 characters or more and email in `users.json`, the
  Bitbucket accounts' names, the map's aliases and unique first names,
  first names two people share, and the client and kept product names. A
  single word only spaCy found counts once marked a name; undecided ones
  are counted apart. The pipeline's own pseudonyms are skipped, so a word
  before one (`acme product-07`) doesn't spell a kept product's name with
  it. A URL on a host that isn't public is a leak too, its host the term,
  unless the host holds a pseudonym: a public host whose label is a kept
  product or a client spelling is sent with the pseudonym inside it
  (`docs.product-04.com`), and that is accepted. An identifier added by
  hand is searched for from 2 characters. Anything found is listed on the
  review page with where it was, and under each snippet every pseudonym in
  it is named with the real term behind it, read from the map. A hit that
  isn't a leak (an identifier read as a host name)
  can be marked cleared by hand there; one found more times later is
  outstanding again. No `voice` step sends anything, and no build is
  written, while a term is neither fixed nor cleared.
- **Mining:** every text a record sends is read, its text and every string
  in its source fields (keys included; not timestamps), except code: fenced
  and inline code and log lines are blanked, and the code under a Bitbucket
  inline comment (the `inline` field) is skipped. Code is still sent, with
  known names replaced, so a name that appears only in code and is on no
  list is sent as written. Two routes onto the
  list: spaCy tags a term as an organisation or product at least twice
  (spaCy tags every source field but tool calls, paths, branch names, links
  and file names), or a word that isn't in the bundled English dictionary is
  used at least 3 times in conversations mapped to a client, 80% of them one
  client's. Left off: fragments that can't be a name, terms no record holds
  any more, and terms in three or more clients' conversations. Case decides
  nothing: spellings that differ only in case are one term, shown as its
  decided spelling or its commonest, and one decision covers them all. Each
  term is suggested keep (not made only of dictionary words, and mostly or
  only in one client's conversations), strike (only dictionary words, not
  concentrated in one client), or left to check by hand. The dictionary is
  `pylib/vdp/data/words.txt`: SCOWL's British and American lists, lower-case
  entries only, built by `tools/build-wordlist.sh` (licence in
  `WORDS-LICENCE.txt` beside it). It is built, never committed: the release
  workflow builds it into the tarball, and in a checkout the tests build it
  when it is missing. The page shows one section at a time
  (check by hand, suggested keep, suggested strike, decided), each with its
  own keep-all and strike-all; a decided term leaves its section. A fifth,
  Earlier runs, lists terms decided in an earlier run that this run didn't
  list, each with its decision, so a struck one can still be kept. Keep
  means replace for good: a kept term is in the map, and striking it later
  has no effect; reversing a keep means editing its decision and map entry
  in the state.
- **Gates:** no batch is drawn while a mining candidate or a word on Names is
  undecided, or after a decision until `anonymise` has run again; nor after an audience is set on
  the review page until `extract slack` and then `anonymise` have run again;
  nor after a client is added or removed, or the public host list changes,
  until `anonymise` has run again. A batch drawn before the last `anonymise`
  can only be rejected: its items are no longer what is sent.
- **Index:** your Slack and Bitbucket voice items, each embedded with the
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
