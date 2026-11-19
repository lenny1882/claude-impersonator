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
  attachments as file names. Mining doesn't search code for names; known
  names are replaced in it as everywhere (§5).
- **Transcripts:** each typed prompt plus the text of Claude's reply before
  it, a one-line summary per tool call (which file, which command),
  AskUserQuestion questions and answers, project name and date. Claude's
  preceding reply is kept because it is usually what the owner was correcting.
  Main-session transcripts only: subagent (sidechain) transcripts are left
  out. Their text is Claude's, and the owner's own words
  and answers are all in the main sessions.
  Transcripts from other machines are left out of this build.
  claude.ai cloud sessions are not a source.
  If another machine's `~/.claude/projects` is copied here later,
  the pipeline's `import-transcripts <dir>` reads it through the same
  anonymising and filters.
- **Git commit messages:** not a source. Most are
  short subject lines, and PR descriptions and threads cover the same
  changes for Bitbucket repos.
- **Bitbucket:** each comment with its PR title, description and thread.
  PRs the owner authored, commented on or approved; a
  silent approval counts, as a record that the owner accepted the approach. A PR
  the owner was only added to as a reviewer, with no comment or approval, is left
  out. It covers every PR in the picked repos
  (§4.14). The repos are picked from a pre-pass that counts, per repo,
  the PRs the owner authored, commented on or approved.
  Inline comments get the code under them from the API, which needs
  `read:repository` on the Bitbucket token, which it has.

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
- Every package's state is owner-only: directories
  700, files 600. Each package's scripts set umask 077 before writing; each
  install creates its state directory as 700 and its verify step checks the
  modes.
- No backup. Losing the system disk or `~/.claude`
  loses the live files (decision log, reviewed-changes record, gate state,
  questions, drafts, validation answers, holdouts) and the anonymising map;
  builds and the corpus can be rebuilt from the sources.
  The drafts, decision log and questions also reach the builds repo,
  encrypted (§5), and the `age` key is backed up outside the machines.
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
  (about 1.2 GB in all) and makes a corpus pass slower: a full
  `anonymise` takes hours on a CPU-only machine.
  spaCy's tags are cached by text, so a rerun tags only
  new text. The run asks nothing; the owner's part comes after it (the leak
  check, mining decisions, then the first batches).
  spaCy also tags some ordinary words as names and blanks them. Product,
  store and project names that identify a client on their own are found
  by mining the corpus: while building it, the pipeline
  collects every term spaCy tags as an organisation or product, and
  capitalised terms concentrated in one client's channels or repos. The owner
  strikes or keeps each on one local review page before the first review
  batch is sent; kept terms join the replacement list.
- A single word only spaCy tags as a person is the owner's to decide.
  Each is listed
  on the review page with its counts and a suggestion, and the owner marks it a
  name or not a name. A name is replaced everywhere in any case; not a name
  is never replaced; until marked, it is replaced only where spaCy tagged
  it, and no batch is drawn. A name of two or more words is
  replaced everywhere in any case.
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
- Reviewer hooks send code diffs from the working repo to the API
  un-anonymised: they aren't corpus data, the session
  that wrote them already sent them, and client constraints need real names
  to match the code.
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
  plugin files are not edited. It is re-run with every pipeline rebuild, so
  the profile matches the transcripts the build used.
  Checked against GSD 5.1.0's `references/user-profiling.md`:
  anonymising doesn't change message counts, so the message thresholds
  behave as on raw text; the sensitive-content patterns (`sk-`, `Bearer `,
  `password`, `secret`, `token`, `api_key`, home-directory paths) still
  match where those words or paths remain, so such quotes are skipped, and
  a quote holding a `[REDACTED:<type>]` marker carries no value.

### 2.4 Time

- No cut-off for Slack or transcripts. Bitbucket keeps its own rule (§1).
- When an older and a newer position disagree, both are kept and marked
  unresolved. Once the work is finished, every such conflict is listed for
  the owner to decide, and no orchestrator gets the decision model until they have.

---

## 3. Voice plan

### 3.1 Uses

Slack messages, PR descriptions, PR review comments, Jira comments. Jira
comments are their own audience (§3.2), with no exemplars: their guide
  section is the `## Jira` section of
the owner's rules file (§3.5), and those rules win on wording.
Validation has no held-back Jira messages, so it can't test Jira
drafts. Where a tool sets a format (the PR description templates in
`/gsd:ship` and `/bm:ship`, the comment format of `/code-review
--comment`), the tool keeps its structure and the voice model does the
wording inside it. Every draft goes to the owner for
approval before anything is sent.

At drafting time Claude works out a draft's audience (from where it is
going, by the §3.2 mapping) and purposes (from the request), and shows
both above the draft for the owner to correct.

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
| Jira | none: rules only, no exemplars (§3.1) |

Each conversation is assigned by its name and members; the owner checks the
mapping. 1:1 colleagues is not split by whether the person reports to
the owner; per-audience validation results show if it
needs to be. Any other internal channel not covered goes to the project team
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
  Sonnet 5.5 labels purposes on
  anonymised messages.
- Checking, in parallel: the owner checks a sample of 120 labelled messages
  spread across audiences and purposes (more whenever the owner wants), and a second
  model, Opus 5.5 (a different model, not a different prompt)
  labels all ~17k messages blind.
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
  built locally, no API. Measured against two references:
  Phrases common in other people's messages in the corpus and rare
  in the owner's, built from dictionary words only so no name gets in; and a
  fixed list of a few hundred generic business and assistant phrases,
  written once and committed.
