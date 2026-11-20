# Voice and decision models — requirements

Two models, built from the owner's own writing and decisions:

1. **Voice model**: Claude drafts Slack messages, PR descriptions, PR review
   comments and Jira comments in the owner's voice. Every draft goes to the
   owner for approval before anything is sent.
2. **Decision model**: orchestrators and agents settle some technical
   questions the way the owner would, and ask the owner about the rest.

The two share only the sources and corpus preparation (§1, §2). Uses,
analysis, output, loading, validation and upkeep are separate (§3, §4). §7
holds checked facts. §8 holds what is still to build.

---

## 1. Shared: sources

| Source | Used for | Scope |
|---|---|---|
| Slack export (JSON) | voice and decisions | the conversations kept in the pipeline's inputs |
| Bitbucket PR descriptions and comments | voice (technical team audience) and code-level decisions | `oneiota` repos picked in the inputs; a repo whose last update is older than `bitbucket.CUTOFF` is skipped |
| Claude Code transcripts (`~/.claude/projects/*/*.jsonl`) | technical decisions only, never voice | everything kept from now on |
| GSD written records: decisions in `.planning/STATE.md`, phase `CONTEXT.md` | decisions, weighted by origin (§4.9) | every repo with `.planning/`; files are read once they exist |
| grill-with-docs ADRs (`docs/adr/`) and `GLOSSARY.md` | not used until grill-with-docs is in use; a reader is added then | none |
| `/gsd:profile-user` output | decisions | run on anonymised copies only (§2.3) |

Conversation-level values (conversation ids, names, the struck and kept
lists, audience assignments, candidate client names) are the pipeline's
input, held with real names in `build-inputs.json` on the owner's machine
only, never committed.

Not sources:

- Jira. Jira comments still get the voice model as an output.
- Email and documents.
- Anything outside the Slack export folder.
- Struck conversations.
- Git commit messages.
- Subagent (sidechain) transcripts.
- Transcripts from other machines and claude.ai cloud sessions.
  `import-transcripts <dir>` reads another machine's `~/.claude/projects`
  through the same anonymising and filters if one is copied here.
- New Slack data after the export ends. A later slackdump export goes through
  the same local steps. The Slack connector is not used for this: it would
  send real names before anonymising.

## 2. Shared: corpus preparation

### 2.1 Context kept per item

- **Slack:** each of the owner's messages keeps its thread if threaded;
  otherwise the messages before it in that conversation from the previous 2
  hours (up to 20), the same after it (up to 20), and emoji reactions.
- **Bot messages and channel events:** neither is a corpus item. A bot
  message in the thread or window of one of the owner's messages is kept as
  context, tagged `bot`, never used as voice or as the owner's decision, and
  anonymised. Channel events are dropped.
- **The owner's reactions on other people's messages:** agreement reactions
  (thumbs-up, plus, tick and OK-hand kinds, plus the workspace's custom ones
  listed in the inputs as `agreement_reactions_extra`) make the message
  reacted to, with its context, a corpus item tagged `reaction:<name>`.
  Decision extraction treats it as a possible agreement only where the
  message proposes something; it is never voice. Other reactions are
  context only.
- **Pasted code, logs, links and attachments:** kept and tagged. Voice
  analysis skips them; decision analysis reads them. Links are kept as URLs,
  attachments as file names.
- **Transcripts:** each typed prompt, the text of Claude's reply before it,
  a one-line summary per tool call (which file, which command),
  AskUserQuestion questions and answers, project name and date.
- **Bitbucket:** each comment with its PR title, description and thread,
  for PRs the owner authored, commented on or approved (a silent approval
  counts). A PR the owner was only added to as a reviewer is left out. Which
  PRs qualify is read from the PR list, and only those are fetched. Inline
  comments get the code under them from the API (needs `read:repository`).
  Each finished repo of an extract is saved, so a stopped run resumes at the
  next repo.

### 2.2 Storage

