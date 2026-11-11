# Voice and decision models — plan

§7 holds
checked facts, not decisions. Everything undecided is in §8; the order it is
worked through in is §8.0.

Evidence, comparisons, options not used and references are in `APPENDIX.md`
beside this file.

Two models, built from the owner's own writing and decisions:

1. **Voice model** — so Claude can draft Slack messages, PR descriptions, PR
   review comments and Jira comments in the owner's voice. Every draft goes to
   the owner for approval before anything is sent.
2. **Decision model** — so orchestrators and agents can settle some technical
   questions the way the owner would, and ask them about the rest.

The two share only the sources and corpus preparation. Everything else —
uses, analysis, output, loading, validation, upkeep — is planned separately.

---

## 1. Shared: sources

| Source | Used for | Scope |
|---|---|---|
| Slack export (JSON, 2020–2026) | voice and decisions | the owner's messages, after the exclusions below |
| Bitbucket PR descriptions and comments | voice (technical team audience) and code-level decisions (what the owner approves, rejects and asks to be changed) | `oneiota` repos only; hard rule: repos last updated before 2019 are left out; the exact repos are picked when the pipeline is run |
| Claude Code transcripts (`~/.claude/projects/*/*.jsonl`) | technical decisions only — never voice (prompts are written to Claude, not colleagues). Probably the strongest decision source, because corrections there state a decision outright | everything kept from now on |
| GSD written records: decisions in `.planning/STATE.md`, phase `CONTEXT.md` | decisions, weighted by origin (§4.9) | GSD repos: every repo with `.planning/` counts, including those without `.planning/config.json` whose `.planning/` is empty or holds only `codebase/`; their `STATE.md` and `CONTEXT.md` are read once they exist. |
| grill-with-docs ADRs (`docs/adr/`) and `GLOSSARY.md` | read once grill-with-docs is in use | Decisions made in grill sessions reach the model through transcripts |
| `/gsd:profile-user` output | decisions | run on anonymised copies only (§2.3) |

Conversation-level values — conversation ids, names, the struck and kept
lists, audience assignments, and the candidate client names for the
anonymiser — are the pipeline's input, held with real names in
`build-inputs.json` on the owner's machine only.

Left out:

- Jira — dropped as a source. Jira comments still get the voice model as an
  output.
- Email and documents: not sources.
- Anything outside the Slack export folder.
- New Slack data after the export ends: none expected for now. The pipeline
  accepts a later slackdump export through the same local steps if one is ever
  run; the Slack connector route stays open but unused (it would send real
  names to the API before anonymising).

## 2. Shared: corpus preparation

### 2.1 Context kept per item

- **Slack:** each of the owner's messages keeps its thread if threaded; otherwise
  the messages before it in that conversation from the previous 2 hours (up to
  20), and the same after it (up to 20), plus emoji reactions. The "after"
- **Bot messages and channel events**: neither is a
  corpus item. A bot message (build, alert and PR notifications) is kept as
  context when it sits in the thread or window of one of the owner's messages,
  tagged `bot`, never used as voice or as the owner's decision, and anonymised like
  the rest. Channel events (room created, joins, topic and canvas changes)
  are dropped.
- **The owner's reactions on other people's messages**:
  agreement reactions (thumbs-up, plus, tick and OK-hand kinds) make the
  message reacted to, with its context, a corpus item tagged
  `reaction:<name>`. The decision extraction treats it as a possible
  agreement only where the message proposes something; it is never voice.
  Other reactions are kept as context only.
- **Pasted code, logs, links and attachments:** kept and tagged. The voice
  analysis skips them; the decision analysis reads them. Links kept as URLs,
  attachments as file names.
- **Transcripts:** each typed prompt plus the text of Claude's reply before
  it, a one-line summary per tool call (which file, which command),
  AskUserQuestion questions and answers, project name and date. Claude's
  preceding reply is kept because it is usually what the owner was correcting.
  Main-session transcripts only: subagent (sidechain) transcripts are left
  out. Their text is Claude's, and the owner's own words
  and answers are all in the main sessions.
  Transcripts from the owner's other machines are included;
  claude.ai cloud sessions are not. Before a build,
  the owner copies each machine's `~/.claude/projects` here with one `rsync`
  per machine, and the pipeline's `import-transcripts <dir>` reads it
  through the same anonymising and filters. Whether those machines hold
  transcripts is not
  checked.
- **Git commit messages:** not a source. Most are
  short subject lines, and PR descriptions and threads cover the same
  changes for Bitbucket repos.
- **Bitbucket:** each comment with its PR title, description and thread.
  PRs the owner authored, commented on or approved; a
  silent approval counts, as a record that the owner accepted the approach. Every
  PR in the picked repos is to be read as well (§4.14).
  Inline comments get the code under them from the API; the owner adds
  `read:repository` to the Bitbucket token when the pipeline is run.

### 2.2 Storage