- Exemplars drawn from the whole labelled corpus, minus messages of 3 words
  or fewer and messages at least 50% code
  or logs by characters, counting fenced blocks and unfenced log or
  stack-trace lines. Dropped messages still count in
  the measured statistics (never-say list, length per audience). The
  thresholds are config values; changing them re-runs exemplar selection
  only. A kept exemplar is stored with its code blocks replaced by `[code]`:
  Mining doesn't search code, so code could carry a
  name nobody found, and the voice model doesn't use it.
- Exemplar choice uses both: labels narrow the pool to the right audience and
  purposes, then similarity search picks the closest few. How many is set by
  validation: the model judge scores held-back drafts made with 3, 5 and 8
  exemplars, and the best-scoring count is used.
  When an audience-and-purpose cell has too few, the rest come from the
  same audience, the closest by similarity whatever their purpose.
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
- The owner's own rules: a rules file in the pipeline's
  state, owner-only and never committed, is copied word for word into the
  guide as its own first section at each build. Where one conflicts with a
  rule drawn from the corpus, the owner's rule wins. It reaches other machines
  inside the encrypted build.

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
  its context, audience and purposes only, by Opus 5.5, the model the owner's
  sessions draft with; validation runs again if that
  model changes.
- In parallel: the owner sees 60 blind pairs (their real message and the draft,
  shuffled), 12 per audience across the five corpus audiences (not Jira), covering as many of
  the 11 purposes as each audience's held-back messages allow. For
  each pair the owner answers "A is mine", "B is mine" or "can't tell", and grades
  the draft 1–5 for "would send as is". The owner can review more at any time (the
  review page saves progress between sittings;
  The progress file
  holds pair ids and answers only, the key staying in the pipeline's
  state; each answer is written there as it is given). A
  model judge, Fable 5.2 (not the drafting model),
  compares every draft with the real message and scores it.
  The owner's graded pairs also show where the judge disagrees with them, which
  is how the judge's scores on the other ~1,700 drafts are trusted. On top
  of the pairs, the owner also reviews the judge's 20 worst-scored drafts and
  10 random ones each validation run.
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
  When the owner edits a draft after it leaves Claude (in Slack, say), the next
  build matches the saved draft to the message actually sent (same
  conversation, close in time, closest by similarity) and records that as
  the approved version.
- Regular review sessions with the owner feed them back in.
  One is offered once 20 edited drafts have built up or 4 weeks
  have passed, whichever is first (config values), and the owner can start one
  at any time. It runs on the local review page: recurring edits shown as
  suggested lines for the owner's rules file, approved versions proposed as
  exemplars, each accepted or rejected by the owner.
- Decision review happens in the same session, on a Decisions tab
  inferred reasons, bulk-accepted records, the choices Claude made in
  answers given after a "You decide", reviewer blocks from subagents and GSD runs,
  phase-audit finds, recommendations against the owner's choices, and ladder
  promotions, each with its evidence, accepted, rejected or corrected one
  by one. The offer rule counts items waiting on either side: 20, or 4
  weeks, or whenever the owner starts one.
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
Its wording limits it to technical decisions in code work and in
recommendations about code; in sessions that never touch code it asks and
parks nothing.
At each decision the agent calls the lookup, which returns the matching
principles, tech positions and client constraints, each with its status
(usable, below the evidence bar, unresolved). The lookup uses similarity
search through `embedding-lib`, filtering locally first.

### 4.4 Delivery and enforcement layers

All generated from one source file, so each agent gets one copy. That file
is a `voice-decision-pipeline` output (§5).

| Layer | Strength | Reaches |
|---|---|---|
| Gating hooks: deny dependency changes (manifest edits, installs), test-framework switches and edits under marked paths unless the decision log has an approved entry | enforced | every session and subagent |
| Logging gate: not built; the reviewer sends agents back for unlogged decisions at the same points | — | — |
| `SubagentStart` block | advisory | every subagent, plugin and workflow agents included (read-only search and help agents, such as Explore and `claude-code-guide`, are skipped by type; Plan agents and every agent that edits or recommends get it). Observed firing for workflow agents and for a GSD plugin agent (`gsd:bm-executor`; saved hook log, APPENDIX D.2). That the block's context reaches the agent is not tested for either — §8.3 |
| `SessionStart` block (instead of a CLAUDE.md section, so subagents don't get it twice) | advisory | the main session, every session (not just GSD repos, because Claude's recommendations in ordinary sessions follow the model — §4.1) |

Gates:

- Marked paths: a default list (CI and deploy config such as
  `bitbucket-pipelines.yml` and `serverless*.yml`, infrastructure-as-code
  such as Terraform, database migrations, `.env` files), plus a small file
  at a repo's root that adds paths or takes defaults off.
- Patterns per stack (manifest files and install commands for JS/TS, Dart,
  Go and PHP; the two commit-command patterns §7 says must both match) are
  taken at build time from what the repos on this machine use. Switching
  test frameworks is a new test dependency in a manifest or a new test
  config file (`jest.config.*`, `vitest.config.*` and the like). The full
  list goes in the gates' config and the owner reviews it before the gates go
  live.
- A gate that times out blocks the call: a 30-second limit, which covers
  the embedding model's cold start, and every timeout is logged.