- Corpus: in `voice-decision-pipeline`'s state, `~/.claude/
  voice-decision-pipeline/`. One record per message, one file per source
  (`slack.jsonl`, `transcripts.jsonl`, `bitbucket.jsonl`), each message
  stored once, context held as ids. Fields: `id`, `source`, `conversation`,
  `author` (real id), `audience`, `ts`, `text`, `tags` (code, log, link and
  attachment spans), `context_ids`, `reactions`, `source_fields`,
  `schema_version`. Readers join on ids to rebuild a context window.
- Embedding indexes (the corpus index and `voice-runtime`'s `index/`): a
  NumPy `.npy` float32 matrix, `ids.json` mapping rows to record ids, and
  `identity.json` holding `embedding-lib`'s `identity()`. Search is a dot
  product over every row. The corpus index holds the owner's Slack and
  Bitbucket voice items only.
- Anonymising map: one append-only `anonymising-map.json`. Each entry holds a
  real id, every alias seen, its kind (person, client, product), role,
  pseudonym and origin (`users.json`, a list, spaCy, mining). A counter per
  role means numbers are never reused or renumbered.
- Every package's state is owner-only: directories 700, files 600. Scripts
  set umask 077 before writing; each install creates its state directory as
  700 and its verify step checks the modes.
- No backup. The drafts, decision log and questions reach the builds repo,
  encrypted (§5); the `age` key has a copy outside the machine.
- State is kept until the owner deletes it. `forget <person|conversation>`
  (also a Bitbucket repo or PR) removes the items from the corpus and its
  index, rewrites the index matrix without them, and adds them to the struck
  list so later builds and extracts skip them. It works before `anonymise`,
  from the sources' own people lists. The person's map entry stays, so
  mentions of them are still replaced and their number never passes to
  someone else.
- Real names are kept in the stored corpus.
- `~/.claude` is outside Claude's Bash sandbox, so the pipeline's commands
  get a `sandbox.excludedCommands` entry.
- No data ever goes into a package repo or release.

### 2.3 Privacy: anonymise before anything is sent

- Anything sent to a model is anonymised and redacted first, by local
  scripts in `voice-decision-pipeline`, the only package that runs them. The
  map stays local, so results can be turned back into real names on this
  machine.
- `anonymise` and mining run in the owner's own shell. Claude never reads
  the map, the name and mining files, the raw corpus or the leak report's
  terms.
- **Lists:** every name in `users.json` (full name, display name, handle,
  first name), Slack user ids and @mentions, client names from the inputs,
  email addresses (`[email]`), phone numbers (`[phone]`).
  - A first name is matched in any case. A first name two people share
    becomes their role (`colleague`, or `person` when their roles differ).
  - A name's pattern allows up to three separators between its words.
  - A form that matches a client or kept product's name once spaces,
    hyphens, dots and underscores are dropped is replaced as that client or
    product.
  - Group DM names (`mpdm-<handle>--<handle>-N`) are anonymised handle by
    handle, however short a handle is.
  - Dictionary keys inside source fields and reaction names are anonymised.
- **spaCy:** `en_core_web_trf` tags names the lists miss. It runs in the
  pipeline's own venv on `embedding-lib`'s bundled Python, pinned in the
  pipeline's lock file (spaCy 3.8, `spacy-curated-transformers` 0.3.0). The
  verify step fails if `embedding-lib`'s Python version changes, until the
  venv is rebuilt. Tags are cached by text hash, so a rerun tags only new
  text. Python runs unbuffered, so progress reaches the log as it happens.
  - A name of two or more words only spaCy finds is replaced everywhere, in
    any case.
  - A single word only spaCy finds is listed on the review page's Names
    with its counts and a suggestion, and the owner marks it a name or not a
    name. Marked a name, it is replaced everywhere; not a name, never;
    undecided, only where spaCy tagged it, and no batch is drawn.
  - A client or kept product of the same name stays that, not a person.
- **Mining** finds product, store and project names that identify a client
  on their own: terms spaCy tags as an organisation or product, and
  capitalised terms concentrated in one client's conversations. The owner
  keeps or strikes each on the review page's Mining tabs (check by hand,
  suggested keep, suggested strike, decided) before the first batch is sent;
  kept terms join the replacement list.
  - An ordinary word is one in a dictionary built from SCOWL lower-case
    entries at release (`tools/build-wordlist.sh`), never committed. Case
    decides nothing.
  - Every sent text is mined, source fields included. Tool calls, paths,
    branch names, links, file names and code (fenced and inline code, log and
    stack-trace lines, the `inline` field of Bitbucket inline comments) are
    not mined. Only code marked by its writer or fetched as code is skipped.
    Known names are still replaced in code.
  - Left off the list: fragments that can't be a name (no letters, one or
    two letters or digits, punctuation at either end, markup, a line break),
    terms in three or more clients' conversations, and terms the corpus no
    longer holds. Each run writes the list afresh.
  - Suggested strike: a term starting in lower case, or one made of ordinary
    words that isn't concentrated in one client. Suggested keep: a term that
    isn't an ordinary word and sits mostly, or with at least half its uses,
    in one client's conversations.
  - Keep means replace: a kept term gets a map entry, and every product entry
    in the map is replaced whatever its decision says now. Reversing a keep
    needs its decision and map entry edited in the state.
  - Terms decided in an earlier run and not listed in the current one have
    their own section, each with its decision.
- **Clients added by hand:** the review page takes a client name the lists
  and mining missed, with its other spellings and identifiers, all one
  pseudonym. An identifier added this way is matched from 2 characters.
- **URLs:** a URL whose host isn't on the public list (`urls.py`: code
  hosts, package registries, Q&A sites, platform, infrastructure and payment
  docs, `localhost`) becomes `[url]`, path and all. A public one stays, with
  names in its path replaced; a public host whose label is a kept product or
  a client spelling gets the pseudonym inside the host.
- **Paths and ids:** full paths, working directories and repo slugs keep
  only their last part, anonymised. Record ids are hashed; `real_id()` maps
  them back locally.
- **Pseudonyms:** stable, with a role tag (`colleague-07`, `client-pm-02`);
  clients become codes (`client-03`). The owner is `self-01`. A person is
  `client-contact` when outside the owner's Slack team and in no internal
  conversation, otherwise `colleague`; a name only spaCy finds becomes
  `person-NN`. Each person keeps one pseudonym across every source.
- **Credentials** (AWS, Slack and Bitbucket keys, JWTs, private keys,
  `password=` lines) are replaced with `[REDACTED:<type>]` while building the
  corpus, logged by type and count, never value.
- **Leak check**, at the end of `anonymise`: every real name, handle, email,
  client name and kept product the pipeline knows is searched for in every
  anonymised record, over what is sent only (text, source fields with their
  keys, reactions, author). JSON escapes and the pipeline's pseudonyms are
  blanked before the search, lengths kept. A single spaCy word counts once
  marked a name. A private URL host is a hit. A host holding a pseudonym is
  accepted. Hits, with snippets, are written to `leak-report.json` (never
  sent) and shown on the review page, each snippet with the real term behind
  every pseudonym in it, read from the map on this machine.
  - A hit that isn't a leak (an iOS app-group identifier read as the host
    `group.com`) is marked cleared by hand on the leak page. The mark keeps
    the count found; a term found more times later is outstanding again.
  - The voice steps that send (`voice label`, `voice guide`, `voice
    validate`) refuse while the report has a term neither fixed nor cleared.
    Refusals name kinds and counts, never a term.
  - Batches wait for `anonymise` after a client is added or the host list
    changes. A batch drawn before the last `anonymise` can only be rejected.
- **Review batches:** 50 anonymised messages each, every replacement
  highlighted, drawn per source (Slack, Bitbucket PRs, transcripts, GSD
  records; imported transcripts count as transcripts). Nothing from a source
  is sent until its first batch is approved. Review continues per source
  until the owner stops it. Batches are rejected and review stopped only on
  the review page.
- All of the corpus may be sent, anonymised: every kept message with its
  context, for labelling, second-model labelling, extraction and validation,
  plus the decision filter's miss-rate sample.
- Corpus text reaches a model only through the pipeline's own scripts: one
  call per batch, its result written straight to the state, each item sent
  once per pass. Subagents and Workflows never carry corpus text. Passes run
  outside any Claude Code session, log to a file, stop cleanly at a usage
  limit and resume from the last finished batch. Prompts change between
  passes, not during one.
- Exemplars loaded into drafting prompts are sent anonymised: the build
  holds a pre-anonymised copy, so `voice-runtime` never runs the anonymiser.
- Built outputs (voice guide, exemplars, principles, evidence quotes, client
  constraints) are stored with real names and as an anonymised copy; only
  the anonymised copy is sent. Client constraints are matched to a repo
  locally, against the real-name copy, and only the client code is sent.
- Anything else the pipeline sends that isn't from the copies (the struck
  rules shown to the guide model) is leak-checked first; what fails isn't
  sent.
- Reviewer hooks send code diffs from the working repo un-anonymised: they
  aren't corpus data, the session that wrote them already sent them, and
  client constraints need real names to match the code.
- `/gsd:profile-user` is not run as shipped (its agent reads raw transcript
  samples). Its steps are run by hand: run the sampler, anonymise the sample,
  give the anonymised file to `bm-user-profiler`, keep the output in the
  pipeline's state, and answer "neither" to writing it into a CLAUDE.md.
  GSD's plugin files are not edited. It is rerun with every pipeline rebuild.

### 2.4 Time

- No cut-off for Slack or transcripts. Bitbucket keeps its own rule (§1).
- When an older and a newer position disagree, both are kept and marked
  unresolved. Every such conflict is listed for the owner to decide, and no
  orchestrator gets the decision model until each is decided.

---

## 3. Voice plan

### 3.1 Uses

- Slack messages, PR descriptions, PR review comments, Jira comments.
- Jira comments are their own audience (§3.2), with no exemplars: their
  guide is the `## Jira` section of the owner's rules file (§3.5).
  Validation can't test Jira drafts.
- Where a tool sets a format (the PR description template in `/gsd:ship`,
  the comment format of `/code-review --comment`), the tool
  keeps its structure and the voice model does the wording inside it.
- At drafting time Claude works out the audience (from where the draft is
  going, by the §3.2 mapping) and purposes (from the request), and shows both
  above the draft for the owner to correct.
- Slack drafts go out through the Slack connector. Every draft needs the
  owner's approval of the exact text before it is sent.

### 3.2 Audiences

