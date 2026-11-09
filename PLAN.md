# Voice and decision models — plan

Planned in one session on 9 Nov 2026. Nothing is built yet. Decisions in
§1–§6 were made by James in that session, except figures that came from
Claude's option text and were never discussed on their own (listed in §8.2),
Claude's own design choices that were never put to James (§8.3), and items
marked proposed, ambiguous or open where they stand (listed in §8.1 and
§8.4–§8.8). §7 holds checked facts, not decisions. Everything undecided is in
§8.

Evidence, comparisons, rejected options and references are in `APPENDIX.md`
beside this file.

Two models, built from James's own writing and decisions:

1. **Voice model** — so Claude can draft Slack messages, PR descriptions, PR
   review comments and Jira comments in James's voice. Every draft goes to
   James for approval before anything is sent.
2. **Decision model** — so orchestrators and agents can settle some technical
   questions the way James would, and ask him about the rest.

The two share only the sources and corpus preparation. Everything else —
uses, analysis, output, loading, validation, upkeep — is planned separately.

---

## 1. Shared: sources

| Source | Used for | Scope |
|---|---|---|
| Slack export (JSON, 2020–2026) | voice and decisions | 75 conversations, 17,319 of James's messages, after the exclusions below |
| Bitbucket PR descriptions and comments | voice (technical team audience) and code-level decisions (what James approves, rejects and asks to be changed — Claude's description) | `oneiota` repos only; repos with no update since 2018 are normally left out (James's guideline, not a hard cut), applied when the repos are picked (whether 2018 itself is kept: §8.4); the exact repos are picked when the pipeline is run |
| Claude Code transcripts (`~/.claude/projects/*/*.jsonl`) | technical decisions only — never voice (James's choice: technical decisions only; prompts are written to Claude, not colleagues). Probably the strongest decision source, because corrections there state a decision outright | everything kept from now on |
| GSD written records: decisions in `.planning/STATE.md`, phase `CONTEXT.md` | decisions, weighted by origin (§4.9) | 6 GSD repos with `.planning/config.json` today (8 repos have `.planning/`; whether the other 2 count: §8.4). Their `STATE.md` files mention "decisions" (word match; the sections themselves were not checked) |
| grill-with-docs ADRs (`docs/adr/`) and `GLOSSARY.md` | decisions, weighted by origin (included from option text, §8.2) | none found at repo roots (nested ones not searched); grill-with-docs isn't installed; used if they appear. Its decisions that don't pass the three ADR tests stay only in the conversation, so they reach the model through transcripts |
| `/gsd:profile-user` output | decisions | run on anonymised copies only (§2.3) |

Conversation-level values — conversation ids, names, the struck and kept
lists, audience assignments, and the candidate client names for the
anonymiser — are the pipeline's input, held with real names in
`build-inputs.json` on James's machine only.

Left out:

- Jira — dropped as a source. Jira comments still get the voice model as an
  output.
- Email and documents — offered by Claude as possible sources; James named
  only Jira, Bitbucket PRs and Claude Code transcripts, so neither is used.
- Anything outside the export folder James gave.
- Struck-out conversations: nine (282 of James's messages).
- New Slack data after the export ends: none expected for now. The pipeline
  accepts a later slackdump export through the same local steps if one is ever
  run; the Slack connector route stays open but unused (it would send real
  names to the API before anonymising).


## 2. Shared: corpus preparation

### 2.1 Context kept per item

- **Slack:** each of James's messages keeps its thread if threaded; otherwise
  the messages before it in that conversation from the previous 2 hours (up to
  10), and the same after it (up to 10), plus emoji reactions. (The cap of 10
  is from option text, §8.2.) The "after"
  context gives decision outcomes.
- **Pasted code, logs, links and attachments:** kept and tagged. The voice
  analysis skips them; the decision analysis reads them. Links kept as URLs,
  attachments as file names.
- **Transcripts:** each typed prompt plus the text of Claude's reply before
  it, a one-line summary per tool call (which file, which command),
  AskUserQuestion questions and answers, project name and date. Claude's
  preceding reply is kept because it is usually what James was correcting.
- **Bitbucket:** each comment with its PR title, description and thread.
  Inline comments get the code under them from the API; James adds
  `read:repository` to the Bitbucket token when the pipeline is run.
  `~/.claude/auth-recipes/bitbucket.md` needs its scopes and gotchas 5 and 8
  updated at the same time.

### 2.2 Storage

- Corpus directory: `~/claude-sandbox/voice-decisions-data`, writable by
  Claude's Bash tool. A local git repo since 9 Nov 2026 (James's choice,
  committed with the gitignore), with no remote. Corpus data will need to be
  gitignored before any is written there. About 20 MB, each message stored
  once.
- Real names are kept in the stored corpus, so it stays readable and
  searchable.
- No data ever goes into a package repo or release.

### 2.3 Privacy: anonymise before anything is sent

- Anything sent to the Anthropic API is anonymised and redacted first, by
  local scripts. The mapping stays local, so results can be turned back into
  real names on this machine.
- Anonymising uses lists (every name in `users.json`, Slack user ids and
  @mentions, client names from channel and repo names, email addresses,
  phone numbers, client-domain URLs) **plus spaCy** named-entity tagging for
  names the lists miss (where spaCy's environment lives is open — §8.4).
  spaCy also tags some ordinary words as names and blanks them. Product,
  store and project names that identify a client on their own
  get through unless they are added to the replacement list; which ones to
  add is not decided (§8.4).
- Proposed, not separately agreed: replacements are stable pseudonyms with a
  role tag (e.g. `colleague-07`, `client-pm-02`) and clients become codes
  (§8.4).
- Credentials (AWS, Slack and Bitbucket keys, JWTs, private keys,
  `password=` lines) are pattern-matched and replaced with
  `[REDACTED:<type>]` while building the corpus. Findings are logged by type
  and count, never value.
- The first batches sent are reviewed together with James before they go
  (about 50 anonymised messages each, every replacement highlighted). Review
  continues until James says stop.
- Exemplars loaded into drafting prompts are sent anonymised: the pipeline
  stores a pre-anonymised copy of each exemplar at build time, so
  `voice-runtime` never runs the anonymiser. (This follows the
  anonymise-before-sending rule; James's earlier "real names everywhere"
  answer covered exemplars too, so which holds is open — §8.5.)
- Accepted exception: Slack questions and replies go through the Slack
  connector with real names (§4.7).
- Not covered by this rule, and not discussed: reviewer hooks send code diffs
  from the working repo to the API un-anonymised (they aren't corpus data).
- Not settled: the built outputs (voice guide, exemplars, principles,
  evidence quotes, client constraints). The names option James answered
  said quotes in prompts would name real people; whether
  anonymise-before-sending covers them is open (§8.5).
- `/gsd:profile-user` is not run as shipped (its agent reads raw transcript
  samples). Its steps are run by hand: run the sampler, anonymise the sample,
  give the anonymised file to `bm-user-profiler`, keep the output in the data
  directory, and answer "neither" to writing it into a CLAUDE.md. GSD's plugin
  files are not edited.

### 2.4 Time

- No cut-off for Slack or transcripts. Bitbucket keeps its own rule (§1).
- When an older and a newer position disagree, both are kept and marked
  unresolved. Once the work is finished, every such conflict is listed for
  James to decide, and no orchestrator gets the decision model until he has.

---

## 3. Voice plan

### 3.1 Uses

Slack messages, PR descriptions, PR review comments, Jira comments. Jira
comments keep their structure from `~/.claude/reference/jira-comments.md`;
how that file's own wording rules (e.g. no second person, shorter) sit
against the voice model is open (§8.5). Every draft goes to James for
approval before anything is sent.

Slack drafts go out through the Slack connector, which can draft and send
messages (Claude's survey of voice uses). Sending still needs James's
approval of the exact text.

### 3.2 Audiences

| Audience | Conversations |
|---|---|
| Clients | client channels |
| Project team | internal project channels |
| Technical team | technical channels, all Bitbucket PR content |
| Senior / management | senior and management channels, group DMs with the same people |
| 1:1 colleagues | one-to-one DMs |

Each conversation is assigned by its name and members; James checks the
mapping. Any other internal channel not covered goes to the project team
(James's choice, because those channels are less technical). Unassigned group
DMs: §8.4.

### 3.3 Purposes

Each message can carry several purposes, listed in the order they appear:
push back / disagree; decline; ask / request; chase / nudge; status / update;
explain / instruct; approve / agree; own a mistake / apologise; thank /
praise; escalate; small talk / humour. Anything else is "other". The guide
also records how purposes are combined (e.g. news before the objection). A
message counts in every audience-and-purpose cell it carries, so thin cells
(clients especially) gain examples; label checks cover every label on a
sampled message. Merges were offered (push back + decline, chase + ask) and
declined — all 11 kept.

Why purposes (Claude's reasons): James writes "no, we're not doing that"
differently from "can you look at this", even to the same person. Labels
let exemplars match what a draft has to do, and let the guide state rules
per purpose (e.g. pushing back on a client against pushing back on a
developer).

### 3.4 Analysis and checking

- Local statistics (no API): length, capitalisation, punctuation, openings,
  sign-offs, emoji, spelling, common words and phrases.
- Audience comes from the message's conversation (the §3.2 mapping, worked
  out locally, checked by James); the label-check option described the
  model assigning each message that audience. A model labels purposes on
  anonymised messages.
- Checking, in parallel: James checks a sample of about 60 labelled messages
  spread across audiences and purposes, and a second model labels messages
  blind; its disagreements come to James too. Scope is pending James's
  confirmation (§8.1): it was taken as all
  ~17k (the label-check option said "the same messages"; the cost step
  costed all ~17k, offered a sample-only cut, and James accepted the costs
  with no cuts — §6), and Claude asked James on 9 Nov whether that matches
  what he meant. Over
  about 10% wrong, the labelling prompt is changed and rerun (threshold from
  option text — see §8.2).

### 3.5 Output

- A voice guide, split by audience and purpose.
- A measured "never say" list: phrases, words and habits common in generic
  business writing that James uses rarely or never (e.g. "Hope this helps",
  "Kind regards", exclamation marks to clients), each with his actual count;
  built locally, no API.
- Exemplars drawn from the whole labelled corpus, minus very short messages
  (e.g. "ok", "thanks") and messages that are mostly code or logs.
- Exemplar choice uses both: labels narrow the pool to the right audience and
  purposes, then similarity search picks the closest 3–5 (figure from option
  text, §8.2). Similarity uses
  `BAAI/bge-base-en-v1.5`, run locally on the CPU (sentence-transformers, CPU
  PyTorch), so nothing is sent for the search. Messages are embedded with a
  short slice of context (the message plus the message it answers; Claude's
  design, never asked — §8.3), within the model's 512-token limit.
- Guide plus exemplars, not either alone: rules alone give flatter drafts;
  examples alone carry over phrasing tied to old clients and people.
- For drafts to other people, James's voice wins over the CLAUDE.md writing
  rules. The CLAUDE.md rules keep governing everything Claude writes to
  James. So, for example, the CLAUDE.md ban on apologies does not apply to
  an outward draft where James would apologise (Claude's example when the
  question was raised).

### 3.6 Loading

A skill holds the guide and calls the exemplar search — a local script that
takes audience, purposes and a description of the situation and returns the
3–5 closest messages, anonymised (as §2.3 assumes; open, §8.5). A line in
`~/.claude/CLAUDE.md` says to load it before any draft for other people, the
way `jira-comments.md` is loaded now; the line is there because a skill alone
loads only when its description matches, which misses some drafts. All four
uses run in the main session, not in subagents, so the skill only needs to
reach the main session (Claude's statement, never asked — §8.3).

### 3.7 Validation

- About 10% of messages are held back from the exemplar pool. For each, a
  draft is written from its context, audience and purposes only.
- In parallel: James sees 60 blind pairs (his real message and the draft,
  shuffled; spread across the five audiences and 11 purposes, about 12 per
  audience, about an hour), picks which is his and grades each draft 1–5 for
  "would send as is", with the option to keep reviewing more at any time (the
  review page saves progress between sittings — Claude's design, §8.3); and
  a model judge compares
  every draft with the real message and scores it. James's graded pairs also
  show where the model judge disagrees with him, which is how the judge's
  scores on the other ~1,700 drafts are trusted. The judge option James
  chose also said he reviews the judge's worst-scored drafts and a random few;
  whether he does, on top of the 60 pairs, is open (§8.5).
- Pass: James picks wrong about 40% of the time or more, and most drafts score
  4 or higher (from option text — see §8.2).

### 3.8 Upkeep

- The skill saves each draft and the version James approved, and keeps them.
- Regular review sessions with James feed them back in.
- Approved versions do not join the exemplar pool on their own. James
  changed the recommended "Record and add" (approved versions join the pool,
  recurring edits listed for him to make into rules) to recording and keeping
  them; they go in only through the review sessions.

---

## 4. Decision plan

### 4.1 What may be decided alone

- Orchestrators and agents may decide alone on: **libraries and tooling,
  code structure, test approach.** Everything else — scope cuts included —
  goes to James.
- What the three kinds mean (from the option text James ticked): libraries
  and tooling — which package, framework or tool to use, where the model has
  James's positions; code structure — where code lives, naming, patterns,
  how modules split; test approach — what to test, at what level, with which
  tools. Small scope cuts (not ticked): dropping or deferring a minor piece
  of a phase to finish the rest.
- An agent decides alone only if the kind is allowed, a usable principle
  covers the question, and no client constraint contradicts it. Otherwise it
  asks. (The client-constraint condition is Claude's, never asked — §8.3.)
- Within those three kinds, if nothing in the model covers the question, ask
  James. The answer is recorded and joins the model.
- Claude's first proposal also had small scope cuts decided alone, and named
  ask-categories (anything a client sees, costs money, deletes data, or is
  hard-to-reverse architecture); James dropped scope cuts. The early
  "escalation list" idea is replaced by "ask when nothing covers it" and the
  evidence bar. Claude's reason for the list, which carries over to the ask
  rule: a confident wrong guess costs more than a question.
- Claude's recommendations in ordinary sessions follow the model and name the
  principle; where none applies, Claude says so and gives its own. Why: a
  recommendation that follows James's reasoning saves a round of correction.

### 4.2 Asking mid-run (park rule)

- The question is parked. Current work that doesn't depend on it carries on;
  current work that does depend on it stops; no new work starts until James
  answers.
- James's answer applies at once to that exact question in that client or
  project, so it isn't asked again (the client-or-project scope is from
  option text, §8.2). Turning it into a general principle waits for a review
  session.

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
| Logging gate: a `SubagentStop` and `Stop` hook refuses to let an agent finish while it has decisions it hasn't logged. **Ambiguous:** it was in Claude's first full recommendation, but the recap James accepted listed only the dependency, test-framework and path gates — see §8.6 | enforced (that it records, not that it decided well) | every session and subagent |
| `SubagentStart` block | advisory | every subagent, plugin and workflow agents included (agents that never decide can be skipped by type; which ones, Explore included, is open — §8.6). Observed firing for workflow agents and for a GSD plugin agent (`gsd:bm-executor`; saved hook log, APPENDIX D.2). That the block's context reaches the agent is not tested for either — §8.6 |
| `SessionStart` block (instead of a CLAUDE.md section, so subagents don't get it twice) | advisory | the main session, every session (not just GSD repos, because Claude's recommendations in ordinary sessions follow the model — §4.1) |

Fallback: if tests show a particular agent ignoring the `SubagentStart`
block, that agent alone moves to a `PreToolUse` hook on the Agent tool that
appends the block to its prompt (in the question text James answered by
choosing the recommendation, §8.2). Only one hook may ever modify Agent input
(Claude's rule, never asked — §8.3).

James's criteria for choosing the layers: enforcement first, then little
upkeep, then as little overlap between layers as possible.

Rejected: overriding GSD's agents with copies in `~/.claude/agents/` (heavy
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

Claude's recommendations in ordinary sessions (the fourth out-of-GSD kind
James put in scope) get no review point: Claude said they are already
handled, because they cite the principle (§4.1) and James chooses. Never
asked (§8.3).

- All review points share one per-repo record of what has been reviewed (last
  reviewed commit plus working-tree state), so nothing is checked twice —
  otherwise an `execute-phase` turn would re-review commits the
  after-each-plan check already passed, and a subagent's changes could be
  checked by both `SubagentStop` and the end-of-turn check. (Claude's design,
  never asked — §8.3.)
- Rejected: reviewing every commit (James ruled it out; no reason given
  — the table showed a few thousand checks and ~12–15M tokens a year and
  seconds on every commit), reviewing only at phase end or PR (too much
  rework), reviewing before each GSD wave (would duplicate the after-each-plan
  review).
- The same reviewer covers decisions made only in code, decisions an agent
  doesn't notice it's making, and GSD executor Rules 1–3 (auto-fix bugs, add
  missing critical functionality, fix blockers).
- What stays unprevented: a judgement call made in text inside a GSD step
  that the reviewer misses. James's review sessions catch it after the fact,
  as would a phase-end audit if one is built (§8.6).

### 4.6 Plan review

Why (Claude's reason): while a plan is being written nothing is edited, so
the end-of-turn review has no diff and the plan's choices go unchecked until
they're built. Chosen over "GSD only for now", in which plan mode and other
tools rely on the end-of-turn review after code is written.

One plan reviewer with a small adapter per tool, naming where the tool's plan
text lives and which event marks it final. The first adapters are the GSD
infrastructure skip and `ExitPlanMode`; each new tool costs one adapter
(from the option James chose):

- **GSD infrastructure skip:** `autonomous` skips discuss for phases it judges
  pure infrastructure and writes a minimal `CONTEXT.md`. A hook detects that
  minimal `CONTEXT.md` (which event, how it holds the run, and what it
  reviews at that point: §8.6) and holds the run until the planner's
  approach has been looked up; anything not covered is parked.
- **Claude Code plan mode:** a `PreToolUse` hook on `ExitPlanMode` (it
  receives `plan` and `planFilePath`) reviews the plan before James is asked
  to approve. Planning research runs in the built-in Plan and Explore agents:
  they skip CLAUDE.md, get the `SubagentStart` block unless their type is
  skipped (Explore may be — §8.6), and never trigger `SubagentStop` review
  (no edits). Proposed, never asked (§8.6): a
  `PostToolUse` hook logging the approved plan's decisions as James's, and
  putting uncovered decisions into the plan as open questions instead of
  `question-store`.
- **OpenSpec:** an adapter at `/opsx:apply`, reviewing
  `openspec/changes/<change>/` (`proposal.md`, `design.md`, `tasks.md`,
  `specs/`), added when James starts using it (from option text, §8.2).
- **grill-me / grill-with-docs:** no gate needed — they never decide
  (Claude's judgement, never asked — §8.3). Their
  recommended answers are shaped by the `SessionStart` block. Their
  fact-finding subagents (the skill says only "dispatch a sub-agent with a
  fresh context window"; that they don't edit is Claude's inference) get the
  `SubagentStart` block unless their type is skipped (§8.6); if they don't
  edit, `SubagentStop` review never fires. Neither is installed.

`workflow.skip_discuss` is already off everywhere (unset in all 6 local GSD
configs and in `~/.gsd/defaults.json`).

### 4.7 Questions to James

- Each question states the decision, the options, the principles that came
  close, and what work is waiting on it (from question text, §8.2).
- Channels: push notification (only tells James a question is waiting), the
  session itself (locally or through Remote Control), and a Slack DM to James
  with real names. Questions and replies go through the Slack connector, so
  their text reaches the API with real names — an accepted exception to §2.3.
  James's reason: it's a DM to himself in the company Slack, which already
  holds this material, and anonymised questions would be hard to answer from
  a phone.
- Every answer, from any channel, is written back to one local question
  record (a file in the data directory holding each question, its status, the
  answer, the channel it came from and when); first answer wins and the other
  channels are told (Slack gets a thread reply saying where it was answered;
  Claude's design, never asked — §8.3).
- One session command lists every question, open and answered, with the
  answer and the channel it came from.
- Open questions are mirrored to GSD blockers (`gsd_add_blocker`; resolved
  with `gsd_resolve_blocker`), so questions survive a restart and
  `autonomous`'s `handle_blocker` step stops at them before the next phase.
  That step offers retry, skip or stop rather than waiting for the answer;
  with `--interactive`, discuss for the next phase may already be running.
  How the park rule maps onto both is open (§8.6).

### 4.8 Decision log

- Every decision made alone is logged with the agent and the principle ids it
  relied on.
- Answers to parked questions are copied in as entries marked "asked". A
  changed answer gets a new entry that supersedes the old one, never an edit.
- `decision-runtime` writes the "asked" entry when it reads the answer to
  resume waiting work, citing the question id; `question-store` knows nothing
  of the log, so the dependency stays one-way. One log then feeds review
  sessions, rebuilds and trust-level stats.
- `decision-runtime` also logs every review block.
- James asked for answers to be copied into the log; the rest of this
  section (supersede rather than edit, who writes the "asked" entries,
  logging review blocks) is Claude's design, never asked (§8.3).

### 4.9 Extracting decisions

- A broad local filter (James's choice, so that fewer decisions are missed)
  picks candidates (threads weighing options, wording
  like "rather", "instead", "should we", PR comments asking for changes,
  transcript corrections). Not discussed with James: `[Rule N - Type]`
  deviation entries in GSD `SUMMARY.md` files as another candidate. All
  candidates are sent, plus a random 10% of the rest to measure what the
  filter misses (10% from option text, §8.2). If the sample shows the filter
  missing many, the filter is widened (from option text; no threshold set).
- Each case records the question, options, choice, reason and outcome.
- Reasons James never stated are inferred, tagged "inferred", and count only
  once James confirms them in a review session.
- Decisions James relayed (a client's or manager's call) are tagged with who
  they came from and kept as constraints for that client or project. Where he
  said he agreed, they also count as his.
- Written records are weighted by origin: answers James overrode or gave one
  by one count as his; recommendations accepted in bulk, and context written
  by infrastructure skips, are weak evidence until he confirms them.

### 4.10 Output

- Principles, each with dated evidence quotes, what it trades against, and
  when it was last seen — last-seen date because a position from, say, 2021
  may no longer hold.
- Priority order for settling conflicts between principles (e.g. speed
  against correctness, build against buy, a client's request against
  maintainability — Claude's examples).
- Tech positions on specific tools and platforms (Claude's examples:
  Flutter, Shopify), dated.
- Client constraints, per client or project.
- The contents option James ticked gave these examples: principle "prefer
  the platform's own service over a third-party one"; priority order
  "maintainability over delivery speed, except for client-facing
  deadlines"; tech positions on Flutter, Shopify, AWS services. It said each
  part is built from the confirmed decision cases. Examples only, not
  positions James has stated.
- Evidence bar ("3+ cases, 2+ settings"): a principle needs at least 3
  confirmed cases from at least 2 different projects or sources before an
  agent may act on it alone. Below that, James approves it before it's used;
  above the bar it counts as decided. The chosen
  option's text also said "Principles you confirm directly in a review
  session pass regardless" — this conflicts with §4.12
  listing "use approved below-bar principles alone" as a later step (§8.2).
- Format (from Claude's option text): a markdown record with stable principle
  ids, plus a lookup script.

### 4.11 Validation

- About 10% of confirmed cases are held back and predicted from the question,
  options and context alone. Outcomes: right, wrong, or correct refusal (from
  question text, §8.2).
  Why refusals don't count against the model (Claude's reasoning when it
  proposed validation): a confident wrong prediction is the failure that
  matters; a refusal is safe, because the question just reaches James.
- Grading in parallel: a model judge scores every prediction against James's
  real choice and stated reason; James grades a sample spread across decision
  kinds, plus every case the judge marks wrong.
- Machinery tests: every deciding agent (`bm-executor`, `bm-planner`,
  `bm-plan-checker`, `bm-advisor-researcher`, `bm-framework-selector`,
  workflow agents, the main session — list from Claude's proposal) parks a
  decision outside the three kinds; each review point sends back a planted
  bad decision; the question record delivers to all three channels and returns
  answers.
- Starting bar (all of): no confident wrong predictions in James's graded
  sample; at least 90% right among predictions made (refusals excluded — the
  90% was an "e.g." in option text, §8.2); James's sign-off; every machinery
  test passing. Each confident wrong is traced to its principle, fixed, and
  the sample regraded (from option text, §8.2).

### 4.12 Trust levels

- **Level 0 — shadow:** the model predicts at every decision, but
  orchestrators still ask James, showing the prediction. Starts here after
  passing.
- **Level 1:** decides alone in the three kinds, on principles that meet the
  evidence bar; everything logged.
- **Level 2 and beyond:** steps James chooses (lower the evidence bar, add
  kinds — Claude's example was small scope cuts, which James dropped from
  §4.1 — use approved below-bar principles alone).
- Up: only when James says so, judged on shadow agreement and how often he
  overrides logged decisions. Down: automatic — a confirmed confident wrong
  drops that principle back to "ask" until he approves it again; the rest of
  the model stays at its level.
- In shadow, each answer James gives is a live grade. The live stats (share
  of shadow predictions agreed with, override rate in review) come from the
  decision log, where answers are copied in as "asked" entries (§4.8).
  Claude first said the question store would hold them; that was superseded
  by the one-way log design, since `question-store` knows nothing of
  decisions or overrides.

### 4.13 Upkeep

Answers to parked questions apply live to the exact question. Everything else
— overrides, new transcripts, PRs and GSD records, conflict verdicts,
confirmations — is folded in during regular review sessions. Why: the same
question often recurs in the next phase or repo; generalising waits for
sessions so one-off answers don't become rules without review. (The live
answer is scoped to that client or project, so a recurrence elsewhere is
still asked; that scope is from option text, §8.2.)

### 4.14 Deferred

Structural lint rules and James's own orchestration scripts: revisit once the
decision model exists (which principles are lintable) and the reviewer has a
track record (where it misses).

---

## 5. Packaging

Five packages, built with `claude-package-kit`, released as tarballs and
installed into `/mnt/sda/User/Programs/claude-tools/<package>`. Each gets an
INVENTORY.md row when installed. Each extracted tarball directory under
`claude-tools/<package>` must stay after install, because the package's
`update.sh` re-runs the installer from it (as with claude-guard-hooks).

| Package | Kind | Depends on |
|---|---|---|
| `embedding-lib` | command | nothing |
| `question-store` | hooks + command | nothing |
| `voice-decision-pipeline` | command | `embedding-lib`; writes the data format |
| `voice-runtime` | skill | `embedding-lib`; reads the data format |
| `decision-runtime` | hooks | `embedding-lib` (only if the lookup uses similarity search, §8.6), `question-store`; reads the data format |

Which repo each package lives in is not decided, and the kinds are from
option text (§8.2).

- **Naming:** the prefix is the subject (`voice`, `decision`, or what a
  shared part handles) and the suffix is the kind of thing — `-pipeline`
  builds the models, `-runtime` uses a model, `-lib` is a shared library and
  environment others load, `-store` holds a live record others read and
  write. James chose a suffix naming what the package does, with the
  voice/decision prefixes kept.
- **Contents:** `voice-decision-pipeline` — extraction (Slack, Bitbucket,
  transcripts, GSD records), anonymising and redaction, building the
  embedding index, labelling runs, writing the guide and principles, the
  review pages, validation, rebuilds and the regular review sessions.
  `voice-runtime` — the guide loader and exemplar search. `decision-runtime`
  — the `SessionStart`/`SubagentStart` blocks, gates, reviewers, plan-review
  adapters, the lookup and the decision log (the question store moved to
  `question-store`). `question-store` (Claude's list) — park
  (record a question; the agent carries on with independent work), notify
  (push, session, Slack DM), collect (every channel's answer written back to
  one record; first answer wins, the others are told), hand back (waiting
  work reads the answer), show (the session command), mirror (open
  questions as GSD blockers; where mirroring lives is open, §8.7). This
  split of contents is Claude's, never asked (§8.3).
- **Building vs using:** only `voice-decision-pipeline` builds the models
  (corpus, labels, guide, principles, indexes, the short agent block of
  §4.3, review steps, validation, rebuilds). The others use what it built
  and write evidence records (drafts and approved versions, answers,
  decision-log entries and every review block) back into the data directory
  for the next build. Nothing is trained
  in the machine-learning sense; building means producing files.
- **Build order:** the voice model is built first, then the decision model
  (James, 9 Nov 2026, after the planning session). Claude's
  reason, chosen as recommended: the decision model's main source, Claude
  Code transcripts, grows from now on, so waiting gives it more data, and
  the voice model can start from the Slack export already on disk. The
  voice model's Bitbucket PR part still needs `read:repository` on the
  token (§9).
- **`question-store`** is separate so other hooks, GSD blockers and future
  tools can ask James without depending on `decision-runtime`; its versioned
  interface is park a question / read its answer.
- **Coupling, following the rrc/rrcd pattern:** shared code lives once in the
  owning package's library, which only defines things; dependents load it from
  that package's install directory (never `PATH`), check a version constant,
  and their install check fails if it's missing; each dependent's README says
  what has to be installed first. (James pointed to rrc/rrcd; loading from
  the install directory with a version check is from option text, §8.2.)
- **`embedding-lib`** owns the Python environment (sentence-transformers, CPU
  PyTorch, `bge-base-en-v1.5`) and an embed library with a version constant.
  The data directory records which model and version built each index; a
  consumer refuses a mismatch until the pipeline re-embeds (Claude's design,
  never asked — §8.3).
- **Data format manifest:** the pipeline writes a manifest in the data
  directory naming the format version and what each file holds; both
  runtime packages check it before reading and refuse a version they don't
  know. A format change means coordinated releases of the
  pipeline and both runtime packages. (The manifest is from option text,
  §8.2.)
- **Anonymiser** stays inside the pipeline, the only thing that runs it. It
  splits out the same way if anonymising is ever needed at use time (e.g. if
  the Slack-connector route for new Slack data is used). Claude's
  placement, never asked (§8.3).
- No data in any repo; tests use made-up fixtures. Model rebuilds change only
  the data directory, never a package. Re-releases are for code changes
  only.

## 6. Cost (estimates, input tokens)

Accepted as estimated; no cuts. Output tokens are much smaller (mostly labels
and scores). Offered, and not taken up when James accepted the costs:
second-model labelling on a sample only (whether that settles the second
model's scope is still asked, §8.1), or fewer held-back voice drafts (would
save 10–15M, at the cost of less certainty).

| Building, once | Tokens |
|---|---|
| Labelling ~17k Slack messages with context | ~5.5M |
| Second-model blind labelling | ~5.5M |
| Decision extraction | ~2–3M |
| Transcripts and PR comments | ~2–3M (PR volume not measured) |
| Writing the guide and principles | ~2–5M |
| Voice validation (~1,700 drafts + judge) | ~14M |
| Decision validation | ~2M |
| **Total** | **~33–38M** (the rows' sum; the first estimate was ~35–45M) |

| Running, per year | Tokens |
|---|---|
| End-of-turn review (~8,700 checks) | ~25–35M (session figure; ~8,700 checks × ~2–4k gives ~17–35M) |
| After-each-plan review | ~4–10M (session figure). Its ~750–1,000 checks are an unmeasured estimate, which overstates, since only 6–8 of the active repos use GSD (8 have `.planning/`, 6 a `config.json`; §8.4) and 145 plans exist on the machine; commits per plan not measured. APPENDIX B.4's own figures give ~7–11M (every-commit tokens less repeated overhead) or ~4–15M (checks × tokens per check) |
| `SubagentStop` and plan reviews | small; volume unknown |
| Drafting | small (guide cached) |

Disk: about 1–2 GB for `embedding-lib`'s environment, about 20 MB for the
corpus.

James's time: about an hour for the 60 blind pairs, about 60 labels and the
graded prediction sample, plus the first anonymised batches, confirming
inferred reasons and bulk-accepted records, conflict verdicts and the
regular review sessions.

---

## 7. Verified facts this plan rests on

Checked on 9 Nov 2026 (Claude Code docs, GSD plugin files and tests on this
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
  `SubagentStart` too: the saved hook log shows a second `bm-executor`
  (id `a62417db1d7e36a4f`) logging `SubagentStart` at 13:15:54, 15
  `PreToolUse` calls and `SubagentStop` at 13:16:33. Not tested for any agent
  type: that `additionalContext` from `SubagentStart` reaches the agent.
- Before the test, `~/.claude/settings.json` had no `SubagentStart` or
  `SubagentStop` hooks; `decision-runtime` will be the first to register them.
- Tested: a `PreToolUse` hook on `ExitPlanMode` receives the plan text; a deny
  keeps Claude in plan mode, the reason reaches Claude, and the revised plan
  can be resubmitted.
- GSD: `autonomous`'s smart discuss asks James to accept or override each grey
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
- `check-discuss-batch.sh` lets `--power` and `--auto` through and doesn't
  fire in `autonomous`'s discuss step: without `--interactive`, smart discuss
  runs and no skill is called; with it, `autonomous` calls the hyphenated
  `gsd-discuss-phase`, which the hook's match list (`gsd:`/`bm:`) doesn't
  cover.
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

Swept from the whole planning session. Nothing here has been decided by
James; where an item has a figure or rule, it came from Claude's question or
option text and was never discussed on its own.

### 8.1 Never answered

- **How the build is run.** Which repos the packages live in is itself
  open (§8.2). The repos Claude's option text named, `claude-skills` and
  `claude-hooks`, have no `.planning/`, so the GSD-only rule doesn't apply
  to them. Whether the build goes through GSD (set up in whichever repos
  are chosen), through `claude-package-kit` directly, or another route is
  not decided.
- **When the build starts.** Nothing is to start until James says so.
- **Second-model labelling scope.** Asked at the end of the 9 Nov session and
  not yet answered: does the second model label all ~17k messages (as the
  cost table priced it, ~5.5M, accepted), or only the ~60-message
  check sample? Today §3.4 records it as pending.

### 8.2 Taken from option text, never discussed on its own

- Voice pass mark: James picks wrong about 40% of the time or more, and most
  drafts score 4 or higher.
- Label check: over about 10% wrong labels, the labelling prompt is changed
  and rerun.
- Size of the label-check sample (about 60) and of each anonymised review
  batch (about 50 messages).
- Holding back about 10% for validation, in both models.
- Showing the prediction next to the question in trust level 0 (shadow).
- Level 2 examples (lower the evidence bar, add kinds — Claude's example was
  small scope cuts, which James dropped from §4.1 — use approved below-bar
  principles alone) — examples only; the actual steps are James's to choose.
- The decision pass mark's 90% figure: an "e.g. 90%+" in option text; James
  chose that option and agreed to the trust levels; the figure itself was
  never discussed.
- "Principles you confirm directly in a review session pass regardless" (in
  the evidence-bar option James chose) — conflicts with Level 2's "use
  approved below-bar principles alone"; which holds is open.
- "Each confident wrong is traced to its principle, fixed, and the sample
  regraded" (option text; §4.11).
- "If the 10% sample shows the filter missing many, it is widened" — no
  threshold set.
- The list of deciding agents for the parking test (`bm-executor`,
  `bm-planner`, `bm-plan-checker`, `bm-advisor-researcher`,
  `bm-framework-selector`, workflow agents, main session).
- Voice blind-pair spread (about 12 per audience, about an hour).
- James's time: the voice step gave the 60 blind pairs alone as about an
  hour (§3.7); the cost step gave about an hour for the pairs, about 60
  labels and the graded prediction sample together (§6). Neither figure was
  discussed. Not discussed: the cost-step figure is
  probably low.
- Decision model format: a markdown record with stable principle ids.
- Which repo each package lives in: `embedding-lib`,
  `voice-decision-pipeline` and `voice-runtime` in `claude-skills`;
  `question-store` and `decision-runtime` in `claude-hooks`. Claude put the
  repos into the option text of the three-package question (which
  James asked to clarify instead of answering) and the five-package question.
  James answered the second with a reply that chose the split and asked for
  new names; the repos were never discussed. Claude had placed them by kind
  (hooks in `claude-hooks`, skills and commands in `claude-skills`).
- Package kinds (`embedding-lib` command, `question-store` hooks + command,
  `voice-decision-pipeline` command, `voice-runtime` skill,
  `decision-runtime` hooks), the versioned data-format manifest, and
  loading shared code from the owning package's install directory with a
  version check: all in the five-package option text. James
  chose the split and asked for consistent names. The coupling concern and
  the rrc/rrcd pattern were his; the manifest and kinds were never
  discussed.
- Slack context cap of 10 messages each way: in the description of a context
  option.
- grill-with-docs ADRs and GLOSSARY.md as a source: in the text of the
  written-records question, which was about GSD records.
- Three to five exemplars per draft ("the closest 3–5").
- A live answer applies only to that exact question in that client or
  project.
- The OpenSpec adapter is added when James starts using it.
- The PreToolUse prompt rewrite on the Agent tool as a per-agent fallback.
- What each question to James contains: the decision, the options, the
  principles that came close, the work waiting on it.
- "Correct refusal" as a validation outcome, safe and excluded from the
  right-prediction bar (question text).
- A random 10% of non-candidates sent to measure what the decision filter
  misses.

### 8.3 Claude's own design, never put to James

Found by checking every question put to James and his answers; none of these
was put to him.

- What goes in each package (§5 Contents; Claude's list).
- The anonymiser lives inside the pipeline.
- `embedding-lib` consumers refuse a model/index mismatch until the
  pipeline re-embeds.
- Each message is embedded with the message it answers.
- All four voice uses run in the main session, so the skill only needs to
  reach it (§3.6).
- An agent decides alone only if no client constraint contradicts the
  principle (§4.1).
- One per-repo record of what has been reviewed, shared by all review
  points (§4.5).
- Claude's recommendations in ordinary sessions get no review point (§4.5).
- grill-me / grill-with-docs need no gate (§4.6).
- Only one hook may ever modify Agent input (§4.4).
- Question answers: first answer wins, the other channels are told (§4.7).
- Decision log: changed answers supersede, never edit; `decision-runtime`
  writes the "asked" entries; every review block is logged (§4.8).
- The voice review page saves progress between sittings (§3.7).

### 8.4 Sources and corpus

- Whether subagent (sidechain) transcripts are included, or only main-session
  ones.
- Whether git commit messages in the local clones are a decision source.
- The exact Bitbucket repos (to be picked when run; rule set apart from the
  2018 boundary below).
- spaCy model size: the large English model (~500 MB) or a smaller one.
- Whether the data directory's name, `voice-decisions-data`, should follow the
  package naming (`voice-decision-*`).
- The two DMs whose other person has no resolvable name ("DM (no name)" and
  one shown only as a Slack user id) are kept by default; not discussed.
- Thresholds for "too short to show voice" and "mostly code or logs" in the
  exemplar filter.
- Whether James's own emoji reactions to other people's messages are a
  signal. A 👍 on a proposal can be an agreement, i.e. a
  decision. Today only reactions on his messages are kept, as context.
- Group DMs outside the senior/management set (e.g. one with James and two
  colleagues) have no audience assigned yet.
- Corpus file formats: the JSONL schema, how the embedding index is stored,
  how the anonymising map is stored.
- Protection of the data directory (it holds colleagues' DMs). Today the
  whole directory is owner-only: Claude set it with `chmod -R go-rwx` on
  9 Nov, unasked. Open: whether the pipeline keeps the corpus
  and map files that way once written, what mode the anonymising map gets,
  whether the directory is backed up, and whether and when it's ever
  deleted.
- How packages find the data directory (an environment variable, a config
  file, or a fixed path).
- Bot messages and channel events (joins, topic changes) dropped from the
  corpus: proposed in the part list, never discussed.
- Whether Bitbucket content is limited to PRs James authored or reviewed
  (Claude's proposal; never answered).
- Whether a repo last updated in 2018 is kept: James's guideline drew the line
  at 2018 without saying which side 2018 itself falls on; Claude restated it
  as "updated since 2018" (keeps 2018); a repo count used "2019 or later"
  (drops 2018).
- Whether the 2 repos that have `.planning/` but no `.planning/config.json`
  are GSD repos whose `STATE.md` and `CONTEXT.md` count as decision sources
  (§1 counts 6).
- Whether the reviewed anonymised batches must include each source (Slack,
  PRs, transcripts) before James stops review, since each anonymises
  differently.
- The pseudonym format (stable pseudonym plus role tag, e.g. `colleague-07`;
  clients as codes): proposed, not separately agreed.
- Where spaCy's environment lives, now `embedding-lib` owns the embedding
  environment: its own environment in the data directory, inside the
  pipeline package, or `embedding-lib`'s. The option James chose ("Lists +
  spaCy") said "installed into the data directory's own Python environment,
  not system-wide"; it was reopened only because `embedding-lib` later took
  over the embedding environment.
- Which product, store and project names that identify a client on their own
  are added to the anonymising replacement list (§2.3).
- That sending work through subagents multiplies the volume of text sent to
  the API: raised, never discussed.
- The "how much of the corpus may be sent" question was withdrawn for
  clarification and never re-asked; full sending (anonymised) is assumed by
  §4.9 and §6.
- Whether Claude Code transcripts from other machines or cloud sessions exist
  and should be included (only this machine's were counted).

### 8.5 Voice

- Whether the 1:1 colleagues audience is split further by whether the person
  reports to James.
- Which reference list of generic business phrases the "never say" list is
  measured against.
- How a draft's audience and purposes are set at drafting time: inferred by
  Claude, or stated by James.
- How the "approved version" is captured when James edits a draft after it
  leaves Claude (e.g. edited in Slack before sending).
- How often the regular review sessions run, and what form they take.
- The exact line added to `~/.claude/CLAUDE.md` to load the voice skill
  (James approves the wording; CLAUDE.md is his).
- Where the review pages run — label checks, blind pairs, and confirmations
  of inferred reasons and bulk-accepted records all show real corpus text; a
  local page keeps it on this machine, a claude.ai page would send it off it —
  and how the blind-pair page saves progress between sittings. (The pages
  are part of `voice-decision-pipeline`.)
- Real names in built outputs: the voice guide, exemplars, principles,
  evidence quotes and client constraints. All of them reach the API — the
  guide in every drafting prompt, exemplars at each draft, principles,
  quotes and constraints through every lookup. James chose "real names
  everywhere" when the option said it meant "exemplars and quotes loaded
  into future prompts name real people", then added anonymise-before-
  sending, which was agreed for the corpus. Today §2.3 assumes exemplars
  are sent anonymised (a pre-anonymised copy stored at build time); nothing
  is set for the guide, principles, quotes or constraints. Options: real
  names in all of them; anonymised in all of them; or a split, e.g.
  exemplars and guide anonymised, client constraints with real client names
  (they probably need them to match a repo).
- How `jira-comments.md`'s own wording rules (e.g. no second person,
  shorter) sit against the voice model where they disagree. "Voice wins
  outward" was agreed against the CLAUDE.md writing rules, not against that
  file. Today §3.1 keeps only the file's structure. Options: the file's
  wording rules win for Jira comments; the voice model wins; or the file's
  rules apply only where the voice model has no Jira-specific evidence.
  The Jira comments option James ticked under voice uses did say "Structure
  stays with jira-comments.md; wording would take your Slack voice, since
  Jira is no longer a source", which points to the voice model winning on
  wording. The file's own wording rules were not mentioned.
- How the voice model sits alongside the formats other tools impose: the PR
  description template in `/gsd:ship` and `/bm:ship`, and the comment format
  of `/code-review --comment`.
- How a rule James wants added to the voice guide gets in. The guide is
  generated by the pipeline, so a hand edit would be overwritten; it needs a
  pipeline input James can write to.
- Which model writes drafts, and which runs the labelling and the judge.
- Whether James also reviews the judge's worst-scored drafts and a random few
  (part of the judge option he chose), on top of the 60 blind pairs. As
  offered, the judge option replaced James's pairs ("you review only the
  worst and a random few"). James chose it in parallel with the blind pairs
  (options 1 and 3), so whether the worst-and-random review is added on top is
  the open point.
- When an audience-and-purpose cell has too few exemplars, whether to fall
  back to the same purpose in another audience (Claude's proposal; not
  discussed).
- Whether "second model" for blind labelling means a different model, or the
  same model with a different prompt.

### 8.6 Decisions

- Whether the decision lookup uses similarity search or keywords. If
  keywords are chosen, `decision-runtime` no longer needs `embedding-lib` or
  the ~1–2 GB environment at use time.
- Reviewer hook type: prompt (single call) or agent (experimental; whether it
  can run `git diff` is unconfirmed), and which model it runs on (the cost
  estimate assumes the cheap background tier).
- Which model makes the held-back decision predictions (Claude said "I …
  predict") and which runs the decision judge.
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
- Where the decision log lives and its entry format, beyond the fields agreed
  (decision, agent, principle ids, asked or made alone, supersedes).
- The infrastructure-skip check: which hook event detects the minimal
  `CONTEXT.md` (the file write, or its `bm-sdk` commit), how it holds the
  run, and which signals it matches (candidates, §7: the display line, and
  a `<domain>` that is the phase boundary from the ROADMAP goal). Also what is
  reviewed at that point: when the minimal `CONTEXT.md` is written the planner
  hasn't run, so there is no approach yet; the check either reviews the phase
  goal against the decision model there, or waits for the first `PLAN.md`
  before execution starts.
- Whether a pre-existing `CONTEXT.md` not written by James (discuss is
  skipped when `has_context` is true) needs the same check as the
  infrastructure skip.
- Whether the end-of-turn reviewer treats changed plan and spec files
  (OpenSpec's `proposal.md`/`specs/`, GSD's `PLAN.md`/`CONTEXT.md`, plan
  files) as decisions rather than code — Claude said it would need to; not
  decided.
- Which hook event catches `/opsx:apply` (a slash command is not a tool call
  unless run through the Skill tool; `UserPromptSubmit`/`UserPromptExpansion`
  are the candidates) — not checked.
- How client constraints are matched to the current repo (a repo-to-client
  mapping).
- How often `/gsd:profile-user` is rerun on anonymised copies.
- Whether the profiler's own "Sensitive Content Exclusion (Layer 1)" and
  "Message Thresholds" (in `references/user-profiling.md`, APPENDIX D.3)
  still behave correctly on an anonymised sample. Those sections were listed
  but not read.
- What a review session for decisions looks like, and how often.
- Whether any GSD setting can narrow `bm-executor`'s Rules 1–3 (not checked).
  L116 also forbids ad-hoc pauses to ask about mechanics (APPENDIX D.3).
- Whether `bm-phase-researcher` (spawned by `/gsd:quick`, `quick.md` L411)
  needs the parking test along with the other deciding agents (§4.11).
- Whether the after-each-plan review hooks `SubagentStop` or `PreToolUse` on
  `SubagentHandback`: the observed `bm-executor` handed back through a
  `SubagentHandback` tool call, logged by `PreToolUse` a second before
  `SubagentStop` (APPENDIX D.2). Not discussed.
- Whether OpenSpec runs its own agents (its docs don't say).
- How the `SessionStart` block behaves in sessions that never touch code (it
  fires in every session; cost accepted, behaviour not discussed).
- Real names in principles, evidence quotes and client constraints: see
  §8.5.
- What counts as an "approved entry" for the gates. If an agent can log its
  own decision and then pass the gate, the gate is circular; it needs to be
  limited to entries backed by a usable principle or by James's answer.
- What the reviewer does when it finds a problem. Today §4.5 says it sends
  the agent back (part of the layers taken as recommended). Open: whether,
  besides that, it reverts, logs it or parks a question; and in the main
  session, where James is present, whether it asks him directly instead of
  sending Claude back.
- What happens when the reviewer keeps blocking: Claude Code caps
  continuations at 8; whether the reviewer then parks a question. (A prompt
  hook's `"impossible": true` lets the stop go ahead, APPENDIX D.1.)
- How James overrides a false block ("allow anyway") without a workaround.
- Whether a local pre-filter limits the end-of-turn and after-plan reviews to
  changes that touch structure (new or moved files, large diffs), to cut
  cost.
- What the gates and reviewers do before the decision model exists or while
  it's at trust level 0: live from the start, or only once the model passes
  validation.
- How James adds or adjusts a principle directly. The principles file is
  generated, so it needs a pipeline input, like the voice guide.
- Folders that aren't git repos (e.g. `~/claude-sandbox` itself) have no diff
  for the end-of-turn review, and changes outside the working directory (e.g.
  `~/.claude` files) aren't seen unless the hook is told where to look.
  Whether those are covered is not decided.
- Sessions this machine's hooks don't reach: claude.ai cloud sessions and
  any other machine (e.g. the remote Mac). Whether the runtime is installed
  anywhere else is not decided.
- Buildomator's `.agents/workspace.json` reader (§7) as another delivery
  route: `decision-runtime` could emit a conformant file. Noticed, not
  discussed.
- `bm-executor` treats a project `./CLAUDE.md` as hard constraints — a
  stronger route for that agent (it would mean editing each repo's
  CLAUDE.md); noticed, not discussed.
- Whether `bm-advisor-researcher`, `bm-framework-selector`, `bm-plan-checker`
  and `code-review-fix` — which recommend or judge without James — are covered
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
  finish with unlogged decisions): in Claude's first full recommendation,
  but not in the recap James accepted (it listed dependency,
  test-framework and path gates). Whether it's part of the decided layer,
  and whether it's still needed now the reviewer reads diffs and catches
  unlogged decisions itself.
- In plan mode, whether a `PostToolUse` hook logs the approved plan's
  decisions as James's, and whether uncovered decisions go into the plan as
  open questions (James is present at approval) instead of `question-store`.
  Both proposed, never asked.
- Reviewer diffs go to the API un-anonymised; not discussed.
- Whether the end-of-turn `Stop` reviewer uses `asyncRewake` like
  claude-guard-hooks 1.3.1 (a `Stop` hook's block reason is otherwise printed
  to James in full).
- How the park rule maps onto `autonomous`. `autonomous` doesn't wait for
  replies (§7), so a parked question pauses a run only through blocker
  mirroring. A question mirrored to `STATE.md` blockers sends `autonomous`
  to `handle_blocker`, which asks James to choose "Fix and retry", "Skip
  this phase" (marks the phase skipped and carries on) or "Stop autonomous
  mode"; it does not wait for the question's answer. Options not discussed,
  e.g. stopping, then resuming with `--from`. In `autonomous --interactive`,
  plan and execute for phase N run as background agents while discuss for
  N+1 starts; how a question parked by N's executor interacts with that is
  not discussed either.
- Whether `autonomous`'s ui-phase (UI design contract) and ui-review are
  covered; not discussed.
- Origin weighting (§4.9) needs the transcript's AskUserQuestion answers,
  because GSD's `CONTEXT.md` records only the final answer (§7). A "You
  decide" answer in discuss is James delegating and shouldn't count as his
  choice; how it is counted is not decided.
- Which GSD checkpoints auto-approve, beyond `gate="blocking-human"` ones
  being excluded (§7): not checked.
- Whether Rule 4's checkpoint (what was found, proposed change, why, impact,
  alternatives — §7), and the package-install `checkpoint:human-verify`
  (answered "verified" with the package name, or "abort"; APPENDIX D.3),
  feed `question-store`; not discussed.
- `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` (§7) bears on the model-choice items
  above and in §8.5.
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
- How grill-with-docs records are weighted (§4.9). `grilling` asks a whole
  numbered round, each question with a recommended answer that "yes"
  accepts, so a round answered "yes" is close to bulk acceptance. An ADR is
  written only when James says yes to it, and `GLOSSARY.md` is updated
  without asking. Whether these count as his or as weak
  evidence is not decided; Claude's summary called them "decisions you
  made, recorded with reasons".

### 8.7 Questions to James (`question-store`)

- Which session sends notices and reads Slack replies, and how often (push
  and the Slack connector are only callable from a Claude session). Push and
  Slack delivery, and reading Slack replies, only happen while a Claude
  session is running, not from a background service. A question parked when
  no session is running isn't delivered until one starts. A background
  sender could only send by some other route than those two tools.
- Whether a Slack DM to James himself counts as "posting" under the
  CLAUDE.md rule that anything outward-facing needs approval of the exact
  text. Sending questions there needs either a standing exception written
  into that rule or approval per message.
- Which push mechanism is used (Claude Code's push notification tool is
  assumed). For a background sender: this machine has systemd 245, and the
  sandbox blocks the user bus (from the rrcd notes: rrc's
  `rrc-session@.service` unit never started on systemd 245 / Ubuntu 20.04,
  because `StandardOutput=truncate:` needs systemd 248 and the unit's
  `%i.env` wasn't found for a path with a hyphen; rrc dropped systemd units
  after 1.0.0).
- Whether a Slack DM to yourself notifies you at all. Slack may not send
  notifications for messages in your own self-DM, which would make it a place
  to answer but not a way to be told. Not checked.
- The session command's name, and whether it can also be used to answer.
- What a question shows beyond the agreed fields (decision, options,
  principles that came close, waiting work), e.g. a deadline or which run is
  waiting.
- Blocker mirroring (§4.7) works only in GSD repos (no `STATE.md`
  elsewhere; APPENDIX B.5). Open: whether anything outside GSD needs a stop
  like `handle_blocker`, or the question record and the park rule are enough
  there. Also open: whether mirroring lives in `question-store` (Claude's
  list, §5, puts it there, which makes it depend on GSD's `gsd_add_blocker`
  and `STATE.md`) or in `decision-runtime` or a GSD adapter, so
  `question-store` keeps no GSD dependency.
- How James changes an answer already given (which channel or command), and
  what happens to work that has already resumed on the old answer. §4.8
  covers only the log entry.
- How waiting work learns that a parked question has been answered and is
  resumed, outside `autonomous`'s blocker route: polling by the waiting
  agent, a hook in the next turn, or James restarting it. Not discussed: if
  the run that parked the question has ended, nothing in the plan restarts it.

### 8.8 Packaging and process

- Release order and how the first versions are cut.
- Which hooks `question-store` itself installs (it's marked "hooks +
  command").
- Whether the price of the token estimates is worked out (claude-api skill
  rates); only token counts exist today.
- Which estimates still need measuring: Bitbucket PR and comment volume,
  commits per GSD plan (the after-each-plan figure in §6 rests on an assumed
  count), the number of PRs per repo.
- Whether `claude-package-kit` supports a package that is both hooks and a
  command (`question-store`), or it has to be one kind. Not checked.
- How the packages are tested end to end against real Claude Code. The
  rrc/rrcd packages used Docker: `confirm.sh sandbox-rrc`, `integration.sh`
  and `integration.sh --app`, run in James's terminal (Claude's Bash tool
  can't reach the Docker socket) with output logged to
  `results/<time>/run.log`; all passed on Claude Code 2.1.308 on 2 Nov
  (`test/docker/results/20261102-194809/`).
- Each install adds its own sandbox exclusion with a wildcard (`"rrc *"`); a
  bare entry matches only the bare command — relevant if any package's
  commands must run outside the sandbox.
- The by-hand `/gsd:profile-user` run: the workflow deletes its temp
  directory holding the sample (`{temp_dir}/profile-sample.jsonl`, the file
  to anonymise) and the analysis (the agent's `<analysis>` JSON block), so
  both must be copied to the data directory before cleanup.
- When a runtime package refuses (missing data directory, wrong embed model,
  unknown format version — §5 already says it refuses): whether the hook or
  skill fails loudly or carries on without the model.
- Where runtime state lives that isn't model data (the per-repo record of
  what has been reviewed, gate state, delivery state): the data directory,
  or each package's own `state/` as rrc/rrcd do (which reinstalls keep).
- Whether pipeline rebuilds (folding in new transcripts, PRs and GSD
  records) are run by hand in review sessions or scheduled automatically.
  Raised in Claude's part list (part 13, "re-run by hand or automatically")
  and not discussed separately.
- Running costs not estimated in §6: the 300–600-token block
  in every session (`SessionStart`) and every subagent launch
  (`SubagentStart`), lookup results at each decision, gate denial reasons,
  and any `PostToolUse` plan logging.
- Which after-each-plan review figure stands. §6 gives ~4–10M a year. APPENDIX
  B.4's own numbers give ~7–11M (every-commit tokens less the repeated
  overhead) or ~4–15M (checks × tokens per check). The ~750–1,000 checks
  behind all three are an unmeasured estimate. No method was chosen. Measuring
  commits per plan from the 145 local plans would settle the count. (Claude
  told James on 9 Nov this contradiction was left open in §8.)

## 9. Needs James when it runs

1. Add `read:repository` to the Bitbucket token; at the same time
   `~/.claude/auth-recipes/bitbucket.md` gets its scopes and gotchas 5
   (branch refs) and 8 (PR diffstat) updated. The token is in `~/.netrc` (REST
   only; git uses SSH).
2. Pick the `oneiota` repos.
3. Review the first anonymised batches, until he says stop.
4. Check the audience mapping and the label sample; confirm inferred reasons
   and bulk-accepted records.
5. Grade the 60 blind voice pairs (more whenever he wants).
6. Grade the prediction sample and every judge-marked wrong.
7. Decide every old-against-new conflict before an orchestrator gets the
   decision model.
8. Run the install commands for the hook packages (`~/.claude/hooks` is
   outside Claude's Bash sandbox).
9. Move the decision model up trust levels.