- A wrong block is overridden through the question the denial parks: "allow
  this one" becomes an asked entry so the retry passes; "this rule is
  wrong" also flags the pattern or marked path for the next review session.
  Both are logged as false blocks. There is no allow command.

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
| GSD execute runs (including `/gsd:quick`) | after each plan: `PreToolUse` on the executor's `SubagentHandback`, so a problem denies the hand-back before the report leaves; `SubagentStop` as the fallback for agents that end without one |
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
- How the reviewer runs:
  - A command hook works out the diff against the review record locally,
    looks up the principles touching the changed files, and sends both in
    one `claude -p` call.
  - Haiku 5.5 screens every review; Sonnet 5.5 confirms before anything is
    blocked.
  - On a problem, subagents and GSD runs are sent back with the reason; in
    the main session the owner is asked first (fix it, allow this one, or the
    rule is wrong). Nothing is reverted.
  - After 2 blocks on the same problem the reviewer parks a question
    (diff, principle, both attempts) and lets the agent stop.
  - A local pre-filter skips the review when the change is only whitespace
    or formatting, only comments, only docs other than plan and spec files,
    or only generated files.
  - The end-of-turn `Stop` review runs in the background with
    `asyncRewake`, as claude-guard-hooks 1.3.1 does: the turn ends at once,
    and only a problem wakes Claude. On a timeout the review record isn't
    advanced, so the next review covers the change.
  - Changed plan and spec files (GSD `PLAN.md` and `CONTEXT.md`, OpenSpec
    `proposal.md` and `specs/`, plan-mode plan files) are read as
    decisions and checked like code. Apart from plan mode and the GSD
    infrastructure skip (§4.6), this is the only check on plan text before
    it is built.
  - Coverage: the reports of `bm-advisor-researcher`,
    `bm-framework-selector`, `bm-plan-checker`, `code-review-fix` and
    `bm-ui-auditor` are checked against the principles when each finishes,
    so a recommendation against one is flagged before the owner chooses.
    `UI-SPEC.md` is read as a plan file. A hook records every file written
    or edited through Claude's file tools, in any folder, and the reviewer
    gets those changes as well as the git diff, so folders that aren't git
    repos and files such as `~/.claude` are covered; a shell-made change
    outside a git repo is not. OpenSpec's open points wait until the owner
    starts using it.
  - Once a build is delivered the reviewer blocks, at trust level 0 too
    with no build it skips (§5).
  - A skipped agent's decision is still caught if it ends up in code; one
    that reaches the owner only as a recommendation is not.
  - Each `claude -p` call carries about 46k tokens of Claude Code's own
    setup, which §6's reviewer figures leave out.
- A phase-end audit is built: when a GSD phase
  completes, Sonnet 5.5 diffs the whole phase against the decision log and
  sends anything that looks like an unlogged decision to the question
  record. It never blocks. Each find is a reviewer miss, logged for the
  miss estimate (§8.3).
- What stays unprevented: a judgement call made in text inside a GSD step
  that the reviewer misses. The owner's review sessions catch it after the fact,
  as can the phase-end audit.

### 4.6 Plan review

Why: while a plan is being written nothing is edited, so
the end-of-turn review has no diff and the plan's choices go unchecked until
they're built.
Other tools rely on the end-of-turn review after code is written.

One plan reviewer with a small adapter per tool, naming where the tool's plan
text lives and which event marks it final. The first adapters are the GSD
infrastructure skip and `ExitPlanMode`; each new tool costs one adapter

- **GSD infrastructure skip:** `autonomous` skips discuss for phases it judges
  pure infrastructure and writes a minimal `CONTEXT.md`. A hook notes the
  skipped phase when that file is written, and when the executor is about
  to start, the phase's first `PLAN.md` is reviewed against the principles
  before execution; anything not covered is parked.
  The file, event and signals that mark a skip are taken at build time from
  the installed GSD version and shown to the owner with the gate patterns.
  The same hold applies to any phase where discuss didn't run with the owner,
  including a pre-existing `CONTEXT.md` the owner didn't write (`has_context`);
  one they wrote through discuss is recognised from its discuss session in
  the transcripts and isn't held.
- **Claude Code plan mode:** a `PreToolUse` hook on `ExitPlanMode` (it
  receives `plan` and `planFilePath`) reviews the plan before the owner is asked
  to approve. Planning research runs in the built-in Plan and Explore agents:
  they skip CLAUDE.md, get the `SubagentStart` block unless their type is
  skipped (Explore may be — §8.3), and never trigger `SubagentStop` review
  (no edits). Decisions the review finds no principle for go into the plan
  as open questions, which the owner answers as part of approving; each answer
  is logged as an asked entry. After approval, a `PostToolUse` hook logs
  each decision in the plan as "approved in a plan", weak evidence that
  counts only once the owner confirms it in a review session.
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
  it, plus where it came from (the repo, the session's name and its Remote
  Control link) and when it was parked; no deadline.
  At trust level 0 the asking agent's recommendation and the model's
  prediction are both hidden until the owner answers, then shown with whether
  each matched; from level 1 both appear with the question.
- Channels: push notification (only tells the owner a question is waiting) and
  the session itself, answered locally or from the phone through Remote
  Control. Slack is not a channel: a Slack connector
  message posts as the owner, and Slack doesn't notify a user of their own
  self-DM. A run started in a plain terminal session is answered only at
  that terminal; long runs are started in Remote Control sessions. Slack
  can be added later through a separate bot app with its own token, never
  the connector.
- Every answer, from any channel, is written back to one local question
  record (`questions.jsonl` in `question-store`'s state, holding each
  question, its status, the answer, the channel it came from and when); first
  answer wins and the other channels are told.
  A later, different answer from another channel is not applied;
  The owner is told it was already answered. The owner changes an answer on
  purpose in `/questions`: not yet picked up, the new
  answer replaces it; picked up by a session still running, that session is
  sent the change the same way; picked up by a run that has ended, `/questions`
  marks it changed after use for the owner to decide what to redo. The
  decision log keeps both answers.
- One session command, `/questions`, lists every question, open and
  answered, with the answer and the channel it came from, and answers them:
  an open question picked there is put to the owner as a multiple-choice prompt
  in whichever session the owner is in, and the answer goes to the question record
  for the waiting work.