| Audience | Conversations |
|---|---|
| Clients | client channels, and DMs with client-side contacts |
| Project team | internal project channels, and any other internal channel |
| Technical team | technical channels, all Bitbucket PR content |
| Senior / management | senior and management channels, group DMs with the same people |
| 1:1 colleagues | one-to-one DMs |
| Jira | none: rules only, no exemplars (§3.1) |

- Each conversation is assigned by its name and members; the owner checks
  the mapping.
- Other group DMs are assigned one by one on the review page's audience
  mapping, which lists each with its members and a button per audience. A
  group DM new in a later export comes up there. A change holds batches
  until `extract slack` and `anonymise` have run again.
- The owner's DM with themself is out of voice and kept for decisions.

### 3.3 Purposes

- Each message can carry several purposes, in the order they appear: push
  back / disagree; decline; ask / request; chase / nudge; status / update;
  explain / instruct; approve / agree; own a mistake / apologise; thank /
  praise; escalate; small talk / humour. Anything else is "other".
- The guide records how purposes are combined.
- A message counts in every audience-and-purpose cell it carries. Label
  checks cover every label on a sampled message.

### 3.4 Analysis and checking

- Local statistics (no API): length, capitalisation, punctuation, openings,
  sign-offs, emoji, spelling, common words and phrases. Every voice item
  counts, including those too short or code-heavy to be exemplars.
- Audience comes from the conversation (§3.2). Sonnet 5.5 labels purposes on
  anonymised messages, 20 items a call. The labelling prompt is changed
  through `labelling-notes.md` in the state; `voice label --redo <purposes>`
  resends the items either model gave one of those purposes.
- Opus 5.5 labels every message blind as the second labeller.
- Label check: the owner checks a sample of 120 labelled messages spread
  across audiences and purposes (more on request). Over 5% wrong (more than 6
  of 120), the prompt is changed and rerun, and a fresh sample is checked.
- Disagreements: the rate per purpose is measured over every message and
  shows where the prompt is weak; those purposes get the prompt fixed and are
  relabelled. A fixed sample of 60 disagreements comes to the owner to grade
  (more on request). Every disagreement is recorded with both models' labels.
  The disagreement page puts the two models on sides A and B per item by a
  seeded coin toss.

### 3.5 Output

- A voice guide, split by audience and purpose, written by Opus 5.5 from the
  exemplar pool without the holdouts.
- A measured never-say list: phrases common in generic business writing that
  self-01 uses rarely or never, each with self-01's count. Built locally from
  the anonymised copies against two references: phrases of 2 to 4 dictionary
  words common in other people's messages and rare in self-01's; and the
  fixed committed list `data/generic-phrases.txt`. A phrase holding a
  pseudonym's kind word, a placeholder or an emoji name is never formed.
- Exemplars from the whole labelled corpus, minus messages of 3 words or
  fewer and messages at least 50% code or logs by characters (fenced blocks
  and unfenced log or stack-trace lines). The thresholds are config values;
  changing them reruns exemplar selection only. Code is stored as `[code]`.
- Exemplar choice: labels narrow the pool to the audience and purposes, then
  similarity search picks the closest, as many as validation sets (§3.7). A
  thin cell is filled from the same audience, closest by similarity whatever
  the purpose. Similarity uses `BAAI/bge-base-en-v1.5` locally on the CPU.
  Each message is embedded with the message it answers, within the model's
  512-token limit.
- Drafts use the guide and exemplars together.
- For drafts to other people, the owner's voice wins over the CLAUDE.md
  writing rules; those rules still govern everything Claude writes to the
  owner.
- **Own rules:** `own-rules.md` in the pipeline's state, owner-only, never
  committed, created by `voice rules`. Each `- ` line is copied word for word
  as the guide's first section at each build, and wins over every corpus
  rule. Its `## Jira` section is the Jira guide. It reaches other machines
  inside the encrypted build.
- **Struck rules:** `struck-rules.md` in the state, created by `voice rules`.
  A corpus rule under `## Rules`, or a never-say phrase under `## Never say`,
  is left out when the guide is assembled and rendered, so validation drafts
  and builds go without it. Matching ignores case, spacing, quote marks and
  end punctuation. `voice guide` tells the guide model not to write a struck
  rule or one like it. The file isn't shipped.
- Drafts are shown, for each word the guide's rules quote, how rarely
  self-01 writes it to that audience.

### 3.6 Loading

- A skill holds the guide and calls the exemplar search, a local script
  that takes audience, purposes and a description of the situation and
  returns the closest messages (the count set in §3.7), anonymised.
- A line in `~/.claude/CLAUDE.md` says to load it before any draft for other
  people, because a skill alone loads only when its description matches.
- The skill serves the main session and subagents alike: a subagent with
  the Skill tool sees the same skill list.
- The skill gives Claude the same drafting rules validation uses (§3.7).

### 3.7 Validation

- 10% of each audience's messages are held back from the exemplar pool.
  Only held-back messages the exemplar pool's own rule keeps, with 4 words
  still left once links and code show as `[url]` and `[code]`, count.
- For each, Sonnet 5.5 writes a brief of what the message says in neutral
  words; Opus 5.5 drafts from the brief, its context, audience and purposes,
  with 3, 5 and 8 exemplars. The best mean judge score sets the build's
  exemplar count.
- The drafter is told to write as briefly, loosely and plainly as self-01,
  and how rarely each word the guide's rules quote appears.
- Validation runs again if the drafting model changes. A drafter change can
  be validated for one audience alone: only that audience is drafted and
  paired again, and the other audiences' drafts, pairs and answers stand
  (`validate.KEPT`).
- Blind pairs: the owner's real message and the draft, shuffled, 12 per
  audience across the five corpus audiences, covering as many purposes as
  each audience's held-back messages allow. The owner answers "A is mine",
  "B is mine" or "can't tell", then grades the draft 1–5 on the judge's
  scale, shown on the page: 5 could pass for the owner's, 4 would send with
  no or trivial changes, 3 right idea but needs editing, 2 wrong voice or
  content, 1 unusable. The grade is asked after the pick, once the page says
  which side was the draft.
- Both sides show code as `[code]` and every link as `[url]`. A pair whose
  answer was given away can be dropped and replaced for the same audience.
- Pairs are drawn in batches of 12. A pair's message is one no earlier pair
  used; a pair whose real side the owner has seen isn't blind.
  `voice pairs --redraw <audience>` drops an audience's pairs and draws one
  batch of 12 from messages never paired, holding back as many as needed.
  Replaced pairs and their answers stay in the files, marked with why.
- When an audience runs out of pairs, `voice holdout --more <audience>`
  holds back more (default 12), only from messages that count and that the
  guide was never shown.
- The review pages save progress between sittings. The progress file holds
  pair ids and answers only; the key stays in the state. Each answer is
  written as it is given, to `validation-answers.jsonl`. The pages have
  audience tabs with how many are left.
- A model judge, Fable 5.2, scores every draft against the real message,
  mostly on voice, given the same brief. The owner also reviews the judge's
  20 worst-scored drafts and 10 random ones each run.
- Pass: every gate passes on its own. The spotting rate is right picks minus
  wrong picks as a share of pairs. How sure a rate is comes from a Dirichlet
  over the right, wrong and can't-tell counts.
  - Blind test: at least 80% sure the overall spotting rate is at most 10%.
  - Each audience: at least 80% sure its spotting rate is at most 25%.
    Between 50% and 80% sure, it gets 12 more pairs and is worked out
    again; under 50%, it fails.
  - Grades: at least 80% of drafts at 4 or higher overall, at least 70% in
    each audience, none at 1.
  - Judge scores are no gate.