- Corpus: in `voice-decision-pipeline`'s own state, `~/.claude/
  voice-decision-pipeline/` (per-package state, §5 Data and state).
  About 20 MB, each message
  stored once. One record per message, one file per source
  (`slack.jsonl`, `transcripts.jsonl`, `bitbucket.jsonl`), context held as
  ids. Fields: `id`, `source`, `conversation`,
  `author` (real id), `audience`, `ts`, `text`, `tags` (code, log, link and
  attachment spans), `context_ids` (thread, or before/after window),
  `reactions`, `source_fields` (per-source object), `schema_version`.
  Readers join on ids to rebuild a context window; `forget` deletes records
  by `author` or `conversation`.
- Embedding indexes (the corpus index and `voice-runtime`'s `index/`): a
  NumPy `.npy` float32 matrix, `ids.json` mapping each row to a record id,
  and `identity.json` holding `embedding-lib`'s `identity()`.
  Search is a dot product over every row; `forget` rewrites the
  matrix without the dropped rows.
- Anonymising map: one append-only `anonymising-map.json`
  Each entry holds a real id, every alias seen, its kind (person,
  client, product), role, pseudonym and origin (`users.json`, a list,
  spaCy, mining). A counter per role means numbers are never reused or
  renumbered. `forget` keeps the person's entry, so mentions of them in
  other people's messages are still replaced and their number never passes
  to someone else. `~/.claude` is outside Claude's Bash sandbox, so the
  pipeline's commands get a `sandbox.excludedCommands` entry, as `rrc *`
  has.
- This repo, `claude-impersonator`, holds the planning documents; its
  checkout also holds `build-inputs.json` (gitignored).
  No corpus data is written there.
- All four packages' state is owner-only: directories
  700, files 600. Each package's scripts set umask 077 before writing; each
  install creates its state directory as 700 and its verify step checks the
  modes.
- No backup. Losing the system disk or `~/.claude`
  loses the live files (decision log, reviewed-changes record, gate state,
  questions, drafts, validation answers, holdouts) and the anonymising map;
  builds and the corpus can be rebuilt from the sources.
- State is kept until the owner deletes it. The pipeline
  has a `forget <person|conversation>` command: it removes their items from
  the corpus and its index and adds them to the struck list, so later
  builds skip them; the next build drops them from every built output and
  anonymised copy.
- Real names are kept in the stored corpus, so it stays readable and
  searchable.
- No data ever goes into a package repo or release.

### 2.3 Privacy: anonymise before anything is sent

- Anything sent to the Anthropic API is anonymised and redacted first, by
  local scripts in `voice-decision-pipeline`, the only package that runs
  them. The mapping stays local, so results can be turned
  back into real names on this machine.
- Anonymising uses lists (every name in `users.json`, Slack user ids and
  @mentions, client names from channel and repo names, email addresses,
  phone numbers, client-domain URLs) **plus spaCy** named-entity tagging for
  names the lists miss. spaCy runs in the pipeline's own venv, built from
  `embedding-lib`'s bundled Python, with spaCy pinned in the pipeline's own
  lock file; `embedding-lib` stays embedding-only and the runtimes never
  install spaCy. The pipeline's verify step fails if `embedding-lib`'s
  Python version changes, until the venv is rebuilt.
  spaCy 3.8 has Python 3.14 wheels (checked at build time);
  `spacy-curated-transformers` is pinned to 0.3.0, the newest 0.x that
  installs on 3.14, which `en_core_web_trf` 3.8.0 needs. The model is
  `en_core_web_trf`, for the highest published
  name-finding score (~0.90 NER F against ~0.85 for the others, not
  measured here); it brings its own CPU PyTorch into the pipeline's venv
  (about 1.2 GB in all) and makes a corpus pass slower.
  spaCy also tags some ordinary words as names and blanks them. Product,
  store and project names that identify a client on their own are found
  by mining the corpus: while building it, the pipeline
  collects every term spaCy tags as an organisation or product, and
  capitalised terms concentrated in one client's channels or repos. The owner
  strikes or keeps each on one local review page before the first review
  batch is sent; kept terms join the replacement list.
- Replacements are stable pseudonyms with a role tag (e.g. `colleague-07`,
  `client-pm-02`), and clients become codes (e.g. `client-03`); each person
  keeps one pseudonym across every source.
- Credentials (AWS, Slack and Bitbucket keys, JWTs, private keys,
  `password=` lines) are pattern-matched and replaced with
  `[REDACTED:<type>]` while building the corpus. Findings are logged by type
  and count, never value.
- The first batches sent are reviewed together with the owner before they go
  (50 anonymised messages each, every replacement highlighted).
  Review continues until the owner says stop. Batches are drawn per
  source (Slack, Bitbucket PRs, transcripts, GSD records; imported
  transcripts count as transcripts), and nothing from a source is sent
  until its own first batch is approved; "stop" applies per source.
- Exemplars loaded into drafting prompts are sent anonymised: the pipeline
  stores a pre-anonymised copy of each exemplar at build time, so
  `voice-runtime` never runs the anonymiser.
- All of the corpus may be sent, anonymised: every
  kept message with its context, 1:1 DMs included, for labelling,
  second-model labelling, extraction and validation, plus the decision
  filter's 10% miss-rate sample, as §4.9 and §6 assume.
- Corpus text reaches the model only through the pipeline's own scripts
  each batch goes out in one call and its result is
  written straight to the pipeline's state, so each item is sent once per
  pass, as §6 assumes. Subagents and Workflows never carry corpus text; at
  most they start the script. The passes run outside any Claude Code
  session, log to a file Claude monitors, stop cleanly at a usage limit and
  resume from the last finished batch; prompts are adjusted between passes,
  not during one.
- Accepted exception: Slack questions and replies go through the Slack
  connector with real names (§4.7).
- Not covered by this rule: reviewer hooks send code diffs
  from the working repo to the API un-anonymised (they aren't corpus data).
- Built outputs are anonymised: the voice guide,
  exemplars, principles, evidence quotes and client constraints are each
  stored twice, with real names and as an anonymised copy, and only the
  anonymised copy is sent.
  Client constraints are matched to a repo locally,
  against the real-name copy, and only the client code is sent.
- `/gsd:profile-user` is not run as shipped (its agent reads raw transcript
  samples). Its steps are run by hand: run the sampler, anonymise the sample,
  give the anonymised file to `bm-user-profiler`, keep the output in the
  pipeline's state, and answer "neither" to writing it into a CLAUDE.md. GSD's
  plugin files are not edited.

### 2.4 Time

- No cut-off for Slack or transcripts. Bitbucket keeps its own rule (§1).
- When an older and a newer position disagree, both are kept and marked
  unresolved. Once the work is finished, every such conflict is listed for
  the owner to decide, and no orchestrator gets the decision model until they have.

---

## 3. Voice plan

### 3.1 Uses

Slack messages, PR descriptions, PR review comments, Jira comments. Jira
comments keep their structure from `~/.claude/reference/jira-comments.md`;
how that file's own wording rules (e.g. no second person, shorter) sit
against the voice model is open (§8.2). Every draft goes to the owner for
approval before anything is sent.

Slack drafts go out through the Slack connector, which can draft and send
messages. Sending still needs the owner's
approval of the exact text.

### 3.2 Audiences

| Audience | Conversations |
|---|---|
| Clients | client channels |
| Project team | internal project channels |
| Technical team | technical channels, all Bitbucket PR content |
| Senior / management | senior and management channels, group DMs with the same people |
| 1:1 colleagues | one-to-one DMs |

Each conversation is assigned by its name and members; the owner checks the
mapping. Any other internal channel not covered goes to the project team
(because those channels are less technical). Group DMs not
made up of the senior/management people get no rule: the owner assigns each on the mapping page,
and a group DM new in a later export comes up there the same way.
A DM with a client-side contact takes the Clients audience;
the owner's DM
with themselves (notes to self), left out of voice and kept for decisions.

### 3.3 Purposes

Each message can carry several purposes, listed in the order they appear:
push back / disagree; decline; ask / request; chase / nudge; status / update;
explain / instruct; approve / agree; own a mistake / apologise; thank /
praise; escalate; small talk / humour. Anything else is "other". The guide
also records how purposes are combined (e.g. news before the objection). A
message counts in every audience-and-purpose cell it carries, so thin cells
(clients especially) gain examples; label checks cover every label on a
sampled message.
All 11 purposes are kept.

Why purposes: a refusal is written
differently from a request, even to the same person. Labels
let exemplars match what a draft has to do, and let the guide state rules
per purpose (e.g. pushing back on a client against pushing back on a
developer).

### 3.4 Analysis and checking

- Local statistics (no API): length, capitalisation, punctuation, openings,
  sign-offs, emoji, spelling, common words and phrases.
- Audience comes from the message's conversation (the §3.2 mapping, worked
  out locally, checked by the owner).
  A model labels purposes on
  anonymised messages.
- Checking, in parallel: the owner checks a sample of 120 labelled messages
  spread across audiences and purposes (more whenever the owner wants), and a second
  model labels all ~17k messages blind (as the cost step
  priced it, §6). Over 5% wrong in the owner's sample,
  the labelling prompt is changed and rerun, and a fresh sample is
  checked.
- Second-model disagreements: the
  disagreement rate per purpose is measured across all ~17k and shows where
  the labelling prompt is weak; those purposes get the prompt fixed and are
  relabelled. A fixed sample of about 60 disagreements comes to the owner to grade
  (more whenever they want). Every disagreement is recorded, with both models'
  labels, so the owner can review all of them by hand if they want to.

### 3.5 Output

- A voice guide, split by audience and purpose.
- A measured "never say" list: phrases, words and habits common in generic
  business writing that the owner uses rarely or never (e.g. "Hope this helps",
  exclamation marks to clients), each with the owner's count;
  built locally, no API.
- Exemplars drawn from the whole labelled corpus, minus messages of 3 words
  or fewer and messages at least 50% code
  or logs by characters, counting fenced blocks and unfenced log or
  stack-trace lines. Dropped messages still count in
  the measured statistics (never-say list, length per audience). The
  thresholds are config values; changing them re-runs exemplar selection
  only.
- Exemplar choice uses both: labels narrow the pool to the right audience and
  purposes, then similarity search picks the closest few. How many is set by
  validation: the model judge scores held-back drafts made with 3, 5 and 8
  exemplars, and the best-scoring count is used.
  Similarity uses `BAAI/bge-base-en-v1.5`, run locally on the CPU
  (sentence-transformers, CPU PyTorch), so nothing is sent for the search.
  Messages are embedded with a short slice of context (the message plus the
  message it answers),
  within the model's 512-token limit.
- Guide plus exemplars, not either alone: rules alone give flatter drafts;
  examples alone carry over phrasing tied to old clients and people.
- For drafts to other people, the owner's voice wins over the CLAUDE.md writing
  rules. The CLAUDE.md rules keep governing everything Claude writes to
  the owner. So, for example, the CLAUDE.md ban on apologies does not apply to
  an outward draft where the owner would apologise.

### 3.6 Loading

A skill holds the guide and calls the exemplar search — a local script that
takes audience, purposes and a description of the situation and returns the
closest messages (the count set in §3.5), anonymised (as §2.3 assumes; open,
§8.2). A line in `~/.claude/CLAUDE.md` says to load it before any draft for
other people, the way `jira-comments.md` is loaded now; the line is there
because a skill alone loads only when its description matches, which misses
some drafts. The skill serves the main session and subagents alike: a subagent
with the Skill tool sees the same skill list and loads it when it drafts, so
nothing is added to subagent prompts. Whether the
CLAUDE.md line reaches subagents is not checked; a test that a drafting
subagent loads the skill is open (§8.2).

### 3.7 Validation

- 10% of messages are held back from the exemplar pool;
  later runs draw a fresh holdout (§4.11). For each, a draft is written from
  its context, audience and purposes only.
- In parallel: the owner sees 60 blind pairs (their real message and the draft,
  shuffled), 12 per audience across the five audiences, covering as many of
  the 11 purposes as each audience's held-back messages allow. For
  each pair the owner answers "A is mine", "B is mine" or "can't tell", and grades
  the draft 1–5 for "would send as is". The owner can review more at any time (the
  review page saves progress between sittings;
  The progress file
  holds pair ids and answers only, the key staying in the pipeline's
  state; how it saves depends on where the page runs, §8.2). A
  model judge compares every draft with the real message and scores it.
  The owner's graded pairs also show where the judge disagrees with them, which
  is how the judge's scores on the other ~1,700 drafts are trusted. Whether
  the owner also reviews the judge's worst-scored
  drafts and a random few, on top of the pairs, is open
  (§8.2).
- Pass:
  - Blind test: right picks minus wrong picks no more than 10% of pairs (6
    of 60); "can't tell" counts as neither. With drafts that can't be told
    apart, every pick is a coin toss, so a perfect model passes about 4 runs
    in 5. (A bar above chance, 50%, would mean a perfect model almost never
    passes.)
  - Grades: at least 80% of drafts at 4 or higher, and none at 1.
  - The pass is overall. Results are reported per audience; an audience
    where right picks beat wrong picks by 3 or more gets more pairs from
    that audience before the result stands.
- Tracking and report: every answer is stored with the pair, its
  audience and purposes, the answer, the grade and the time, across sittings
  and validation runs. After the test the page shows the counts (right,
  wrong, can't tell; overall, per audience, per purpose), how often the owner
  spots drafts as a best estimate with a 95% range, the confidence that the
  pass holds (worked out from their answers, not the model's opinion of
  itself), and the pairs the owner got right, side by side.
- Every check in this plan can be run on more items whenever the owner wants;
  each bar is a rate, so it still holds.

### 3.8 Upkeep

- The skill saves each draft and the version the owner approved, and keeps them.
- Regular review sessions with the owner feed them back in.
- Approved versions do not join the exemplar pool on their own; they go in
  only through the review sessions.

---

## 4. Decision plan

### 4.1 What may be decided alone

- Orchestrators and agents may decide alone on: **libraries and tooling,
  code structure, test approach.** Everything else — scope cuts included —
  goes to the owner.
- What the three kinds mean: libraries
  and tooling — which package, framework or tool to use, where the model has
  the owner's positions; code structure — where code lives, naming, patterns,
  how modules split; test approach — what to test, at what level, with which
  tools. Small scope cuts (excluded): dropping or deferring a minor piece
  of a phase to finish the rest.
- An agent decides alone only if the kind is allowed, a usable principle
  covers the question, and no client constraint contradicts it. Otherwise it
  asks.
- Within those three kinds, if nothing in the model covers the question, ask
  the owner. The answer is recorded and joins the model.
  The reason for asking:
  a confident wrong guess costs more than a question.
- Claude's recommendations in ordinary sessions follow the model and name the
  principle; where none applies, Claude says so and gives its own. Why: a
  recommendation that follows the owner's reasoning saves a round of correction.

### 4.2 Asking mid-run (park rule)

- The question is parked. Current work that doesn't depend on it carries on;
  current work that does depend on it stops; no new work starts until the owner
  answers.
- The owner's answer applies at once to that exact question, so it isn't asked
  again. Matching answers widen its scope live through the approval ladder
  (§4.10); review sessions check every promotion.

### 4.3 What agents receive

A short block (about 300–600 tokens): the three kinds that may be decided
alone, the park rule, the priority order, and how to call the lookup script.
At each decision the agent calls the lookup, which returns the matching
principles, tech positions and client constraints, each with its status
(usable, below the evidence bar, unresolved).

### 4.4 Delivery and enforcement layers

All generated from one source file, so each agent gets one copy. That file
is a `voice-decision-pipeline` output (§5).

| Layer | Strength | Reaches |
|---|---|---|
| Gating hooks: deny dependency changes (manifest edits, installs), test-framework switches and edits under marked paths unless the decision log has an approved entry | enforced | every session and subagent |
| Logging gate: a `SubagentStop` and `Stop` hook refuses to let an agent finish while it has decisions it hasn't logged. **Ambiguous** — see §8.3 | enforced (that it records, not that it decided well) | every session and subagent |
| `SubagentStart` block | advisory | every subagent, plugin and workflow agents included (agents that never decide can be skipped by type; which ones, Explore included, is open — §8.3). Observed firing for workflow agents and for a GSD plugin agent (`gsd:bm-executor`; saved hook log, APPENDIX D.2). That the block's context reaches the agent is not tested for either — §8.3 |
| `SessionStart` block (instead of a CLAUDE.md section, so subagents don't get it twice) | advisory | the main session, every session (not just GSD repos, because Claude's recommendations in ordinary sessions follow the model — §4.1) |

Fallback: if tests show a particular agent ignoring the `SubagentStart`
block, that agent alone moves to a `PreToolUse` hook on the Agent tool that
appends the block to its prompt.
Only one hook may
ever modify Agent input: any
later need to change agent prompts is added to that hook, and
`decision-runtime`'s install check refuses if `settings.json` already holds
another `PreToolUse` hook matching Agent.

Criteria for choosing the layers: enforcement first, then little
upkeep, then as little overlap between layers as possible.

Not used: overriding GSD's agents with copies in `~/.claude/agents/` (heavy
upkeep, drifts with every GSD update); a CLAUDE.md section (weakest, costs
context in every session).

### 4.5 Review points

A reviewer (model-run hook) checks diffs against the decision model and sends
the agent back if it finds a bad or unlogged decision:

| Work | Review point |
|---|---|
| GSD execute runs (including `/gsd:quick`) | after each plan: `SubagentStop` on `gsd:bm-executor` |
| Main session (including `/gsd:fast` and repos without `.planning/`) | end of turn: `Stop`, only if the repo changed since the last review |
| Non-GSD subagents that change code (incl. worktree-isolated and background agents) | `SubagentStop`, if their worktree or the main tree changed since they started |
| Written plans before code | plan review, one reviewer with an adapter per tool (§4.6) |

Claude's recommendations in ordinary sessions
in scope) get no review point: they are already
handled, because they cite the principle (§4.1) and the owner chooses. For
they are logged and compared later: each recommendation, the
principle it named and the owner's choice are recorded locally, and review
sessions show where they diverged. How a recommendation
is identified is not set: when the build reaches the decision model, every
transcript available then is searched for a dependable marker of one
(AskUserQuestion's "(Recommended)" label is reliable for that tool; prose
recommendations have no fixed marker). A live check before the owner sees a
recommendation can be reconsidered once that review is done.

- All review points share one per-repo record of what has been reviewed (last
  reviewed commit plus working-tree state), so nothing is checked twice —
  otherwise an `execute-phase` turn would re-review commits the
  after-each-plan check already passed, and a subagent's changes could be
  checked by both `SubagentStop` and the end-of-turn check. Writes take a
  lock, and the record is keyed per worktree, since each worktree has its own
  working tree.
  seconds on every commit), reviewing only at phase end or PR (too much
  rework), reviewing before each GSD wave (would duplicate the after-each-plan
  review).
- The same reviewer covers decisions made only in code, decisions an agent
  doesn't notice it's making, and GSD executor Rules 1–3 (auto-fix bugs, add
  missing critical functionality, fix blockers).
- What stays unprevented: a judgement call made in text inside a GSD step
  that the reviewer misses. The owner's review sessions catch it after the fact,
  as would a phase-end audit if one is built (§8.3).

### 4.6 Plan review

Why: while a plan is being written nothing is edited, so
the end-of-turn review has no diff and the plan's choices go unchecked until
they're built.
Other tools rely on the end-of-turn review after code is written.

One plan reviewer with a small adapter per tool, naming where the tool's plan
text lives and which event marks it final. The first adapters are the GSD
infrastructure skip and `ExitPlanMode`; each new tool costs one adapter

- **GSD infrastructure skip:** `autonomous` skips discuss for phases it judges
  pure infrastructure and writes a minimal `CONTEXT.md`. A hook detects that
  minimal `CONTEXT.md` (which event, how it holds the run, and what it
  reviews at that point: §8.3) and holds the run until the planner's
  approach has been looked up; anything not covered is parked.
- **Claude Code plan mode:** a `PreToolUse` hook on `ExitPlanMode` (it
  receives `plan` and `planFilePath`) reviews the plan before the owner is asked
  to approve. Planning research runs in the built-in Plan and Explore agents:
  they skip CLAUDE.md, get the `SubagentStart` block unless their type is
  skipped (Explore may be — §8.3), and never trigger `SubagentStop` review
  (no edits). Open (§8.3): a
  `PostToolUse` hook logging the approved plan's decisions as the owner's, and
  putting uncovered decisions into the plan as open questions instead of
  `question-store`.
- **OpenSpec:** an adapter at `/opsx:apply`, reviewing
  `openspec/changes/<change>/` (`proposal.md`, `design.md`, `tasks.md`,
  `specs/`), added when the owner starts using it.
- **grill-me / grill-with-docs:** no gate needed — they never decide
  (revisit when either is
  installed). Their recommended answers are shaped by the `SessionStart`
  block. Their fact-finding subagents (the skill says only "dispatch a
  sub-agent with a fresh context window";
  that they don't edit is inferred) get the `SubagentStart` block unless their type is skipped
  (§8.3); if they don't edit, `SubagentStop` review never fires. Neither is
  installed.

`workflow.skip_discuss` stays off.

### 4.7 Questions to the owner

- Each question states the decision, what happens today, each option and
  what it changes, the principles that came close, and the work waiting on
  it. At trust level 0 the asking agent's recommendation and the model's
  prediction are both hidden until the owner answers, then shown with whether
  each matched; from level 1 both appear with the question.
- Channels: push notification (only tells the owner a question is waiting), the
  session itself (locally or through Remote Control), and a Slack DM to the owner
  with real names. Questions and replies go through the Slack connector, so
  their text reaches the API with real names — an accepted exception to §2.3.
  The reason: it's a DM to the owner in the company Slack, which already
  holds this material, and anonymised questions would be hard to answer from
  a phone.
- Every answer, from any channel, is written back to one local question
  record (`questions.jsonl` in `question-store`'s state, holding each
  question, its status, the answer, the channel it came from and when); first
  answer wins and the other channels are told (Slack gets a thread reply
  saying where it was answered.
  A later, different answer is not applied; the owner is told it was
  already answered.
- One session command lists every question, open and answered, with the
  answer and the channel it came from.
- Open questions are mirrored to GSD blockers (`gsd_add_blocker`; resolved
  with `gsd_resolve_blocker`), so questions survive a restart and
  `autonomous`'s `handle_blocker` step stops at them before the next phase.
  That step offers retry, skip or stop rather than waiting for the answer;
  with `--interactive`, discuss for the next phase may already be running.
  How the park rule maps onto both is open (§8.3).

### 4.8 Decision log

- Every decision made alone is logged with the agent and the principle ids it
  relied on.
- Answers to parked questions are copied in as entries marked "asked". A
  changed answer gets a new entry that supersedes the old one, never an edit.
- `decision-runtime` writes the "asked" entry when it reads the answer to
  resume waiting work, citing the question id; `question-store` knows nothing
  of the log, so the dependency stays one-way. One log then feeds review
  sessions, rebuilds and trust-level stats.
- A `SessionStart` sweep in `decision-runtime` logs any answered question
  that has no "asked" entry yet (an answer nobody resumed on because the
  parking run ended). Local, no tokens. Questions from other tools that
  aren't decisions under the model stay out of the log.
- `decision-runtime` also logs every review block, with the reviewer, the
  diff range and its reason; the pipeline reads them at the next build,
  false blocks included.
  the sweep, logging review blocks) follows the points above.

### 4.9 Extracting decisions

- A broad local filter (so that fewer decisions are missed)
  picks candidates (threads weighing options, wording
  like "rather", "instead", "should we", PR comments asking for changes,
  transcript corrections). `[Rule N - Type]`
  deviation entries in GSD `SUMMARY.md` files are another candidate. All
  candidates are sent, plus a random 10% of the rest to measure what the
  filter misses; the sample is raised in 10% steps until the estimate is
  clearly above or below 95%. The filter is widened if it catches under 95% of
  decisions (decisions found in the sample, scaled up, against those found
  among candidates), then rerun and measured again.
- Each case records the question, options, choice, reason and outcome.
- Reasons the owner never stated are inferred, tagged "inferred", and count only
  once the owner confirms them in a review session.
- Decisions the owner relayed (a client's or manager's call) are tagged with who
  they came from and kept as constraints for that client or project. Where the owner
  said they agreed, they also count as the owner's.
- Written records are weighted by origin: answers the owner overrode or gave one
  by one count as the owner's; recommendations accepted in bulk, and context written
  by infrastructure skips, are weak evidence until the owner confirms them.

### 4.10 Output

- Principles, each with dated evidence quotes, what it trades against, and
  when it was last seen — last-seen date because a position from, say, 2021
  may no longer hold.
- Priority order for settling conflicts between principles (e.g. speed
  against correctness, build against buy, a client's request against
  maintainability).
- Tech positions on specific tools and platforms (for example:
  Flutter), dated.
- Client constraints, per client or project.
- Examples of the contents: principle "prefer
  the platform's own service over a third-party one"; priority order
  a principle weighing maintainability against delivery speed, except for client-facing
  deadlines"; tech positions on named platforms and services. Each
  part is built from the confirmed decision cases. Examples only, not
  positions the owner has stated.
- Evidence bar ("3+ cases, 2+ settings"): a principle needs at least 3
  confirmed cases from at least 2 different projects or sources before an
  agent may act on it alone. Held-back cases don't count until the next
  rebuild.
- Approval ladder: an answer the owner approves once applies to
  that question only, and after a second approval to that project; it becomes
  an approved principle at three approvals spread over at least two projects,
  or five within a single project, and is then used everywhere within the
  kinds. One approved from a single project is marked so, and its first use
  elsewhere is logged for the next review session. The ladder climbs live as
  answers arrive; review sessions check every promotion and can undo it.
- Whether a comment in a plan can set aside an approved principle is open
  (§8.3).
- Format: JSON validated by JSON Schema — plain JSON,
  pretty-printed with sorted keys, for the records (principles, priority
  order, tech positions, client constraints), and JSON Lines for anything
  append-only. Agents reach it only through the lookup, which filters
  locally and returns only the fields needed to act (id, rule, scope,
  standing, trades-against, last seen), with quotes only on request.
  Principles outside the three kinds are kept (`kind: other`): they never
  decide alone, but feed recommendations and the "principles that came
  close" in questions. Schema, layout and migration: §5, Data and state.

### 4.11 Validation

- Holdout: 10% of confirmed cases, and at least
  52 in each of the three kinds, but never more than half of a kind's
  confirmed cases.
  A kind held back fewer than 52 is reported with its real count
  as not tested to the 85% standard. 52 per kind is what it takes to tell a
  kind at 95% from one at 85%: a 95% kind is wrongly failed no more than 1
  time in 20, an 85% kind caught at least 4 times in 5 (exact binomial; 27
  per kind for 80%, 169 for 90%). `other` principles get no holdout floor:
  they are graded live in shadow and reported, not counted towards the pass.
- Each held-back case is predicted from the question, options and context
  alone. Outcomes: right, wrong, or refusal. Refusals are split:
  correct (no principle at the bar, outside the kinds, or a client
  constraint conflicts) and unnecessary (a principle at the bar covered it
  and would have given the owner's answer). Unnecessary refusals are reported
  and traced to their cause (lookup miss, principle worded too narrowly);
  neither kind counts against the pass.
  Why refusals don't count against the model:
  a confident wrong prediction is the failure that
  matters; a refusal is safe, because the question just reaches the owner.
- Grading in parallel: a model judge scores every prediction against the owner's
  real choice and stated reason; the owner grades every held-back case,
  so the owner's grades decide the pass and measure how far the judge agrees with
  the owner.
- Machinery tests: every agent type that gets the `SubagentStart` block
  parks a decision outside the three kinds — the test list and the block
  list are one list, and which types are skipped is open (§8.3); each review
  point sends back a planted bad decision; the question record delivers to all
  three channels and returns answers.
- Starting bar (all of): no confident wrong predictions in the owner's
  grades; at least 95% right among predictions made, refusals excluded,
  with the refusal rate reported next to it; the owner's sign-off; every
  machinery test passing.
- After a confident wrong: the principle behind it is traced and
  fixed, the failed case joins the evidence, and the model is tested on a
  fresh holdout, not the same sample.
- Fresh holdouts for later runs: items added since the last build
  first, topped up at random from older items not held back in the last
  run, spread across kinds (audiences and purposes for voice). The
  candidate model is built without that holdout; the tested model is the
  one released, and the holdout rejoins the evidence at the next rebuild.
  Each run's holdout is listed by item id in `holdouts.jsonl` in the
  pipeline's state (§5).

### 4.12 Trust levels

- **Level 0 — shadow:** the model predicts at every decision, but
  orchestrators still ask the owner. The prediction, and the asking agent's
  recommendation, are hidden until they answer, then shown with whether each
  matched. Starts here after passing.
- **Level 1:** decides alone in the three kinds, on principles that meet the
  evidence bar; everything logged.
- **Level 2 and beyond:** steps the owner chooses when they move the model past
  level 1, with the level-0 and level-1 stats in front of the owner; not decided
  now. Examples: add a kind (build
  and CI configuration, error handling and logging, API shape within one
  service; small scope cuts excluded), which brings
  the 52-case floor and the 95% bar for it; lower the evidence bar (e.g. 2
  cases in 1 setting); widen approval scope faster; decide and tell, for
  easily undone decisions; decide unless the owner objects within a set time;
  let at-bar principles satisfy the gates; sampled reviews for principles
  with no overrides.
- Up: only when the owner says so, judged on shadow agreement and how often the owner
  overrides logged decisions. Down: automatic — a confirmed confident wrong
  drops that principle back to "ask" until the owner approves it again; the rest of
  the model stays at its level.
- In shadow, each answer the owner gives is a live grade. The live stats (share
  of shadow predictions agreed with, override rate in review) come from the
  decision log, where answers are copied in as "asked" entries (§4.8).
  This follows from the one-way log design, since `question-store` knows nothing of
  decisions or overrides.

### 4.13 Upkeep

Answers to parked questions apply live to the exact question. Everything else
— overrides, new transcripts, PRs and GSD records, conflict verdicts,
confirmations — is folded in during regular review sessions. Why: the same
question often recurs in the next phase or repo. A live answer covers that
exact question; the approval ladder (§4.10) widens its scope live as
matching answers arrive, and review sessions check every promotion and can
undo it.

### 4.14 Deferred

Structural lint rules and the owner's own orchestration scripts: revisit once the
decision model exists (which principles are lintable) and the reviewer has a
track record (where it misses).

Every Bitbucket PR in the picked repos, not only the owner's, is
to be read eventually, so that decisions from repos the owner took no part in
are extracted too. Open: how those decisions, which are other
people's, are labelled and weighed against the owner's own principles.

---

## 5. Packaging

Five packages, all in one new monorepo, `claude-impersonator`,
built
with `claude-package-kit` in ordinary sessions, without GSD
released as tarballs, each unpacked into
`/mnt/sda/User/Programs/claude-tools/<package>`, whose installer places it per
the kit's layout (`claude-package-kit/skill/reference/layout.md`): a skill in
`~/.claude/skills/<name>/`, a command's state in `~/.claude/<name>/`. Each
gets an INVENTORY.md row when installed. Each extracted tarball directory
under `claude-tools/<package>` must stay after install, because the package's
`update.sh` re-runs the installer from it (as with claude-guard-hooks).

| Package | Kind | Depends on |
|---|---|---|
| `embedding-lib` | command | nothing |
| `question-store` | command, with hook registrations | nothing |
| `voice-decision-pipeline` | command | `embedding-lib`; writes the data format |
| `voice-runtime` | skill | `embedding-lib`; reads the data format |
| `decision-runtime` | command, with hook registrations | `embedding-lib` (only if the lookup uses similarity search, §8.3), `question-store`; reads the data format |

Kinds: the kit has three kinds — `hook`, `skill`,
`command` — and a package is one of them. The `command` kind can register
hooks that call its own executable, as `claude-notify` does.
`decision-runtime` is a command because agents call its lookup and its hooks
fire on several events.

- **Naming:** the prefix is the subject (`voice`, `decision`, or what a
  shared part handles) and the suffix is the kind of thing — `-pipeline`
  builds the models, `-runtime` uses a model, `-lib` is a shared library and
  environment others load, `-store` holds a live record others read and
  write. The suffix names what the package does, with the
  voice/decision prefixes kept.
- **Contents:** `voice-decision-pipeline` — extraction (Slack, Bitbucket,
  transcripts, GSD records), anonymising and redaction, building the
  embedding index, labelling runs, writing the guide and principles, the
  review pages, validation, rebuilds and the regular review sessions.
  `voice-runtime` — the guide loader and exemplar search. `decision-runtime`
  — the `SessionStart`/`SubagentStart` blocks, gates, reviewers, plan-review
  adapters, the lookup and the decision log. `question-store` — park
  (record a question; the agent carries on with independent work), notify
  (push, session, Slack DM), collect (every channel's answer written back to
  one record; first answer wins, the others are told), hand back (waiting
  work reads the answer), show (the session command), mirror (open
  questions as GSD blockers; where mirroring lives is open, §8.4). This
- **Building vs using:** only `voice-decision-pipeline` builds the models
  (corpus, labels, guide, principles, indexes, the short agent block of
  §4.3, review steps, validation, rebuilds). The others use what it built
  and write evidence records (drafts and approved versions, answers,
  decision-log entries and every review block) into their own state, which
  the pipeline reads at the next build. Nothing is trained
  in the machine-learning sense; building means producing files.
- **Build order:** the voice model is built first, then the decision model.
  The reason: the decision model's main source, Claude
  Code transcripts, keeps growing, so a later build has more data, and
  the voice model can start from the Slack export already on disk. The
  voice model's Bitbucket PR part still needs `read:repository` on the
  token (§9).
- **When the build starts**: each stage of §8.0 is built
  once its own questions are answered — the monorepo scaffold and
  `embedding-lib` after Stage 0, the corpus extraction after Stage 1, the
  voice model after Stage 2, `question-store` after Stage 3, the decision
  model after Stage 4.
  `voice-decision-pipeline`, the corpus extraction (Stage 1).
  The pipeline
  reads all four sources, redacts credentials, writes the anonymised copies
  and mining candidates, serves the review page, draws per-source batches,
  and has `forget` and the corpus index; nothing in it sends anything.
  Design choices in the build:
  - The Stage 1 review page (mining candidates and batches) is a small
    server on 127.0.0.1 run by `voice-decision-pipeline review`, writing
    each click to the pipeline's state. Where the voice review pages run
    is open (§8).
  - The owner's own pseudonym is `self-01`. A person is `client-contact` when
    outside the owner's Slack team and in no internal conversation, otherwise
    `colleague`; a name only spaCy finds becomes `person-NN`.
  - The anonymised copies leave out full paths, working directories and
    repo slugs, keeping only their last part, anonymised; record ids are
    hashed.
  - The corpus index holds the owner's Slack and Bitbucket voice items only.
  - A workspace's custom agreement emoji are listed in the inputs
    (`agreement_reactions_extra`), not in the package.
- **`question-store`** is separate so other hooks, GSD blockers and future
  tools can ask the owner without depending on `decision-runtime`; its versioned
  interface is park a question / read its answer.
- **Coupling, following the rrc/rrcd pattern:** shared code lives once in the
  owning package's library, which only defines things; dependents load it from
  that package's install directory (never `PATH`), check a version constant,
  and their install check fails if it's missing; each dependent's README says
  what has to be installed first. (Following rrc/rrcd; loading from the
  install directory with a version check.)
- **`embedding-lib`** owns the Python environment (sentence-transformers, CPU
  PyTorch, `bge-base-en-v1.5`) and an embed library with a version constant.
  The environment always runs on a Python 3.14 that `embedding-lib`
  downloads into its own directory (python-build-standalone 3.14.10), on
  every machine, never the system Python. Machines it runs on
  need not share a system Python version.
  One bundled Python lets every machine share one set of
  pinned library versions, so an index built on one is accepted on the others.
  Each voice build's manifest records which model and version built its index;
  a consumer refuses a mismatch until the pipeline re-embeds.
- **Data and state**
  There is no shared data directory. Each package keeps its data in
  its own state, where the kit's layout puts it from the package's name
  (`claude-package-kit/skill/reference/layout.md`): `voice-runtime` (a skill)
  in `~/.claude/skills/voice-runtime/state/`; `decision-runtime`,
  `question-store` and `voice-decision-pipeline` (commands) in
  `~/.claude/<name>/`. No path or setting is configured or shared.
  - The pipeline writes each build into the runtimes' state and, at the
    start of each build, reads their live files and `question-store`'s
    questions into the corpus. The runtimes never read the pipeline's
    state, so the pipeline can stay uninstalled; each runtime keeps
    working on the last build delivered to it. `decision-runtime` reaches
    questions only through `question-store`'s park/read interface.
  - What must agree across packages is checked when read, not configured:
    the embedding model and version in the voice build's manifest, each
    file's schema version, and principle ids (carried across rebuilds by
    `supersedes`/`superseded_by`).
  - Runtime commands that write state from other repos' sessions get a
    `sandbox.excludedCommands` entry, as `rrc *` has; hooks run outside the
    Bash sandbox.
  - JSON for every file except the binary embedding indexes. The voice guide
    is JSON entries per audience and purpose, with the rule text as strings,
    so `voice-runtime` loads only the cells a draft needs. The agent block
    (§4.3) is generated from the principles at build time as plain text.
  - Manifest: in each runtime's state, one `manifest.json` naming the current
    build and each file's own schema version, written last. Each rebuild goes
    into a new `builds/<build-time>/` directory, and the previous build stays
    until the next succeeds, so a rebuild that dies halfway is never read.
    Each runtime checks only the files it reads, so a voice-only format change
    doesn't make `decision-runtime` refuse.
  - Layout, by package:
    - `voice-runtime`: `builds/<build-time>/` (`guide.json`,
      `exemplars.json`, `stats.json`, `index/`), `manifest.json`, and
      `drafts.jsonl` (live).
    - `decision-runtime`: `builds/<build-time>/` (`principles.json`,
      `priorities.json`, `tech-positions.json`, `client-constraints.json`,
      `cases.json`, `agent-block.txt`), `manifest.json`, and
      `decision-log.jsonl`, the reviewed-changes record and gate state
      (live).
    - `question-store`: `questions.jsonl` and delivery state (live).
    - `voice-decision-pipeline`: the corpus, the anonymising map, the
      corpus embedding index, labelling output, `holdouts.jsonl` (the
      pipeline draws and uses holdouts, the runtimes never
      read them), and `validation-answers.jsonl` (the
      review pages that write it are the pipeline's, and no runtime reads it).
    - `embedding-lib`: no data.
    - Live files sit
      outside builds because they can't be regenerated and are written
      between builds.
  - Uninstall: each
    package's `pre_uninstall` (in `manifest.sh`) refuses while it holds
    live files, unless `--keep-state` is given, so nothing is removed. The
    kit's `uninstall.sh` otherwise deletes state; reinstalls and updates
    keep it. An uninstall meant to delete everything needs the live files
    removed by hand first.
  - Principle record: `id`,
    `rule`, `kind` (libraries-tooling, code-structure, test-approach,
    other), `scope`, `trades_against`, `standing` (below-bar, at-bar,
    approved, demoted — computed by the pipeline, never written by a
    model), `evidence` (cases, settings), `approval` (count, projects,
    single-project flag, first use elsewhere logged), `quotes`,
    `first_seen`, `last_seen`, `demoted`, `supersedes`, `superseded_by`.
  - Model-written JSON uses the API's structured outputs and is validated
    against the full schema before it's written; refusals and `max_tokens`
    cut-offs are retried.
  - Migration: build files never migrate; the next build writes the new
    version. A live file's schema change ships with a migration step and
    runtimes that read both versions. The migration takes the owning package's
    lock, writes and validates a converted copy, swaps it in, keeps the old
    file as `<name>.v<old>.jsonl` and updates the manifest; writers follow the
    manifest; the next release drops the old version. A refusal names the
    file, the version found, the versions accepted and the command that fixes
    it.
  - After a refusal (no build delivered yet, an embedding model mismatch,
    or an unaccepted schema version), the runtimes carry on safely and say
    so.
    `decision-runtime`'s lookup returns "nothing covers this", so every
    decision goes to the owner and nothing is decided alone; the gates keep
    working from the decision log; the reviewers skip; the `SessionStart`
    block shows the refusal message in one line. `voice-runtime` tells
    the owner before drafting that the voice model is unavailable and why,
    and offers the draft marked as not in their voice.
- **Anonymiser** stays inside the pipeline, the only thing that runs it. It
  splits out the same way if anonymising is ever needed at use time (e.g. if
  the Slack-connector route for new Slack data is used).
- **Releases**: in
  dependency order, which is the build order — `embedding-lib`, the
  pipeline, `voice-runtime`, `question-store`, `decision-runtime` — each
  released as `<package>-v1.0.0` once its stage is built and its tests
  pass. The pipeline's first release covers corpus extraction; minor
  releases add the voice build and then the decision build. A runtime's
  version says nothing about its model, which is gated by validation and
  trust levels (§3.7, §4.11, §4.12). No pre-releases: the release workflow
  never writes them to `versions.txt`, which installs and updates read.
- **End-to-end tests**: one Docker box for the monorepo,
  as rrc/rrcd use — Linux with real Claude Code installed and logged in, each
  package copied from the checkout into the box (`tar` piped through `docker
  exec`, as rrc/rrcd's `integration.sh` does) and installed there with its
  `install.sh`, so no release is needed to test; made-up fixture data, never
  the real corpus. The release-tarball rule covers installs on this machine,
  not the box. Scripts run from the owner's terminal or `!` (Claude's Bash tool
  can't reach the Docker socket), log to `test/docker/results/<time>/
  run.log`, and tear down what they started. Hooks that call a model use the
  box's login. Alongside each package's `test/run-tests.sh`, and before
  §4.11's machinery tests on the real install.
- No data in any repo; tests use made-up fixtures. Model rebuilds change only
  the runtimes' build directories, never package code. Re-releases are for
  code changes only.

## 6. Cost (estimates, input tokens)

Output tokens are much smaller (mostly labels
and scores). Possible cuts:
second-model labelling on a sample only (the second model labels
all ~17k, §3.4), or fewer held-back voice drafts
(would save 10–15M, at the cost of less certainty).

| Building, once | Tokens |
|---|---|
| Labelling ~17k Slack messages with context | ~8.5M (context cap 20; ~5.5M at 10) |
| Second-model blind labelling | ~8.5M (as above) |
| Decision extraction | ~2–3M |
| Transcripts and PR comments | ~2–3M (PR volume not measured) |
| Writing the guide and principles | ~2–5M |
| Voice validation (~1,700 drafts + judge) | ~14M |
| Exemplar-count test (3, 5 and 8) | ~10M (~5M per extra count) |
| Decision validation | ~2M |
| **Total** | **~49–54M** (the rows' sum) |

| Running, per year | Tokens |
|---|---|
| End-of-turn review | ~25–35M |
| After-each-plan review | ~4–10M. Its ~750–1,000 checks are an unmeasured estimate, which overstates, since only the active repos with `.planning/` use GSD (§1); commits per plan not measured. APPENDIX B.4's own figures give ~7–11M (every-commit tokens less repeated overhead) or ~4–15M (checks × tokens per check) |
| `SubagentStop` and plan reviews | small; volume unknown |
| Drafting | small (guide cached) |

Costs are token counts only and are not priced.

Disk: about 1–2 GB for `embedding-lib`'s environment, about 20 MB for the
corpus.

The owner's time goes on the review pages before reruns, plus confirming inferred reasons and bulk-accepted records,

---

## 7. Verified facts this plan rests on

Checked (Claude Code docs, GSD plugin files and tests on this
machine):

- `SubagentStart` can add context (`additionalContext`), matched by agent
  type, plugin agents included (per the docs; the event is seen firing for a
  GSD agent in the hook log, but context delivery is untested, see below); it
  can't see the subagent's prompt.
- `SubagentStop` can block with a reason, which becomes the subagent's next
  instruction; `stop_hook_active` guards loops; 8 continuations maximum.
- Prompt and agent hook types exist on `Stop`, `SubagentStop` and
  `PreToolUse`, and can block with `{"ok": false, "reason": …}`. The agent
  type is experimental; whether it can run `git diff` is unconfirmed.
- Tested: Workflow agents fire `SubagentStart`, `PreToolUse` and
  `SubagentStop` (agent type `workflow-subagent`). GSD plugin agents fire
  `PreToolUse` and `SubagentStop` (agent type `gsd:bm-executor`), and
  `SubagentStart` too (the saved hook log).
  Not tested for any agent
  type: that `additionalContext` from `SubagentStart` reaches the agent.
- Tested: a `PreToolUse` hook on `ExitPlanMode` receives the plan text; a deny
  keeps Claude in plan mode, the reason reaches Claude, and the revised plan
  can be resubmitted.
- GSD: `autonomous`'s smart discuss asks the owner to accept or override each grey
  area (`references/autonomous-smart-discuss.md`); `bm-executor` already stops
  for architectural changes (Rule 4) and may not run a package install as a
  Rule 3 auto-fix (a failed or not-found install returns a
  `checkpoint:human-verify` task with `gate="blocking-human"`, because of
  slopsquatted or hallucinated names; no substitute names, no retries; that
  installs a plan task calls for are not blocked is inferred, not stated);
  discuss is also skipped
  when a phase already has a `CONTEXT.md` (`has_context`); code
  commits use `git commit`, docs and sub-repo commits use `bm-sdk query
  commit…`, so gates must match both.
- GSD, further (APPENDIX D.3): an infrastructure skip shows the
  line "Phase N: Infrastructure phase — skipping discuss, writing minimal
  context." (`references/autonomous-smart-discuss.md`) and writes a minimal
  `CONTEXT.md` whose `<domain>` is the phase boundary from the ROADMAP goal.
  `CONTEXT.md` records
  only the final answer, not whether it was bulk-accepted or changed.
  `autonomous` pauses "only for explicit user decisions (grey area
  acceptance, blockers, validation requests)" and has "No kickoff
  confirmation"; constraints are surfaced as notices, not gates. Its own
  audit is milestone-level (audit → complete → cleanup), skipped with
  `--only` and `--to`. `gate="blocking-human"` checkpoints are excluded
  from GSD's auto-approval. Rule 4 returns a checkpoint with what was found,
  proposed change, why, impact and alternatives. `autonomous` also runs
  ui-phase (UI design contract) and ui-review.
- Claude Code, further: a `PreToolUse` command, http or
  mcp_tool hook that times out lets the call through, unless it is
  configured so its failure blocks. `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`
  forces the model of every subagent, teammate and workflow agent.
- Buildomator reads any conformant `.agents/workspace.json` at
  `SessionStart` (spec at https://github.com/workspace-json/spec, GSD
  `README.md` L400) and injects its fragile files, frameworks and co-change
  notes; the plugin neither generates nor bundles the file.

## 8. Undecided


### 8.0 Order of work

The open items are worked through in this order. It is grouped by what
blocks each part of the build, following the build order in §5 (voice
model first, then the decision model).
Each
stage lists only what blocks that stage.

**Stage 0 – before any package is written**
1. The monorepo is `claude-impersonator`, and each stage is
   built once its own questions are answered (§5).
2. Each package keeps its own data in its own state, and
   uninstall refuses while live files exist unless `--keep-state` is given
   (§5 Data and state); `validation-answers.jsonl` is the pipeline's.
3. A refusing runtime carries on safely and says so (§5 Data and
   state).
4. End-to-end tests in one Docker box, and releases in
   dependency order, each `v1.0.0` once its stage is built and tested (§5).
   Package contents, the anonymiser inside the pipeline,
   refusal on an embedding model/index mismatch, embedding each message with
   the one it answers, the voice skill reaching subagents too, a
   client-constraint contradiction going to the owner, one shared review record
   per repo, recommendations logged and compared later, no gate for grill-me
   and grill-with-docs, one hook modifying Agent input, first answer wins, the
   decision-log rules, the voice review page saving progress.

**Stage 1 – `embedding-lib` and the corpus (the pipeline's extraction half)**
(§5)
6. Built outputs are anonymised, stored with a real-name copy
   (§2.3).
7. Role-tagged pseudonyms, and client product names found by
   mining the corpus and reviewed by the owner (§2.3).
8. The packages' state is owner-only, not backed up, and kept
   until the owner deletes it, with a `forget` command (
   §2.2).
9. spaCy runs in the pipeline's own venv on `embedding-lib`'s
   Python, with `en_core_web_trf` (§2.3).
10. Corpus JSONL with one record per message, one file per
    source, context as ids; indexes as `.npy` with `ids.json` and
    `identity.json`; one append-only `anonymising-map.json`
    (§2.2).
11. Source scope. Sidechain transcripts: left out.
    Commit messages: left out (§2.1).
    Other machines: the owner's other machines included, cloud
    sessions not (§2.1). The 2018 cut-off:
    a hard rule, repos last updated before `bitbucket.CUTOFF` left out
    Bitbucket: PRs the owner authored, commented on or
    approved, widened to every PR (§2.1, §4.14).
    `.planning/` repos without `config.json` count as GSD repos
    (§1). Open: which repos (picked when the pipeline
    runs, §1). Bot messages kept only as tagged context, channel events
    dropped; agreement reactions on others' messages are decision
    candidates (§2.1).
12. Exemplar thresholds of 3 words or fewer and 50% code; group
    DMs outside the senior set assigned one by one by the owner on the mapping
    page (§3.2, §3.5).
13. Review batches are drawn per source, and each source is held
    until its first batch is approved (§2.3).
14. The user-id DM is with a client contact, Clients audience;
    The owner's self-DM is out of voice, kept for decisions.
    (§3.2).
15. Corpus text is sent only by the pipeline's scripts, one call
    per batch, never through subagents or Workflows (
    §2.3).
16. All of the corpus may be sent, anonymised.
    (§2.3).

**Stage 2 – voice model and `voice-runtime`**
17. Which models draft, label and judge, and whether the blind-labelling
    "second model" is a different model or a different prompt (§8.2).
18. Where the review pages run, and how the blind-pair page saves progress
    (§8.2).
19. Whether the owner also reviews the judge's worst-scored drafts and a random
    few, on top of the 60 blind pairs (§8.2).
20. How the owner's own rules get into the generated guide (§8.2).
21. The 1:1 audience split, the generic-phrase reference list, and the
    fallback for thin audience-and-purpose cells (§8.2).
22. Drafting time: who sets audience and purpose, how an edited-after-
    sending version is captured, `jira-comments.md` wording, `/gsd:ship`
    and `/code-review` formats (§8.2).
23. The exact CLAUDE.md line that loads the skill (§8.2); last, before voice
    goes live.

**Stage 3 – `question-store`**
24. All of §8.4.
25. Which hooks it registers (§8.5).

**Stage 4 – decision model and `decision-runtime`**
26. Similarity search or keyword lookup (§8.3); decides whether
    `decision-runtime` depends on `embedding-lib`.
27. Extraction weighting: "You decide" answers, grill-with-docs rounds
    (§8.3).
28. What counts as an approved entry, and whether a comment in a plan can set
    aside a principle (§8.3).
29. Gates: marked paths, per-stack patterns, test-framework switch, timeout
    behaviour, overriding a false block (§8.3).
30. Reviewers: hook type and model, what happens on a problem and on
    repeated blocks, the pre-filter, `asyncRewake`, plan files as
    decisions, un-anonymised diffs (§8.3).
31. Coverage: `SubagentStart` skip list and a delivery test, advisor
    agents, `autonomous` and its UI phases, OpenSpec, non-git folders,
    other machines (§8.3).
32. Behaviour before the model passes validation (§8.3).
33. Build task, not a question: search every available transcript for a
    dependable marker of Claude's recommendations (§4.5).
34. The remaining §8.3 items, mostly checks rather than choices.
35. Cost figures still to measure (§8.5), once the decision pipeline runs.

**Any time, blocks nothing**
36. A reminder when a deferred tool is installed (grill-me,
    grill-with-docs, OpenSpec), so these items apply once it is in use:
    mechanism and owner open. Possible places:
    in `question-store` as a question parked with an install trigger

### 8.1 Sources and corpus

- The exact Bitbucket repos (to be picked when run; rule set apart from the
  pre-2019 rule in §1).

### 8.2 Voice

- Whether the 1:1 colleagues audience is split further by whether the person
  reports to the owner.
- Which reference list of generic business phrases the "never say" list is
  measured against.
- How a draft's audience and purposes are set at drafting time: inferred by
  Claude, or stated by the owner.
- How the "approved version" is captured when the owner edits a draft after it
  leaves Claude (e.g. edited in Slack before sending).
- How often the regular review sessions run, and what form they take.
- The exact line added to `~/.claude/CLAUDE.md` to load the voice skill
  (the owner approves the wording; CLAUDE.md is theirs).
- Where the review pages run — label checks, blind pairs, and confirmations
  of inferred reasons and bulk-accepted records all show real corpus text; a
  local page keeps it on this machine, a claude.ai page would send it off it —
  and how the blind-pair page saves progress between sittings. (The pages
  are part of `voice-decision-pipeline`.)
- How `jira-comments.md`'s own wording rules (e.g. no second person,
  shorter) sit against the voice model where they disagree. Today §3.1
  keeps only the file's structure. Options: the file's
  wording rules win for Jira comments; the voice model wins; or the file's
  rules apply only where the voice model has no Jira-specific evidence.
- How the voice model sits alongside the formats other tools impose: the PR
  description template in `/gsd:ship` and `/bm:ship`, and the comment format
  of `/code-review --comment`.
- How a rule the owner wants added to the voice guide gets in. The guide is
  generated by the pipeline, so a hand edit would be overwritten; it needs a
  pipeline input the owner can write to.
- Which model writes drafts, and which runs the labelling and the judge.
- Whether the owner also reviews the judge's worst-scored drafts and a random few
  on top of the 60 blind pairs.
  Whether the worst-and-random review is added
- When an audience-and-purpose cell has too few exemplars, whether to fall
  back to the same purpose in another audience.
- Whether "second model" for blind labelling means a different model, or the
  same model with a different prompt.
- Whether subagents receive the `~/.claude/CLAUDE.md` line that loads the
  voice skill, and a test that a drafting subagent loads it (§3.6).
  Not checked. `/code-review --comment` may word its comments in reviewer
  subagents; also not checked.

### 8.3 Decisions

- Whether the decision lookup uses similarity search or keywords. If
  keywords are chosen, `decision-runtime` no longer needs `embedding-lib` or
  the ~1–2 GB environment at use time. Either way it filters locally first
  and returns only the fields an agent needs (§4.10).
- Whether a comment in a plan can set aside an approved principle, and how
  such a comment is traced to the owner rather than to the agent that wrote the
  plan (`bm-planner` writes GSD plans).
- Reviewer hook type: prompt (single call) or agent (experimental; whether it
  can run `git diff` is unconfirmed), and which model it runs on (the cost
  estimate assumes the cheap background tier).
- Which model makes the held-back decision predictions and which runs the
  decision judge.
- Which paths count as "marked paths" for the path gate.
- The gate patterns per stack (manifest files and install commands for
  JS/TS, Dart, Go, PHP); the exact `bm-sdk query commit…` and `git commit`
  patterns (§7 says both must match); and what tool call counts as switching
  test frameworks (e.g. a new test dependency in a manifest, a new test
  config file such as `jest.config.*`/`vitest.config.*`) — not defined.
- Whether the gates are configured so a timed-out gate blocks the call
  (by default a `PreToolUse` timeout lets it through, §7).
- Whether a phase-end audit (diff against decision log, unlogged items to the
  question record without blocking) is built, or the reviewer is enough.
  GSD's own milestone-level audit in `autonomous` (§7) is not that audit.
- Whether decisions are also written to GSD's own decision log
  (`gsd_add_decision`) in GSD repos, alongside `decision-runtime`'s log.
- Where the decision log lives and its entry format, beyond the fields in §4.8
  (decision, agent, principle ids, asked or made alone, supersedes).
- The infrastructure-skip check: which hook event detects the minimal
  `CONTEXT.md` (the file write, or its `bm-sdk` commit), how it holds the
  run, and which signals it matches (candidates, §7: the display line, and
  a `<domain>` that is the phase boundary from the ROADMAP goal). Also what is
  reviewed at that point: when the minimal `CONTEXT.md` is written the planner
  hasn't run, so there is no approach yet; the check either reviews the phase
  goal against the decision model there, or waits for the first `PLAN.md`
  before execution starts.
- Whether a pre-existing `CONTEXT.md` not written by the owner (discuss is
  skipped when `has_context` is true) needs the same check as the
  infrastructure skip.
- Whether the end-of-turn reviewer treats changed plan and spec files
  (OpenSpec's `proposal.md`/`specs/`, GSD's `PLAN.md`/`CONTEXT.md`, plan
  files) as decisions rather than code; not
  decided.
- Which hook event catches `/opsx:apply` (a slash command is not a tool call
  unless run through the Skill tool; `UserPromptSubmit`/`UserPromptExpansion`
  are the candidates) — not checked.
- How client constraints are matched to the current repo (a repo-to-client
  mapping).
- How often `/gsd:profile-user` is rerun on anonymised copies.
- Whether the profiler's own "Sensitive Content Exclusion (Layer 1)" and
  "Message Thresholds" (in `references/user-profiling.md`, APPENDIX D.3)
  still behave correctly on an anonymised sample.
- What a review session for decisions looks like, and how often.
- Whether any GSD setting can narrow `bm-executor`'s Rules 1–3 (not checked).
  L116 also forbids ad-hoc pauses to ask about mechanics (APPENDIX D.3).
- Whether `bm-phase-researcher` (spawned by `/gsd:quick`, `quick.md` L411)
  needs the parking test along with the other deciding agents (§4.11).
- Whether the after-each-plan review hooks `SubagentStop` or `PreToolUse` on
  `SubagentHandback`: the observed `bm-executor` handed back through a
  `SubagentHandback` tool call, logged by `PreToolUse` a second before
  `SubagentStop` (APPENDIX D.2). Not decided.
- Whether OpenSpec runs its own agents (its docs don't say).
- How the `SessionStart` block behaves in sessions that never touch code (it
  fires in every session; behaviour not decided).
- What counts as an "approved entry" for the gates. If an agent can log its
  own decision and then pass the gate, the gate is circular; it needs to be
  limited to entries backed by a usable principle or by the owner's answer.
- What the reviewer does when it finds a problem. Today §4.5 says it sends
  the agent back. Open: whether,
  besides that, it reverts, logs it or parks a question; and in the main
  session, where the owner is present, whether it asks them directly instead of
  sending Claude back.
- What happens when the reviewer keeps blocking: Claude Code caps
  continuations at 8; whether the reviewer then parks a question. (A prompt
  hook's `"impossible": true` lets the stop go ahead, APPENDIX D.1.)
- How the owner overrides a false block ("allow anyway") without a workaround.
- Whether a local pre-filter limits the end-of-turn and after-plan reviews to
  changes that touch structure (new or moved files, large diffs), to cut
  cost.
- What the gates and reviewers do before the decision model exists or while
  it's at trust level 0: live from the start, or only once the model passes
  validation.
- How the owner adds or adjusts a principle directly. The principles file is
  generated, so it needs a pipeline input, like the voice guide.
- Folders that aren't git repos (e.g. a scratch folder) have no diff
  for the end-of-turn review, and changes outside the working directory (e.g.
  `~/.claude` files) aren't seen unless the hook is told where to look.
  Whether those are covered is not decided.
- Sessions this machine's hooks don't reach: claude.ai cloud sessions and
  any other machine. Whether the runtime is installed
  anywhere else is not decided.
- Buildomator's `.agents/workspace.json` reader (§7) as another delivery
  route: `decision-runtime` could emit a conformant file.
- `bm-executor` treats a project `./CLAUDE.md` as hard constraints — a
  stronger route for that agent (it would mean editing each repo's
  CLAUDE.md).
- Whether `bm-advisor-researcher`, `bm-framework-selector`, `bm-plan-checker`
  and `code-review-fix` — which recommend or judge without the owner — are covered
  beyond the `SubagentStart` block (the review points cover code changes, not
  recommendations).
- Which agent types the `SubagentStart` block skips. Today §4.4 allows
  skipping agents that never decide, by type, while §4.6 has the Explore and
  Plan agents (planning research) and grill-me's fact-finding subagents
  receiving the block. Options: skip Explore (and other read-only types),
  so they get nothing; or skip none, so every subagent gets the block.
  Workflow agents launched with `agentType` report that type, not
  `workflow-subagent` (APPENDIX D.1).
- A test that the `SubagentStart` block's `additionalContext` reaches the
  agent, for GSD plugin agents and workflow agents. That the event fires for
  both is shown by the saved hook log (§7); delivery of the context was not
  tested.
- The logging gate (a `SubagentStop`/`Stop` hook refusing to let an agent
  finish with unlogged decisions): whether it is one of the enforcement layers,
  and whether it's still needed now the reviewer reads diffs and catches
  unlogged decisions itself.
- In plan mode, whether a `PostToolUse` hook logs the approved plan's
  decisions as the owner's, and whether uncovered decisions go into the plan as
  open questions (the owner is present at approval) instead of `question-store`.
- Reviewer diffs go to the API un-anonymised.
- Whether the end-of-turn `Stop` reviewer uses `asyncRewake` like
  claude-guard-hooks 1.3.1 (a `Stop` hook's block reason is otherwise printed
  to the owner in full).
- How the park rule maps onto `autonomous`. `autonomous` doesn't wait for
  replies (§7), so a parked question pauses a run only through blocker
  mirroring. A question mirrored to `STATE.md` blockers sends `autonomous`
  to `handle_blocker`, which asks the owner to choose "Fix and retry", "Skip
  this phase" (marks the phase skipped and carries on) or "Stop autonomous
  mode"; it does not wait for the question's answer. Options not decided,
  e.g. stopping, then resuming with `--from`. In `autonomous --interactive`,
  plan and execute for phase N run as background agents while discuss for
  N+1 starts; how a question parked by N's executor interacts with that is open.
- Whether `autonomous`'s ui-phase (UI design contract) and ui-review are
  covered; not decided.
- Origin weighting (§4.9) needs the transcript's AskUserQuestion answers,
  because GSD's `CONTEXT.md` records only the final answer (§7). A "You
  decide" answer in discuss is the owner delegating and shouldn't count as the owner's
  choice; how it is counted is not decided.
- Which GSD checkpoints auto-approve, beyond `gate="blocking-human"` ones
  being excluded (§7): not checked.
- Whether Rule 4's checkpoint (what was found, proposed change, why, impact,
  alternatives — §7), and the package-install `checkpoint:human-verify`
  (answered "verified" with the package name, or "abort"; APPENDIX D.3),
  feed `question-store`; not decided.
- `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` (§7) bears on the model-choice items
  above and in §8.2.
- grill-with-docs may ask questions with no recommendations when a
  dependency fails to load (the aihero.dev page describes this failure mode
  without saying more), which would undercut §4.6's reliance
  on recommended answers shaped by the `SessionStart` block. Unchecked
  beyond that page.
- OpenSpec lets any artifact change at any time, so edits to
  `openspec/changes/<change>/` after `/opsx:apply` aren't seen by the plan
  reviewer. Whether the adapter re-reviews on later edits, or leaves them to
  the end-of-turn review treating spec text as decisions (open above), is
  not decided.
- Whether `[Rule N - Type]` deviation entries in GSD `SUMMARY.md` files are
  also decision candidates for the extraction filter (§4.9). Not decided.
- How grill-with-docs records are weighted (§4.9). `grilling` asks a whole
  numbered round, each question with a recommended answer that "yes"
  accepts, so a round answered "yes" is close to bulk acceptance. An ADR is
  written only when the owner says yes to it, and `GLOSSARY.md` is updated
  without asking. Whether these count as the owner's or as weak
  evidence is not decided.

### 8.4 Questions to the owner (`question-store`)

- Which session sends notices and reads Slack replies, and how often (push
  and the Slack connector are only callable from a Claude session). Push and
  Slack delivery, and reading Slack replies, only happen while a Claude
  session is running, not from a background service. A question parked when
  no session is running isn't delivered until one starts. A background
  sender could only send by some other route than those two tools.
- Whether a Slack DM to the owner themselves counts as "posting" under the
  approval gate on outgoing messages, which covers the exact
  text. Sending questions there needs either a standing exception written
  into that rule or approval per message.
- Which push mechanism is used (Claude Code's push notification tool is
  assumed).
- Whether a Slack DM the owner sends to themselves notifies them at all. Slack may not send
  notifications for messages in a self-DM, which would make it a place
  to answer but not a way to be told. Not checked.
- The session command's name, and whether it can also be used to answer.
- What a question shows beyond the fields in §4.7 (decision, options,
  principles that came close, waiting work), e.g. a deadline or which run is
  waiting.
- Blocker mirroring (§4.7) works only in GSD repos (no `STATE.md`
  elsewhere; APPENDIX B.5). Open: whether anything outside GSD needs a stop
  like `handle_blocker`, or the question record and the park rule are enough
  there. Also open: whether mirroring lives in `question-store` (the contents
  (the package list, §5, puts it there, which makes it depend on GSD's `gsd_add_blocker`
  and `STATE.md`) or in `decision-runtime` or a GSD adapter, so
  `question-store` keeps no GSD dependency.
- How the owner changes an answer already given (which channel or command), and
  what happens to work that has already resumed on the old answer. §4.8
  covers only the log entry.
- How waiting work learns that a parked question has been answered and is
  resumed, outside `autonomous`'s blocker route: polling by the waiting
  agent, a hook in the next turn, or the owner restarting it. Open: if
  the run that parked the question has ended, nothing in the plan restarts it.

### 8.5 Packaging and process

- Which hooks `question-store` itself registers (it's a command package
  with hook registrations, §5).
- Which estimates still need measuring: Bitbucket PR and comment volume,
  commits per GSD plan (the after-each-plan figure in §6 rests on an assumed
  count), the number of PRs per repo.
- Each install adds its own sandbox exclusion with a wildcard (`"rrc *"`); a
  bare entry matches only the bare command — relevant if any package's
  commands must run outside the sandbox.
- The by-hand `/gsd:profile-user` run: the workflow deletes its temp
  directory holding the sample (`{temp_dir}/profile-sample.jsonl`, the file
  to anonymise) and the analysis (the agent's `<analysis>` JSON block), so
  both must be copied to the pipeline's state before cleanup.
- Whether pipeline rebuilds (folding in new transcripts, PRs and GSD
  records) are run by hand in review sessions or scheduled automatically.
- Running costs not estimated in §6: the 300–600-token block
  in every session (`SessionStart`) and every subagent launch
  (`SubagentStart`), lookup results at each decision, gate denial reasons,
  and any `PostToolUse` plan logging.
- Which after-each-plan review figure stands. §6 gives ~4–10M a year. APPENDIX
  B.4's own numbers give ~7–11M (every-commit tokens less the repeated
  overhead) or ~4–15M (checks × tokens per check). The ~750–1,000 checks
  behind all three are an unmeasured estimate. No method was chosen. Measuring
  commits per plan from the local plans would settle the count.

## 9. Needs the owner when it runs

1. Add `read:repository` to the Bitbucket token. The token is in `~/.netrc` (REST
2. Pick the `oneiota` repos.
3. Review the first anonymised batches, until the owner says stop.
4. Check the audience mapping, the label sample and the sample of
   second-model disagreements (§3.4); confirm inferred reasons
   and bulk-accepted records.
5. Grade the 60 blind voice pairs (more whenever the owner wants).
6. Grade every held-back decision case (at least 52 per kind, §4.11).
7. Decide every old-against-new conflict before an orchestrator gets the
   decision model.
8. Run the install command for every package. Each installs from its
   release tarball, and where the installer places it (`~/.claude/skills/
   <name>`, `~/.claude/<name>`, hook registrations in
   `~/.claude/settings.json`) is outside Claude's Bash sandbox.
9. Move the decision model up trust levels.