- Waiting work resumes by message: at park time the
  question record keeps the session's `CLAUDE_CODE_MESSAGING_SOCKET` and
  `CLAUDE_CODE_MESSAGING_TOKEN`; when the answer is recorded,
  `question-store` posts it to that socket, and an idle session starts a
  new turn with it (Claude Code's cross-session messaging, 2.1.224 or
  later). Nothing runs while waiting. A session in bypass-permissions mode
  holds the message for approval. If the session has closed, `/questions`
  lists the question as answered with nothing waiting, with its session
  link; the owner reopens it, and nothing runs `claude -p --resume` on its
  own.
- `question-store` registers one hook, `SessionStart`:
  it lists the repo's open questions, and answered ones whose session has
  closed, reading the question record only.
- The session that parks a question sends its push, with Claude Code's
  push notification tool. No session runs only to
  deliver questions.
- Open questions are mirrored to GSD blockers (`gsd_add_blocker`; resolved
  with `gsd_resolve_blocker`), so questions survive a restart and
  `autonomous`'s `handle_blocker` step stops at them before the next phase.
  That step offers retry, skip or stop rather than waiting for the answer;
  with `--interactive`, discuss for the next phase may already be running.
  When `handle_blocker` meets a mirrored question, `decision-runtime`'s GSD
  adapter puts the question itself to the owner there, with its options and
  evidence, in place of the bare choices; the answer is recorded in the
  question store, the blocker resolved, and the run takes "Fix and retry"
  Under `--interactive` the same happens when that
  phase reaches the step. The mirroring lives in
  `decision-runtime`'s GSD adapters, so `question-store` has no GSD
  dependency. Outside GSD repos no stop is added; the
  agent holds the dependent step under §4.2 and `/questions` lists what is
  waiting.

### 4.8 Decision log

- The log is `decision-log.jsonl` in `decision-runtime`'s state,
  append-only, travelling in segments (§5). Its JSON Schema is written at
  build time, with the review verdicts, reviews that found nothing,
  delegations and phase-audit finds as fields, and the owner reviews it before
  use.
- Every decision made alone is logged with the agent and the principle ids it
  relied on. Only in `decision-runtime`'s log, never in GSD's `STATE.md`
  decisions: the pipeline reads those as the owner's own,
  so the model would learn from its own output.
- An approved entry, the only kind that lets a gate through, is an "asked"
  entry. An entry citing a principle the gate itself
  looks up and finds usable passes too, but only once the owner takes the
  §4.12 step that lets at-bar principles satisfy the gates; until then only
  the owner's answers pass. Anything else is denied and the
  agent parks a question.
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
  false blocks included. Every review is logged, not only blocks: one that
  found nothing is logged with its diff range and the principles it checked
  The owner's verdict is kept with each block they judge
  in the owner's own session (fix it: right; allow this one, or the rule is wrong:
  wrong). Blocks in subagents and GSD runs, which the owner never sees as they
  happen, come to the next review session for the owner's verdict.
  A principle with 2 blocks the owner judged wrong drops back to "ask"
  until the owner approves it again; the reviewer stops blocking on it, and the
  rest of the model stays at its level.
- The reviewer's miss rate: each review session shows
  10 random reviews that found nothing, with their diffs and the principles
  checked, for the owner to mark whether each should have been blocked. The owner's
  marks and the phase-audit finds give a miss rate with a 95% range on the
  review page.
  the sweep, logging review blocks) follows the points above.

### 4.9 Extracting decisions

- A broad local filter (so that fewer decisions are missed)
  picks candidates (threads weighing options, wording
  like "rather", "instead", "should we", PR comments asking for changes,
  transcript corrections). `[Rule N - Type]` deviation entries in GSD
  `SUMMARY.md` files are picked up too: Rules 1–3
  entries are logged as the executor's decisions made alone, checked in
  review sessions and the phase audit, never counted as the owner's evidence;
  Rule 4 entries count as the owner's, with their answer from the question store. All
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
- A "You decide" answer in discuss is a delegation, not the owner's choice
  it counts towards no principle and is recorded as a
  kind of decision the owner hands to agents (§4.1); what Claude then chose is
  weak evidence until the owner confirms it in a review session.
- How grill-with-docs records are weighted is decided when their reader is
  added (§1).

### 4.10 Output

- Cases and evidence quotes keep any code they quote:
  an agent asking for the evidence behind a rule sees the code it came
  from. The rules themselves hold no code.
- The owner's own principles: a principles file in the
  pipeline's state, owner-only and never committed. Each entry is marked as
  the owner's and counts as approved, so it is usable without evidence; it wins
  over an extracted principle it conflicts with; an entry naming an
  extracted principle's id changes or removes it. It reaches other
  machines inside the encrypted build.
- Principles, each with dated evidence quotes, what it trades against, and
  when it was last seen — last-seen date because a position from, say, 2021
  may no longer hold.
- Priority order for settling conflicts between principles (e.g. speed
  against correctness, build against buy, a client's request against
  maintainability).
- Tech positions on specific tools and platforms (for example:
  Flutter), dated.