- Report: counts (right, wrong, can't tell; overall, per audience, per
  purpose), the spotting rate with a 95% range, the confidence each gate
  holds, and the pairs the owner got right, side by side.
- Every check can be run on more items; each bar is a rate.

### 3.8 Upkeep

- The skill saves each draft and the version the owner approved. When the
  owner edits a draft after it leaves Claude, the next build matches the
  saved draft to the message actually sent (same conversation, close in
  time, closest by similarity) and records that as the approved version.
- A review session is offered once 20 edited drafts or decision items have
  built up, or 4 weeks have passed (config values); the owner can start one
  at any time. It runs on the local review page: recurring edits shown as
  suggested lines for the rules file, approved versions proposed as
  exemplars, each accepted or rejected.
- Decision review is the same session's Decisions tab: inferred reasons,
  bulk-accepted records, what Claude chose after a "You decide", reviewer
  blocks from subagents and GSD runs, phase-audit finds, recommendations
  against the owner's choices, and ladder promotions, each with its
  evidence, accepted, rejected or corrected one by one.
- Approved versions join the exemplar pool only through review sessions.

---

## 4. Decision plan

### 4.1 What may be decided alone

- Agents may decide alone only on: **libraries and tooling** (which
  package, framework or tool), **code structure** (where code lives, naming,
  patterns, how modules split) and **test approach** (what to test, at what
  level, with which tools). Everything else, scope cuts included, goes to
  the owner.
- An agent decides alone only if the kind is allowed, a usable principle
  covers the question, and no client constraint contradicts it. Otherwise
  it asks. The answer is recorded and joins the model.
- Claude's recommendations in ordinary sessions follow the model and name
  the principle; where none applies, Claude says so and gives its own.

### 4.2 Asking mid-run (park rule)

- The question is parked. Work that doesn't depend on it carries on; work
  that does stops; no new work starts until the owner answers.
- The answer applies at once to that exact question. Matching answers widen
  its scope live through the approval ladder (§4.10); review sessions check
  every promotion.

### 4.3 What agents receive

- A short block (about 300–600 tokens): the three kinds, the park rule, the
  priority order, and how to call the lookup. It covers technical decisions
  in code work and recommendations about code; in sessions that never touch
  code it asks and parks nothing.
- At each decision the agent calls the lookup, which filters locally, then
  searches by similarity through `embedding-lib`, and returns the matching
  principles, tech positions and client constraints, each with its status
  (usable, below the evidence bar, unresolved).

### 4.4 Delivery and enforcement layers

All generated from one source file, a `voice-decision-pipeline` output (§5).

| Layer | Strength | Reaches |
|---|---|---|
| Gating hooks: deny dependency changes (manifest edits, installs), test-framework switches and edits under marked paths unless the decision log has an approved entry | enforced | every session and subagent |
| `SubagentStart` block | advisory | every subagent, plugin and workflow agents included; read-only search and help agents (Explore, `claude-code-guide`) skipped by type; Plan agents and every agent that edits or recommends get it |
| `SessionStart` block | advisory | the main session, every session |

There is no logging gate; the reviewer sends agents back for unlogged
decisions.

Gates:

- Marked paths: a default list (CI and deploy config such as
  `bitbucket-pipelines.yml` and `serverless*.yml`, infrastructure-as-code,
  database migrations, `.env` files), plus a small file at a repo's root that
  adds paths or removes defaults.
- Patterns per stack (manifest files and install commands for JS/TS, Dart,
  Go and PHP; both commit-command patterns in §7) are taken at build time
  from what the repos on this machine use. A test-framework switch is a new
  test dependency in a manifest or a new test config file (`jest.config.*`,
  `vitest.config.*` and similar). The owner reviews the full list before the
  gates go live.
- A gate that times out (30 seconds) blocks the call; every timeout is
  logged.
- A wrong block is overridden through the question the denial parks: "allow
  this one" becomes an asked entry so the retry passes; "this rule is wrong"
  also flags the pattern or path for the next review session. Both are
  logged as false blocks. There is no allow command.

If an agent ignores the `SubagentStart` block, that agent alone moves to a
`PreToolUse` hook on the Agent tool that appends the block to its prompt.
Only one hook may modify Agent input: any later change to agent prompts goes
into that hook, and `decision-runtime`'s install check refuses if
`settings.json` already holds another `PreToolUse` hook matching Agent.

### 4.5 Review points

A reviewer (model-run hook) checks diffs against the decision model and
sends the agent back if it finds a bad or unlogged decision:

| Work | Review point |
|---|---|
| GSD execute runs (including `/gsd:quick`) | after each plan: `PreToolUse` on the executor's `SubagentHandback`; `SubagentStop` for agents that end without one |
| Main session (including `/gsd:fast` and repos without `.planning/`) | end of turn: `Stop`, only if the repo changed since the last review |
| Non-GSD subagents that change code (incl. worktree-isolated and background agents) | `SubagentStop`, if their worktree or the main tree changed since they started |
| Written plans before code | plan review (§4.6) |

- Claude's recommendations in ordinary sessions get no review point. Each
  recommendation, the principle it named and the owner's choice are recorded
  locally, and review sessions show where they diverged.
- All review points share one per-repo record of what has been reviewed
  (last reviewed commit plus working-tree state), keyed per worktree, written
  under a lock, so nothing is checked twice.
- The same reviewer covers decisions made only in code, decisions an agent
  doesn't notice it's making, and GSD executor Rules 1–3.
- How the reviewer runs:
  - A command hook works out the diff against the review record locally,
    looks up the principles touching the changed files, and sends both in
    one `claude -p` call.
  - Haiku 5.5 screens every review; Sonnet 5.5 confirms before anything is
    blocked.
  - Subagents and GSD runs are sent back with the reason; in the main
    session the owner is asked first (fix it, allow this one, or the rule is
    wrong). Nothing is reverted.
  - After 2 blocks on the same problem the reviewer parks a question (diff,
    principle, both attempts) and lets the agent stop.
  - A local pre-filter skips changes that are only whitespace or formatting,
    only comments, only docs other than plan and spec files, or only
    generated files.
  - The end-of-turn review runs in the background with `asyncRewake`: the
    turn ends at once and only a problem wakes Claude. On a timeout the
    review record isn't advanced.
  - Changed plan and spec files (GSD `PLAN.md`, `CONTEXT.md`, `UI-SPEC.md`,
    OpenSpec `proposal.md` and `specs/`, plan-mode plan files) are read as
    decisions and checked like code.
  - The reports of `bm-advisor-researcher`, `bm-framework-selector`,
    `bm-plan-checker`, `code-review-fix` and `bm-ui-auditor` are checked
    against the principles when each finishes.
  - A hook records every file written or edited through Claude's file
    tools, in any folder, and the reviewer gets those changes as well as the
    git diff. A shell-made change outside a git repo is not covered.
  - With a build delivered the reviewer blocks, at trust level 0 too; with
    no build it skips (§5).
  - Each `claude -p` call carries about 46k tokens of Claude Code's own
    setup, which §6's reviewer figures leave out.
- Phase-end audit: when a GSD phase completes, Sonnet 5.5 diffs the whole
  phase against the decision log and sends anything that looks like an
  unlogged decision to the question record. It never blocks. Each find is
  logged as a reviewer miss.

### 4.6 Plan review

One plan reviewer with a small adapter per tool, naming where the tool's
plan text lives and which event marks it final:

- **GSD infrastructure skip:** when `autonomous` skips discuss and writes a
  minimal `CONTEXT.md`, a hook notes the phase; when the executor is about to
  start, the phase's first `PLAN.md` is reviewed against the principles, and
  anything not covered is parked. The same hold applies to any phase where
  discuss didn't run with the owner, including a pre-existing `CONTEXT.md`
  (`has_context`) the owner didn't write; one written through discuss is
  recognised from its discuss session in the transcripts. The file, event
  and signals that mark a skip are taken at build time from the installed GSD
  version and shown to the owner with the gate patterns.
- **Claude Code plan mode:** a `PreToolUse` hook on `ExitPlanMode` (it
  receives `plan` and `planFilePath`) reviews the plan before the owner is
  asked to approve. Decisions with no principle go into the plan as open
  questions, answered as part of approving, each logged as an asked entry.
  After approval, a `PostToolUse` hook logs each decision in the plan as
  "approved in a plan", weak evidence until confirmed in a review session.
- **OpenSpec:** an adapter at `/opsx:apply`, reviewing
  `openspec/changes/<change>/`, added once OpenSpec is in use.
- **grill-me / grill-with-docs:** no gate; they never decide.

`workflow.skip_discuss` stays off.

### 4.7 Questions to the owner

- Each question states the decision, what happens today, each option and
  what it changes, the principles that came close, the work waiting on it,
  where it came from (repo, session name, Remote Control link) and when it
  was parked; no deadline. At trust level 0 the asking agent's
  recommendation and the model's prediction are hidden until the owner
  answers, then shown with whether each matched; from level 1 both appear
  with the question.
- Channels: a push notification (only says a question is waiting) and the
  session itself, answered locally or through Remote Control. Slack is not a
  channel; it can be added later only through a separate bot app with its
  own token, never the connector. Long runs are started in Remote Control
  sessions.
- Every answer is written to one local question record (`questions.jsonl` in
  `question-store`'s state: question, status, answer, channel, time). First
  answer wins; the other channels are told. The owner changes an answer in
  `/questions`: not yet picked up, it replaces the old one; picked up by a
  running session, that session is sent the change; picked up by an ended
  run, it is marked changed after use. The decision log keeps both answers.
- `/questions` lists every question, open and answered, with the answer and
  channel, and puts an open one to the owner as a multiple-choice prompt.
- Waiting work resumes by message: at park time the record keeps the
  session's `CLAUDE_CODE_MESSAGING_SOCKET` and `CLAUDE_CODE_MESSAGING_TOKEN`;
  when the answer is recorded, `question-store` posts it there and an idle
  session starts a new turn. Nothing runs while waiting. If the session has
  closed, `/questions` lists the question as answered with nothing waiting,
  with its session link. Nothing runs `claude -p --resume` on its own.
- `question-store` registers one hook, `SessionStart`: it lists the repo's
  open questions, and answered ones whose session has closed.
- The session that parks a question sends its push.
- Open questions are mirrored to GSD blockers (`gsd_add_blocker`,
  `gsd_resolve_blocker`). When `autonomous`'s `handle_blocker` meets one,
  `decision-runtime`'s GSD adapter puts the question itself to the owner
  there, records the answer, resolves the blocker and takes "Fix and retry".
  The mirroring lives in `decision-runtime`, so `question-store` has no GSD
  dependency. Outside GSD repos the agent holds the dependent step under
  §4.2.

### 4.8 Decision log

- `decision-log.jsonl` in `decision-runtime`'s state, append-only,
  travelling in segments (§5). Its JSON Schema is written at build time and
  reviewed by the owner before use.
- Every decision made alone is logged with the agent and the principle ids
  it relied on, in `decision-runtime`'s log only, never in GSD's `STATE.md`.
- Only an "asked" entry lets a gate through, until the owner lets at-bar
  principles satisfy the gates (§4.12). Anything else is denied and the
  agent parks a question.
- Answers to parked questions are copied in as "asked" entries by
  `decision-runtime` when it reads the answer, citing the question id. A
  changed answer gets a new entry that supersedes the old one. A
  `SessionStart` sweep logs any answered question with no "asked" entry yet.
- Every review is logged: blocks with the reviewer, diff range and reason;
  reviews that found nothing with the diff range and principles checked. The
  owner's verdict is kept with each block (fix it: right; allow this one or
  the rule is wrong: wrong). Blocks in subagents and GSD runs come to the
  next review session. A principle with 2 blocks judged wrong drops back to
  "ask" until approved again.
- Miss rate: each review session shows 10 random reviews that found
  nothing, for the owner to mark whether each should have blocked. These
  marks and the phase-audit finds give a miss rate with a 95% range.

### 4.9 Extracting decisions

- A broad local filter picks candidates (threads weighing options, wording
  like "rather", "instead", "should we", PR comments asking for changes,
  transcript corrections, `[Rule N - Type]` entries in GSD `SUMMARY.md`
  files). All candidates are sent, plus a random 10% of the rest to measure
  what the filter misses, raised in 10% steps until the estimate is clearly
  above or below 95%. Under 95% caught, the filter is widened and measured
  again.
- Rules 1–3 deviation entries are the executor's decisions made alone,
  never the owner's evidence; Rule 4 entries count as the owner's, with the
  answer from the question store.
- Each case records the question, options, choice, reason and outcome.
- Reasons never stated are inferred, tagged "inferred", and count once
  confirmed in a review session.
- Decisions relayed from someone else (a client's or manager's call) are
  tagged with who they came from and kept as constraints for that client or
  project; where the owner agreed, they also count as the owner's.
- Written records are weighted by origin: answers given or overridden one by
  one count as the owner's; recommendations accepted in bulk, and context
  written by infrastructure skips, are weak evidence until confirmed. Origin
  needs the transcript's AskUserQuestion answers, because `CONTEXT.md`
  records only the final answer.
- A "You decide" answer is a delegation: it counts towards no principle;
  what Claude then chose is weak evidence until confirmed.

### 4.10 Output

- Principles, each with dated evidence quotes, what it trades against, and
  when it was last seen.
- A priority order for settling conflicts between principles.
- Tech positions on specific tools and platforms, dated.
- Client constraints, per client or project. A repo's client comes from a
  mapping the pipeline proposes from each picked repo's name and its PRs'
  conversations, confirmed by the owner on the review page and stored with
  the build. A repo with no client, or first seen after the build, gets none.
- Cases and evidence quotes keep any code they quote; rules hold no code.
- **Own principles:** a principles file in the pipeline's state,
  owner-only, never committed. Each entry counts as approved and is usable
  without evidence; it wins over an extracted principle it conflicts with;
  an entry naming an extracted principle's id changes or removes it. It
  reaches other machines inside the encrypted build.
- Evidence bar: at least 3 confirmed cases from at least 2 projects or
  sources before an agent may act on a principle alone. Held-back cases
  count from the next rebuild.