- Client constraints, per client or project. Which client a repo belongs
  to comes from a mapping the pipeline proposes from each picked repo's
  name and its PRs' conversations, which the owner confirms on the local review
  page; it is stored with the build. A repo with no client, or first seen
  after the build, gets no client constraints until a build maps it.
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
- A comment in a plan cannot set aside an approved principle.
  Plans are written by agents (`bm-planner`), so a conflicting
  comment makes the agent park a question naming the principle, and only
  The owner's answer lets that one case through; the principle stays.
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
  alone, by Opus 5.5, the model the owner's sessions decide with; Fable 5.2
  judges. Outcomes: right, wrong, or refusal. Refusals are split:
  correct (no principle at the bar, outside the kinds, or a client
  constraint conflicts) and unnecessary (a principle at the bar covered it
  and would have given the owner's answer). Unnecessary refusals are reported
  and traced to their cause (lookup miss, principle worded too narrowly);
  neither kind counts against the pass.
  Why refusals don't count against the model:
  a confident wrong prediction is the failure that
  matters; a refusal is safe, because the question just reaches the owner.
- Grading in parallel: a model judge (Fable 5.2) scores every prediction against the owner's
  real choice and stated reason; the owner grades every held-back case,
  so the owner's grades decide the pass and measure how far the judge agrees with
  the owner.
- Machinery tests: every agent type that gets the `SubagentStart` block
  parks a decision outside the three kinds — the test list and the block
  list are one list, with read-only search and help agents skipped (§4.4),
  so GSD's phase researcher, which quick tasks also spawn, is tested too;
  each review point sends back a planted bad decision; the question record
  delivers by push and the session, and returns answers by message (§4.7).
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
and a sixth, `builds-sync`, built
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
| `builds-sync` | skill plus command; registers hooks (like `rrc`) | nothing; `age` |
| `voice-decision-pipeline` | command | `embedding-lib`; writes the data format |
| `voice-runtime` | skill | `embedding-lib`; reads the data format |
| `decision-runtime` | command, with hook registrations | `embedding-lib` (the lookup's similarity search), `question-store`; reads the data format |

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
  adapters (which also mirror open questions as GSD blockers), the lookup
  and the decision log (the question store is in
  (record a question; the agent carries on with independent work), notify
  (push, session), collect (every channel's answer written back to
  one record; first answer wins, the others are told), hand back (waiting
  work reads the answer), show (the session command).
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
  the voice model can start from the Slack export already on disk.
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
  The Bitbucket extract finds from the PR list which PRs the owner authored, commented on or approved, and
  fetches only those, leaving out PRs the owner was only added to as a reviewer.
  `voice-decision-pipeline` saves each finished repo of a Bitbucket
  extract, so a stopped run resumes at the next repo, and prints a progress
  line per repo. It also has:
  - The audience mapping page (§3.2) on the review page: each Slack
    conversation the inputs leave without an audience, with its members and
    the owner's longest messages there, and a button per audience. A change
    holds batches until `extract slack` and `anonymise` have run again.
  - Group DM names (`mpdm-<handle>--<handle>-N`) anonymised handle by
    handle, however short a handle is.
  - A leak check at the end of `anonymise`: every real name, handle, email
    and client name the pipeline knows, searched for in every anonymised
    record, with what it finds on the review page.
  - A name only spaCy finds is replaced wherever it appears once spaCy has
    tagged it anywhere: a single word as written, or
    in any case inside a URL or path, a name of two or more words in any
    case; a client or kept product of the same name stays that.
  - `forget` works before `anonymise`, from the sources' own people lists,
    and takes a Bitbucket repo or PR; a forgotten PR stays out of later
    extracts.
  - `show bitbucket`, the owner's Bitbucket items as text, kept in the state.
  - A `~/.netrc` that Python refuses is reported as that.
  - Single words only spaCy took for a name go on the review page's Names
    (§2.3), with batches held until each is marked and `anonymise` has run
    again.
  - First names are matched in any case, since a first name typed in lower
    case is still the name; a first name two people share
    becomes their role (`colleague`, or `person` when
    their roles differ).
  - Dictionary keys inside source fields are anonymised: a transcript's
    answers and annotations are keyed by the question's text. Reaction
    names are too, since a custom emoji can carry a name.
  - The leak check searches only what is sent (text, source fields with
    their keys, reactions, author), not the pipeline's own words such as
    the source name and tag types; counts a single spaCy word only once it
    is marked a name; and searches for shared first names.
  - Python runs unbuffered, so progress lines reach the log as they happen.
  A form spaCy tags as a person that is a client or kept product's name once spaces, hyphens,
  dots and underscores are dropped is replaced as that client or product.
  The Mining list leaves terms off and each term carries a suggestion.
  - Left off: fragments spaCy tagged that can't be a name (no letters, one
    or two letters or digits, punctuation at either end, markup, a line
    break); terms that appear in three or more clients' conversations; and
    terms that the corpus no longer holds (each run
    writes the list afresh).
  - Suggested strike: a term starting in lower case, or one made of
    ordinary words (each seen in lower case at least twice in the corpus,
    outside URLs) that isn't concentrated in one client.
  - Suggested keep: a term that isn't an ordinary word and either sits
    mostly in one client's conversations, or appears in one client's
    conversations only with at least half its uses there.
  - The rest are left to check by hand and are listed first on the page,
    which can apply every open suggestion at once.
  The Mining page is split into tabs: check by hand, suggested keep, suggested strike and
  decided, each with its count. Only the open section's undecided terms are
  listed, each with its suggestion as a coloured badge; a term leaves the
  list as soon as it is decided, and each section has its own keep-all and
  strike-all.
  A client or kept product name's pattern allows up to three separators between its words, so a name written with
  a spaced hyphen (`X - Y`) matches. The leak check blanks the pipeline's
  pseudonyms before searching, so a word before one plus its role
  (`acme product-07`) is not taken for a kept product's name.
  A URL whose host isn't on a public list (code hosts, package registries, Q&A sites,
  platform, infrastructure and payment docs, `localhost`) becomes `[url]`,
  path and all; a public one stays, names in its path replaced.
  The review page takes a client name the lists and mining
  missed, with its other spellings and identifiers, all one pseudonym.
  The leak check fails on a private URL, and
  batches wait for `anonymise` after a client is added or the host list
  changes. A batch drawn before the last `anonymise` can only be rejected.
  An ordinary word is one in a dictionary built from SCOWL
  (lower-case entries) at release, never committed. Every text a record
  sends is mined, source fields included; spaCy tags them all but tool
  calls, paths, branch names, links and file names. Spellings that differ
  only in case are one candidate with one decision.
- **Mining skips code**: fenced and
  inline code, log and stack-trace lines, and the code under Bitbucket
  inline comments (the `inline` field) are not searched by spaCy or the
  dictionary route. Only code marked by its writer or fetched as code is
  skipped; no guess at code-like lines. Code is still sent to the decision
  analysis with known names replaced, so a name that appears only in code
  and is on no list goes out as written.
  - A public URL whose host label is a kept product or a client spelling
    gets the pseudonym inside its host and is sent that way; the leak
    check accepts a host holding a pseudonym rather than reading it as a
    private URL.
  - Keep on the Mining page means replace. A kept term gets an entry in
    the append-only map, and every product entry in the map is replaced
    whatever its decision says now, so striking a term after keeping it
    has no effect. Reversing a
    keep needs its decision and map entry edited in the state.
  - A term decided in an earlier run and not listed in the current one
    Such terms get their own section on the Mining page, apart from
    Decided, each with its decision, so a struck one can be kept.
  - The leak page shows only anonymised snippets, so a pseudonymised host
    can't be traced to its term there. So each
    hit's snippet notes the real term behind every pseudonym in it, read
    from the map on this machine; the page stays local and Claude still
    never reads it.
  - Batches are rejected, and a source's review stopped, only on the
    review page; there is no command for either, and none is added.
  - The leak check reads an iOS app-group identifier
    (`group.com.<client>.<app>`, the client already a pseudonym) as the
    private URL host `group.com`.;
    a rebuild that stops on such a hit is cleared by hand.
  The voice steps, `builds-sync` and `voice-runtime` are tested on made-up fixtures with
  stand-ins for `claude`, `age` and the embedding model. Design choices in
  the build:
  - Model calls go through `claude -p` on the logged-in Claude Code
    account (no API key is used; §6), with structured output
    against a JSON schema, checked again before use. Tools, settings files,
    MCP servers, slash commands and session files are turned off, which
    leaves about 1,100 tokens of overhead per call.
  - Labelling sends 20 items a call. The labelling prompt is changed
    through `labelling-notes.md` in the pipeline's state; `voice label
    --redo <purposes>` sends again the items either model gave one of them.
  - The guide is written by the drafting model, Opus 5.5.
  - The guide and the exemplars are written from the pool without the
    holdouts, so validation drafts against messages neither has seen; the
    build ships the same pool.
  - The pass's confidence figure comes from a Dirichlet over the owner's right,
    wrong and can't-tell counts; the spotting rate is right minus wrong
    over pairs, with its 95% range from the same draws.
  - In the blind pairs, the grade is asked after the pick, once the page
    says which side was the draft.
  - `voice publish` refuses until the label check and the validation run
    have passed.
  - The build format, the `builds-sync` library (`publish_build`,
    `read_live`) and the `voice-runtime install-build` call between them
    are fixed in each package's README.
  Not built yet: the §3.8 upkeep (matching edited drafts to sent messages,
  the review sessions), which needs drafts that only exist once
  `voice-runtime` is in use; and item 23's CLAUDE.md line.
  Leak gate: the voice steps that send
  (`voice label`, `voice guide`, `voice validate`) refuse while
  `leak-report.json` has a term neither fixed nor cleared by hand, as §8.5
  asks of a rebuild. The leak page marks a hit cleared by hand (the
  app-group host `group.com`, above, is one); the mark
  keeps the count found when it was made, and a term found more times
  later stops sending again. The build's own leak check honours the marks
  by term. Refusals name kinds and counts, never a term.
  Usage limits: `model.py` recognises a limit by fixed
  phrases, Claude Code's "You've hit your 5-hour limit" among them.
  The phrases cover the 5-hour and
  weekly limits, which stop the pass cleanly with exit 6. Finished batches
  are kept either way, and the same command resumes.
  Label redo: `voice label --redo` runs in both passes under one prompt.
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
  - **Builds on every machine**: the corpus is
    extracted, anonymised and built once, on this machine. Each build is
    committed to a version-controlled builds repo, and every machine the owner
    uses installs `voice-runtime` and
    `decision-runtime` from it, so all of them run the same build; no other
    machine extracts or builds. Because the builds repo is cloned to each
    machine and keeps its history, nothing real may be in a build: the leak
    check runs on the built files (voice guide, exemplars, principles and
    their evidence quotes, tech positions, client constraints, cases, the
    agent block) before every commit, and a failure stops the commit.
    How code is handled: §8.0 item 23a.
  - **Builds repo**:
    - A private GitHub repo, separate from this public one, named in
      `build-inputs.json` (`builds_repo`). Everything in it is encrypted with
      `age` under one key, except a plaintext `README.md` that holds no
      content. The pipeline and every machine refuse a push if any other
      tracked file doesn't end in `.age`.
    - Layout: `builds/<build-time>.tar.age`, one per build (the voice and
      decision files and their manifests), and
      `live/<hostname>/<package>/<push-time>.jsonl.age`. Only the pipeline
      writes `builds/`; each machine writes only its own `live/` directory,
      named by its hostname.
    - The embedding index is not in the repo. Each machine embeds the
      exemplars at install with `embedding-lib`, reusing the previous
      build's rows by a hash of each pair's text, so only new or changed
      pairs are embedded; a change in `embedding-lib`'s identity throws the
      rows away and re-embeds them all. The repo then grows by each build's
      text files only.
    - Each machine holds the key at `~/.config/age/builds.key`, mode 600,
      outside every package's directories, copied there by hand, with a
      backup copy kept off the machines.
    - Live files that travel: `drafts.jsonl` (`voice-runtime`),
      `decision-log.jsonl` (`decision-runtime`) and `questions.jsonl`
      (`question-store`): the evidence the pipeline reads. The
      reviewed-changes record, gate state and question delivery state stay
      on their machine. A repo worked on from two machines is reviewed on
      each.
    - Segments: each push stores only the records added since the last
      push. So `questions.jsonl` is append-only: an answer is a new line,
      and the newest line per question id wins. The pipeline joins every
      machine's segments by push time (this machine's included), drops
      repeated records by id (a lost push position re-sends them), and
      applies the struck list, so a forgotten person's records never
      re-enter the corpus. Their segments stay in the repo's history,
      readable only with the key; history is never rewritten for
      `forget`.
  - **`builds-sync`** is of the skill kind and
    installs, as `repo-remote-control-session` does, a skill directory, an
    executable in `~/.local/bin`, and hooks registered from it. It owns the clone, the key path, `age` and every
    pull, commit and push; the pipeline and the three runtimes load its
    library (Coupling, above). Its state records the clone's location,
    asked once at first install, and where each live file's last push
    stopped.
    - Push: a `SessionEnd` hook pushes this machine's new records, and
      `builds-sync push` does the same on demand. A lock keeps two
      sessions ending together from colliding. An offline or killed
      session loses nothing: the next push carries everything since.
    - Update check: a `SessionStart` hook shows the notice the last check
      left (a newer build in the repo than the one installed) and starts
      the next check in the background, at most once a day, by a day stamp
      written before the `git fetch` (the kit's `update-check.sh` does the same);
      `builds-sync check --force` checks at once.
    - Nothing installs it automatically: `builds-sync install`, or the skill, which
      runs it in the background and watches its log
      (`/tmp/builds-sync-install.log`). Nothing installs on its own.
      `install <build-time>` installs an older build; there is no pinning.
      Nothing records which build each machine runs; `builds-sync status`
      on a machine says.
    - Each install writes a new `builds/<build-time>/` beside the current
      one and writes `manifest.json` last, so the previous build is used
      until the new one is complete, then deleted. Before a machine's
      first install finishes there is no build; the runtimes then behave
      as after any refusal (below).
  - The pipeline writes each build into the builds repo through
    `builds-sync` and, at the start of each build, reads every machine's
    live-file segments from it into the corpus. The runtimes never read the pipeline's
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
    so (kept for a machine's first install).
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
  notes; the plugin neither generates nor bundles the file. `decision-runtime`
  doesn't write one: its start-up block already
  reaches every session, and the gates enforce marked paths.

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
    Other machines: only this one's transcripts; cloud
    sessions not a source (§2.1). Bitbucket:
    a hard rule, repos last updated before `bitbucket.CUTOFF` left out
    Bitbucket: PRs the owner authored, commented on or
    approved, not those they were only added to as a reviewer, covering
    every PR (§2.1, §4.14).
    `.planning/` repos without `config.json` count as GSD repos
    (§1). The repos are the picked list in the
    pipeline's inputs (§2.1). Bot messages kept only as tagged context, channel events
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

**Next – before anything else is built, released or anonymised**
37. Builds on every machine (§5).
    The builds repo
    and `builds-sync` in §5. Code handling is in Stage 2.

**Stage 2 – voice model and `voice-runtime`** (with `builds-sync`; §5)
17. Sonnet 5.5 labels, Opus 5.5 is the second labeller (a
    different model), Opus 5.5 drafts, Fable 5.2 judges
    (§3.4, §3.7).
18. Every review page runs on the pipeline's local review
    server, as the Stage 1 pages do; the blind-pair page writes each
    answer to its progress file in the state (§3.7).
19. The owner also reviews the judge's 20 worst-scored drafts and 10
    random ones, on top of the 60 blind pairs (§3.7).
20. A rules file in the pipeline's state, copied into the guide
    and winning over corpus rules (§3.5).
21. No 1:1 split (§3.2); the never-say list is measured against
    colleagues' phrases and a fixed committed list; thin cells fill from
    the same audience by similarity (§3.5).
22. Drafting time: see §3.1 and §3.8.
23. The exact CLAUDE.md line that loads the skill (§8.2); last, before voice
    goes live.
23a. Code in the corpus.
    Mining skips code (§5); code is sent with known names
    replaced; exemplars store `[code]` in its place (§3.5); cases and
    evidence quotes keep it (§4.10).

**Stage 3 – `question-store`**
24. §8.4: see §4.7.
25. Hooks: see §4.7.

**Stage 4 – decision model and `decision-runtime`**
26. Lookup: see §4.3.
27. Extraction weighting: see §4.9.
28. Approved entries and plan comments: see §4.8 and §4.10.
29. Gates: see §4.4.
30. Reviewers: see §2.3 and §4.5.
31. Coverage: settled in §4.4 and §4.5; the
    `SubagentStart` delivery test is a build task (§8.3). Other machines: §5 (Builds on
    every machine.
32. Before validation: settled in §4.5 and §5.
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


### 8.2 Voice

- The exact line added to `~/.claude/CLAUDE.md` to load the voice skill
  (the owner approves the wording; CLAUDE.md is theirs).
- Whether subagents receive the `~/.claude/CLAUDE.md` line that loads the
  voice skill, and a test that a drafting subagent loads it (§3.6).
  Not checked. `/code-review --comment` may word its comments in reviewer
  subagents; also not checked.

### 8.3 Decisions

- Which hook event catches `/opsx:apply` (a slash command is not a tool call
  unless run through the Skill tool; `UserPromptSubmit`/`UserPromptExpansion`
  are the candidates) — not checked. Deferred with the other OpenSpec
  points until the owner starts using it.
- No GSD setting narrows `bm-executor`'s Rules 1–3 (checked in GSD 5.1.0's
  `agents/bm-executor.md`): its only config reads are
  `workflow._auto_chain_active` and `workflow.auto_advance`. Rule 3 already
  excludes package-manager installs. The one lever is a project
  `./CLAUDE.md`, which the executor treats as hard constraints over plan
  instructions; `decision-runtime` doesn't write to work repos'
  `CLAUDE.md` files, which colleagues share. L116 also forbids ad-hoc pauses to ask about
  mechanics (APPENDIX D.3).

- Whether OpenSpec runs its own agents (its docs don't say). Deferred until
  the owner starts using it.
- Sessions this machine's hooks don't reach: claude.ai cloud sessions and
  any other machine.
  Per §5 (Builds on every machine), the runtimes are installed on
  each of the owner's machines and use the one build made here. claude.ai cloud
  sessions are not covered and not used. They need a
  GitHub-connected account, clone only GitHub repos, and load none of
  `~/.claude`. Sessions started from claude.ai run through Remote Control
  servers on the owner's machines, which the runtimes cover.

- Workflow agents launched with `agentType` report that type, not
  `workflow-subagent` (APPENDIX D.1), which the `SubagentStart` skip list
  matches on.
- A test that the `SubagentStart` block's `additionalContext` reaches the
  agent, for GSD plugin agents and workflow agents. That the event fires for
  both is shown by the saved hook log (§7); delivery of the context was not
  tested.
- Origin weighting (§4.9) needs the transcript's AskUserQuestion answers,
  because GSD's `CONTEXT.md` records only the final answer (§7).
- Which GSD checkpoints auto-approve (checked in GSD 5.1.0):
  with `workflow.auto_advance` or `workflow._auto_chain_active` true, and
  `auto_advance` defaults to true, `checkpoint:human-verify` auto-approves
  except `gate="blocking-human"` and package-legitimacy checks;
  `checkpoint:decision` auto-selects its first option (logged "⚡
  Auto-selected"); `checkpoint:human-action` still stops
  (`references/checkpoints.md` L11, `agents/bm-executor.md` L315).
  `decision-runtime`'s GSD adapter looks up each auto-selected decision
  a usable principle picking the same option lets it
  proceed, logged; a principle pointing elsewhere, or none, parks it for
  the owner; at trust level 0 every one is parked. Auto-advance stays on.
- GSD's own stop-and-ask checkpoints: a Rule 4 stop
  (an architectural change: what was found, proposed change, why, impact,
  alternatives — §7) becomes a parked question in `question-store`, pushed
  and listed in `/questions`, its answer logged as an asked entry. The
  package-legitimacy `checkpoint:human-verify` ("verified" with the package
  name, or "abort"; APPENDIX D.3) stays in GSD's own flow, its answer
  logged.
- `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` (§7) bears on the model-choice items
  above and in §8.2.
- grill-with-docs may ask questions with no recommendations when a
  dependency fails to load (the aihero.dev page describes this failure mode
  without saying more), which would undercut §4.6's reliance
  on recommended answers shaped by the `SessionStart` block. Unchecked
  beyond that page. Deferred with the other grill-with-docs points until it
  is installed.
- OpenSpec lets any artifact change at any time, so edits to
  `openspec/changes/<change>/` after `/opsx:apply` aren't seen by the plan
  reviewer. The end-of-turn review reads spec files as decisions (§4.5),
  so later edits are caught there; the rest waits until the owner starts using
  OpenSpec.
- How grill-with-docs records are weighted (§4.9). `grilling` asks a whole
  numbered round, each question with a recommended answer that "yes"
  accepts, so a round answered "yes" is close to bulk acceptance. An ADR is
  written only when the owner says yes to it, and `GLOSSARY.md` is updated
  without asking. Whether these count as the owner's or as weak
  evidence is not decided.
  Deferred until the reader is added.

### 8.4 Questions to the owner (`question-store`)


### 8.5 Packaging and process

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
- Pipeline rebuilds are run by hand: the review page
  shows when enough new material has built up, with the command, and the owner
  runs it in their own shell; a failing leak check stops it before anything
  is sent.
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

1. The Bitbucket token's scopes: none to add; it has `read:repository`.
   `~/.netrc` has to be readable by its owner only (mode 600): Python's
   `netrc` module refuses any other, though `curl` reads it.
2. Pick the `oneiota` repos.
3. Review the first anonymised batches, until the owner says stop.
4. Check the audience mapping, the label sample and the sample of
   second-model disagreements (§3.4); confirm inferred reasons
   and bulk-accepted records. The group DMs the hand-written list left
   open are assigned on the mapping page.
5. Grade the 60 blind voice pairs (more whenever the owner wants).
6. Grade every held-back decision case (at least 52 per kind, §4.11).
7. Decide every old-against-new conflict before an orchestrator gets the
   decision model.
8. Run the install command for every package. Each installs from its
   release tarball, and where the installer places it (`~/.claude/skills/
   <name>`, `~/.claude/<name>`, hook registrations in
   `~/.claude/settings.json`) is outside Claude's Bash sandbox.
9. Move the decision model up trust levels.
10. Create the private builds repo (`builds_repo` in `build-inputs.json`), give the
    the other machines push access to it, copy the `age` key to
    each machine and to a backup kept off the machines (§5).