- Approval ladder: an approved answer applies to that question only; after
  a second approval, to that project; at three approvals over at least two
  projects, or five within one, it becomes an approved principle used
  everywhere within the kinds. One approved from a single project is marked
  so, and its first use elsewhere is logged. The ladder climbs live; review
  sessions check and can undo every promotion.
- A comment in a plan cannot set aside an approved principle: the agent
  parks a question naming it, and only the owner's answer lets that case
  through.
- Format: JSON validated by JSON Schema, pretty-printed with sorted keys,
  for the records; JSON Lines for anything append-only. Agents reach it only
  through the lookup, which returns only the fields needed to act (id, rule,
  scope, standing, trades-against, last seen), quotes on request.
  Principles outside the three kinds are kept (`kind: other`): they never
  decide alone, but feed recommendations and questions.

### 4.11 Validation

- Holdout: 10% of confirmed cases, at least 52 in each of the three kinds,
  never more than half of a kind's confirmed cases. A kind held back fewer
  than 52 is reported with its count as not tested to the 85% standard (52
  per kind fails a 95% kind no more than 1 time in 20 and catches an 85% kind
  at least 4 times in 5, exact binomial). `other` principles are graded live
  in shadow, not counted towards the pass.
- Opus 5.5 predicts each held-back case from the question, options and
  context; Fable 5.2 judges. Outcomes: right, wrong, or refusal. Refusals are
  correct (no principle at the bar, outside the kinds, or a client
  constraint conflicts) or unnecessary (a principle at the bar would have
  given the owner's answer). Unnecessary refusals are reported and traced to
  their cause; neither kind counts against the pass.
- The owner grades every held-back case; those grades decide the pass and
  measure how far the judge agrees.
- Machinery tests: every agent type that gets the `SubagentStart` block
  parks a decision outside the three kinds (the test list and the block list
  are one list); each review point sends back a planted bad decision; the
  question record delivers by push and the session, and returns answers by
  message.
- Starting bar (all of): no confident wrong predictions in the owner's
  grades; at least 95% right among predictions made, refusal rate reported
  beside it; the owner's sign-off; every machinery test passing.
- After a confident wrong: the principle behind it is traced and fixed, the
  case joins the evidence, and the model is tested on a fresh holdout.
- Fresh holdouts for later runs: items added since the last build first,
  topped up at random from older items not held back in the last run, spread
  across kinds (audiences and purposes for voice). The candidate model is
  built without the holdout; the tested model is the one released. Each
  run's holdout is listed by item id in the pipeline's state.

### 4.12 Trust levels

- **Level 0, shadow:** the model predicts at every decision, but agents
  still ask the owner. Prediction and recommendation are hidden until the
  owner answers. Starts here after passing.
- **Level 1:** decides alone in the three kinds, on principles that meet the
  evidence bar; everything logged.
- **Level 2 and beyond:** steps the owner chooses, with the level-0 and
  level-1 stats in front of them.
- Up: only when the owner says so. Down: automatic; a confirmed confident
  wrong drops that principle back to "ask" until approved again.
- Live stats (shadow agreement, override rate) come from the decision log.

### 4.13 Upkeep

Answers to parked questions apply live to the exact question; the approval
ladder widens their scope. Everything else (overrides, new transcripts, PRs
and GSD records, conflict verdicts, confirmations) is folded in during
review sessions.

### 4.14 Deferred

- Structural lint rules and orchestration scripts: once the decision model
  exists and the reviewer has a track record.
- Every Bitbucket PR in the picked repos, not only the owner's. How other
  people's decisions are labelled and weighed is open.

---

## 5. Packaging

Packages in one monorepo, `claude-impersonator`, built with
`claude-package-kit`, released as tarballs, each unpacked into
`/mnt/sda/User/Programs/claude-tools/<package>`, whose installer places it
per the kit's layout (`claude-package-kit/skill/reference/layout.md`): a
skill in `~/.claude/skills/<name>/`, a command's state in `~/.claude/<name>/`.
Each gets an INVENTORY.md row when installed. The extracted directory stays
after install, because `update.sh` reruns the installer from it.

| Package | Kind | Depends on |
|---|---|---|
| `embedding-lib` | command | nothing |
| `question-store` | command, with hook registrations | nothing |
| `builds-sync` | skill plus command; registers hooks | nothing; `age` |
| `voice-decision-pipeline` | command | `embedding-lib`; writes the data format |
| `voice-runtime` | skill | `embedding-lib`; reads the data format |
| `decision-runtime` | command, with hook registrations | `embedding-lib`, `question-store`; reads the data format |

- **Kinds:** `hook`, `skill`, `command`. A `command` can register hooks that
  call its own executable.
- **Naming:** the prefix is the subject (`voice`, `decision`, or what a
  shared part handles); the suffix is the kind: `-pipeline` builds the
  models, `-runtime` uses one, `-lib` is a shared library and environment,
  `-store` holds a live record others read and write.
- **Contents:**
  - `voice-decision-pipeline`: extraction (Slack, Bitbucket, transcripts,
    GSD records), anonymising and redaction, the embedding index, labelling,
    writing the guide and principles, the review pages (a server on
    127.0.0.1 run by `voice-decision-pipeline review`, writing each click to
    the state), validation, rebuilds and review sessions. `show bitbucket`
    writes the owner's Bitbucket items as text to the state. A `~/.netrc`
    that Python refuses is reported as that.
  - `voice-runtime`: the guide loader and exemplar search.
  - `decision-runtime`: the `SessionStart`/`SubagentStart` blocks, gates,
    reviewers, plan-review adapters, the lookup and the decision log.
  - `question-store`: park, notify (push, session), collect (first answer
    wins), hand back, show (the session command). Its versioned interface is
    park a question / read its answer.
  - `builds-sync`: the builds repo (below).
- **Building vs using:** only the pipeline builds the models (corpus,
  labels, guide, principles, indexes, the agent block, validation). The
  others use what it built and write evidence records (drafts and approved
  versions, answers, decision-log entries, review results) into their own
  state, which the pipeline reads at the next build. Building means producing
  files.
- **Build order:** the voice model first, then the decision model.
- **Model calls** go through `claude -p` on the logged-in account, with
  structured output against a JSON schema, checked again before use. Tools,
  settings files, MCP servers, slash commands and session files are turned
  off (about 1,100 tokens of overhead a call). A 5-hour or weekly usage limit
  stops a pass cleanly with exit 6; finished batches are kept and the same
  command resumes.
- **`voice publish`** refuses until the label check and the validation run
  have passed. The build format, the `builds-sync` library (`publish_build`,
  `read_live`) and `voice-runtime install-build` are fixed in each package's
  README.
- **Coupling:** shared code lives once in the owning package's library,
  which only defines things. Dependents load it from that package's install
  directory (never `PATH`), check a version constant, and fail their install
  check if it's missing. Each dependent's README says what to install first.
- **`embedding-lib`** owns the Python environment (sentence-transformers,
  CPU PyTorch, `bge-base-en-v1.5`) and an embed library with a version
  constant. It always runs on a Python 3.14 it downloads into its own
  directory (python-build-standalone 3.14.10), never the system Python, so
  every machine shares one set of pinned library versions and an index built
  on one is accepted on the others. Each voice build's manifest records the
  model and version that built its index; a consumer refuses a mismatch
  until the pipeline re-embeds.
- **Data and state:** each package keeps its data in its own state, where
  the kit's layout puts it: `voice-runtime` in
  `~/.claude/skills/voice-runtime/state/`; `decision-runtime`,
  `question-store` and `voice-decision-pipeline` in `~/.claude/<name>/`. No
  path or setting is configured or shared.
  - **Builds on every machine:** the corpus is extracted, anonymised and
    built once, on one machine. Each build is committed to a builds repo, and
    every machine the owner uses installs `voice-runtime` and
    `decision-runtime` from it. No other machine extracts or builds. Nothing
    real may be in a build: the leak check runs on the built files (voice
    guide, exemplars, statistics, principles and their evidence quotes, tech
    positions, client constraints, cases, the agent block) before every
    commit, and a failure stops it.
  - **Builds repo:** a private GitHub repo, separate from this one, named in
    `build-inputs.json` (`builds_repo`). Everything in it is encrypted with
    `age` under one key, except a plaintext `README.md` with no content. The
    pipeline and every machine refuse a push if any other tracked file
    doesn't end in `.age`.
    - Layout: `builds/<build-time>.tar.age`, one per build, and
      `live/<hostname>/<package>/<push-time>.jsonl.age`. Only the pipeline
      writes `builds/`; each machine writes only its own `live/` directory.
    - The embedding index is not in the repo. Each machine embeds the
      exemplars at install, reusing the previous build's rows by a hash of
      each text; a change in `embedding-lib`'s identity re-embeds them all.
    - Each machine holds the key at `~/.config/age/builds.key`, mode 600,
      copied there by hand.
    - Live files that travel: `drafts.jsonl` (`voice-runtime`),
      `decision-log.jsonl` (`decision-runtime`), `questions.jsonl`
      (`question-store`). The reviewed-changes record, gate state and
      question delivery state stay on their machine.
    - Segments: each push stores only the records added since the last
      push, so `questions.jsonl` is append-only and the newest line per
      question id wins. The pipeline joins every machine's segments by push
      time, drops repeated records by id, and applies the struck list.
      History is never rewritten for `forget`.
  - **`builds-sync`** installs a skill directory, an executable in
    `~/.local/bin`, and hooks registered from it. It owns the clone, the key
    path, `age` and every pull, commit and push; the pipeline and the
    runtimes load its library. Its state records the clone's location (asked
    once at first install) and where each live file's last push stopped.
    - Push: a `SessionEnd` hook pushes this machine's new records;
      `builds-sync push` does the same on demand. A lock stops two sessions
      colliding. An offline or killed session loses nothing.
    - Update check: a `SessionStart` hook shows the notice the last check
      left and starts the next check in the background, at most once a day,
      by a day stamp written before the `git fetch`; `builds-sync check
      --force` checks at once.
    - Nothing installs it automatically: `builds-sync install`, or the skill, which
      runs it in the background and watches `/tmp/builds-sync-install.log`.
      `install <build-time>` installs an older build; there is no pinning.
      `builds-sync status` says which build a machine runs.
    - Each install writes a new `builds/<build-time>/` and writes
      `manifest.json` last, so the previous build is used until the new one
      is complete, then deleted.
  - The pipeline writes each build through `builds-sync` and, at the start
    of each build, reads every machine's live segments into the corpus. The
    runtimes never read the pipeline's state and keep working on the last
    build delivered. `decision-runtime` reaches questions only through
    `question-store`'s interface.
  - What must agree across packages is checked when read: the embedding
    model and version, each file's schema version, and principle ids
    (carried across rebuilds by `supersedes`/`superseded_by`).
  - Runtime commands that write state from other repos' sessions get a
    `sandbox.excludedCommands` entry; hooks run outside the Bash sandbox.
  - JSON for every file except the binary embedding indexes. The voice guide
    is JSON entries per audience and purpose, so `voice-runtime` loads only
    the cells a draft needs. The agent block is plain text generated from the
    principles.
  - Manifest: one `manifest.json` per runtime naming the current build and
    each file's schema version, written last. Each runtime checks only the
    files it reads.
  - Layout, by package:
    - `voice-runtime`: `builds/<build-time>/` (`guide.json`,
      `exemplars.json`, `stats.json`, `index/`), `manifest.json`,
      `drafts.jsonl` (live).
    - `decision-runtime`: `builds/<build-time>/` (`principles.json`,
      `priorities.json`, `tech-positions.json`, `client-constraints.json`,
      `cases.json`, `agent-block.txt`), `manifest.json`,
      `decision-log.jsonl`, the reviewed-changes record and gate state
      (live).
    - `question-store`: `questions.jsonl` and delivery state (live).
    - `voice-decision-pipeline`: the corpus, the map, the corpus index,
      labelling output, holdouts and `validation-answers.jsonl`.
    - `embedding-lib`: no data.
  - Uninstall: each package's `pre_uninstall` refuses while it holds live
    files, unless `--keep-state` is given. Reinstalls and updates keep state.
  - Principle record: `id`, `rule`, `kind` (libraries-tooling,
    code-structure, test-approach, other), `scope`, `trades_against`,
    `standing` (below-bar, at-bar, approved, demoted; computed by the
    pipeline, never written by a model), `evidence` (cases, settings),
    `approval` (count, projects, single-project flag, first use elsewhere
    logged), `quotes`, `first_seen`, `last_seen`, `demoted`, `supersedes`,
    `superseded_by`.
  - Model-written JSON is validated against the full schema before it's
    written; refusals and cut-offs are retried.
  - Migration: build files never migrate; the next build writes the new
    version. A live file's schema change ships with a migration step and
    runtimes that read both versions. The migration takes the owning
    package's lock, writes and validates a converted copy, swaps it in, keeps
    the old file as `<name>.v<old>.jsonl` and updates the manifest. A refusal
    names the file, the version found, the versions accepted and the command
    that fixes it.
  - After a refusal (no build delivered yet, an embedding mismatch, or an
    unaccepted schema version) the runtimes carry on safely and say so.
    `decision-runtime`'s lookup returns "nothing covers this", so every
    decision goes to the owner; the gates keep working from the decision log;
    the reviewers skip; the `SessionStart` block shows the refusal in one
    line. `voice-runtime` says before drafting that the voice model is
    unavailable and why, and offers the draft marked as not in the owner's
    voice.
- **Anonymiser** stays inside the pipeline, the only thing that runs it.
- **Releases:** in dependency order (`embedding-lib`, the pipeline,
  `voice-runtime`, `question-store`, `decision-runtime`), each tagged
  `<package>-vX.Y.Z` on its `release/<package>-vX.x` branch. A runtime's
  version says nothing about its model, which is gated by validation and
  trust levels. No pre-releases are written to `versions.txt`.
- **End-to-end tests:** one Docker box for the monorepo: Ubuntu with real
  Claude Code installed and logged in, each package copied from the checkout
  (`tar` piped through `docker exec`) and installed with its `install.sh`;
  made-up fixture data only. Scripts run from the owner's terminal, log to
  `test/docker/results/<time>/run.log`, and tear down what they started.
  Alongside each package's `test/run-tests.sh`, and before §4.11's machinery
  tests.
- Tests use made-up fixtures. Model rebuilds change only the runtimes'
  build directories, never package code. Releases are for code changes only.

## 6. Cost (estimates, input tokens)

Token counts only; not priced. Output tokens are much smaller.

| Building, once | Tokens |
|---|---|
| Labelling Slack messages with context | ~8.5M |
| Second-model blind labelling | ~8.5M |
| Decision extraction | ~2–3M |
| Transcripts and PR comments | ~2–3M |
| Writing the guide and principles | ~2–5M |
| Voice validation (drafts and judge) | ~14M |
| Exemplar-count test (3, 5 and 8) | ~10M |
| Decision validation | ~2M |
| **Total** | **~49–54M** |

| Running, per year | Tokens |
|---|---|
| End-of-turn review | ~25–35M |
| After-each-plan review | ~4–10M |
| `SubagentStop` and plan reviews | small |
| Drafting | small (guide cached) |

Disk: about 1–2 GB for `embedding-lib`'s environment, about 20 MB for the
corpus.

---

## 7. Verified facts this plan rests on

From the Claude Code docs, the GSD plugin files and tests on this machine:

- `SubagentStart` can add context (`additionalContext`), matched by agent
  type, plugin agents included; it can't see the subagent's prompt.
- `SubagentStop` can block with a reason, which becomes the subagent's next
  instruction; `stop_hook_active` guards loops; 8 continuations at most.
- Prompt and agent hook types exist on `Stop`, `SubagentStop` and
  `PreToolUse`, and can block with `{"ok": false, "reason": …}`. The agent
  type is experimental.
- Workflow agents fire `SubagentStart`, `PreToolUse` and `SubagentStop`
  (agent type `workflow-subagent`, or the `agentType` they were launched
  with). GSD plugin agents fire all three (agent type `gsd:bm-executor`).
- A `PreToolUse` hook on `ExitPlanMode` receives the plan text; a deny keeps
  Claude in plan mode, the reason reaches Claude, and the revised plan can be
  resubmitted.
- A `PreToolUse` command, http or mcp_tool hook that times out lets the call
  through unless configured so its failure blocks.
- `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` forces the model of every subagent,
  teammate and workflow agent.
- GSD: `autonomous`'s smart discuss asks the owner to accept or override each
  grey area. `bm-executor` stops for architectural changes (Rule 4, returning
  what was found, the proposed change, why, impact and alternatives) and may
  not run a package install as a Rule 3 auto-fix (a failed install returns a
  `checkpoint:human-verify` with `gate="blocking-human"`). Discuss is skipped
  when a phase already has a `CONTEXT.md` (`has_context`). Code commits use
  `git commit`; docs and sub-repo commits use `bm-sdk query commit…`, so
  gates must match both.
  fire in `autonomous`'s discuss step.
- An infrastructure skip shows "Phase N: Infrastructure phase — skipping
  discuss, writing minimal context." and writes a minimal `CONTEXT.md`.
  `CONTEXT.md` records only the final answer. `autonomous` pauses only for
  grey-area acceptance, blockers and validation requests. Its own audit is
  milestone-level, skipped with `--only` and `--to`. `gate="blocking-human"`
  checkpoints are excluded from auto-approval.
- With `workflow.auto_advance` (default true) or
  `workflow._auto_chain_active`, `checkpoint:human-verify` auto-approves
  except `gate="blocking-human"` and package-legitimacy checks;
  `checkpoint:decision` auto-selects its first option; `checkpoint:human-
  action` still stops.
- No GSD setting narrows `bm-executor`'s Rules 1–3. A project `./CLAUDE.md`
  is the one lever, and `decision-runtime` never writes to work repos'
  `CLAUDE.md` files.
- GSD reads a conformant `.agents/workspace.json` at `SessionStart`;
  `decision-runtime` doesn't write one.
- `anonymise` doesn't change message counts, so `/gsd:profile-user`'s
  message thresholds behave as on raw text, and its sensitive-content
  patterns still match where those words remain.
- claude.ai cloud sessions load none of `~/.claude`; they are not covered.
  Sessions started from claude.ai through Remote Control servers on the
  owner's machines are.

## 8. Still to build

### 8.1 Sources and corpus

- A name that is also an ordinary word is replaced only where it is the
  name, not wherever the word appears. The copies, labels, guide, statistics
  and exemplars are then built again from the fixed copies.

### 8.2 Voice

- The line in `~/.claude/CLAUDE.md` that loads the voice skill; the owner
  approves its wording.
- A test that a drafting subagent loads the skill, and whether
  `/code-review --comment` words its comments in reviewer subagents.
- The §3.8 upkeep: matching edited drafts to sent messages, and review
  sessions.
- The judge review of each validation run (§3.7).
- `voice-runtime`'s first release; `voice build` and `voice publish`.

### 8.3 Decisions

- A test that the `SubagentStart` block's `additionalContext` reaches the
  agent, for GSD plugin agents and workflow agents.
- The `SubagentStart` skip list matches workflow agents launched with
  `agentType`.
- Extraction tells Claude's recommendations apart from the rest of a
  transcript by a marker that holds across the transcript corpus.
- `decision-runtime`'s GSD adapter looks up each auto-selected
  `checkpoint:decision`: a usable principle picking the same option lets it
  proceed, logged; otherwise, and always at trust level 0, it is parked.
- A Rule 4 stop becomes a parked question, pushed and listed in
  `/questions`, its answer logged as an asked entry. The package-legitimacy
  `checkpoint:human-verify` stays in GSD's own flow, its answer logged.
- When OpenSpec is in use: the hook event that catches `/opsx:apply`
  (`UserPromptSubmit` or `UserPromptExpansion`), whether OpenSpec runs its
  own agents, and edits after `/opsx:apply`.
- When grill-with-docs is in use: its reader, and how its records are
  weighted.
- A reminder when a deferred tool (grill-me, grill-with-docs, OpenSpec) is
  installed, so its items here are picked up.

### 8.4 Questions to the owner (`question-store`)

- Built as §4.7 describes.

### 8.5 Packaging and process

- Estimates still to measure: Bitbucket PR and comment volume, commits per
  GSD plan, PRs per repo, and the after-each-plan review figure in §6.
- Running costs not in §6: the 300–600-token block in every session and
  subagent launch, lookup results, gate denial reasons, `PostToolUse` plan
  logging.
- Each install adds its sandbox exclusion with a wildcard (`"rrc *"`); a
  bare entry matches only the bare command.
- The by-hand `/gsd:profile-user` run copies the sample
  (`{temp_dir}/profile-sample.jsonl`) and the agent's `<analysis>` block to
  the pipeline's state before the workflow deletes its temp directory.
- Pipeline rebuilds are run by hand: the review page shows when enough new
  material has built up, with the command, and the owner runs it in their
  own shell; a failing leak check stops it before anything is sent.

## 9. Needs the owner when it runs

1. A Bitbucket token with `read:repository` in `~/.netrc`, mode 600
   (Python's `netrc` refuses any other).
2. Review the first anonymised batches of each source.
3. Check the audience mapping, the label sample and the disagreement sample
   (§3.4); confirm inferred reasons and bulk-accepted records.
4. Grade the blind voice pairs (§3.7).
5. Grade every held-back decision case (§4.11).
6. Decide every old-against-new conflict before an orchestrator gets the
   decision model.
7. Run each package's install from its release tarball; the installer
   writes outside Claude's Bash sandbox.
8. Move the decision model up trust levels.
9. The private builds repo exists, each machine can push to it, and each
   machine holds the `age` key.
