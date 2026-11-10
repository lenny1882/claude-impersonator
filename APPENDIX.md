# Appendix to PLAN.md — evidence and comparisons

Everything from the 9 Nov 2026 planning session that isn't a decision:
measurements, the comparisons behind each decision, rejected options
and references.

---

## A. Measurements

### A.1 Slack export

- Messages in the export average 16 words.
- James's messages: 17,601, 309,975 words. After the nine struck-out
  conversations: 17,319 in 75 conversations.
- James struck nine conversations (282 of his messages). Two were
  flagged during review as probably about candidates; he kept one other
  flagged conversation.
- Years covered: 2020–2026.
- Threads: all but 11 of the replies the thread metadata lists are present.
  Checked later; Claude called it "settled
  by measurement": thread replies are complete in the export.
- Corpus with the agreed context rules: 52,655 distinct messages stored
  once (James's 17,601 plus about 35,000 messages from other people as
  context; ~0.84M words, ~10 MB, ~1.1M tokens). The measuring script
  added each message's own index to its context set, so the 52,655
  already includes James's messages. The session described it as "17,601 …
  plus 52,655 context messages", which counts his messages twice. The word
  and size figures were not affected: 52,655 × 16 words ≈ 0.84M;
  with context copied into every message, 4,268,632 words (~35 MB, ~5.5M
  tokens). Measured before the nine conversations were struck out (17,319
  own messages after), so the ~5.5M labelling figure in PLAN §6 is a slight
  overestimate.
- Client audience is the smallest: about 325 of James's messages.

### A.2 Claude Code transcripts (as of 9 Nov 2026)

- 114 files; 2,162 typed prompts, 52,154 words; 12 Oct – 9 Nov 2026 only
  (older ones already deleted by the 30-day default).
- Claude's reply text: 525,742 words; 10,032 tool calls.
- Main session over the same four weeks: 3,653 typed prompts (every
  non-meta user record with text, so task notifications and "[Request
  interrupted…]" markers count too).

### A.3 Jira (dropped as a source)

- JQL can't filter comments by author.

### A.4 This machine

- `nvidia-smi` couldn't reach the driver from
  Claude's Bash tool, so no working GPU was visible. No local model runtime
  (ollama, llama.cpp) installed.
- GSD plugin 5.1.0 at
  `~/.claude/plugins/cache/gsd-plugin/gsd/5.1.0/` (Buildomator; `/gsd:` and
  `/bm:` both work).

---

## B. Comparisons behind the decisions

### B.1 Delivery and enforcement options (ranked strongest to weakest)

1. **Gating hooks** — enforced.
   - Reaches: every session and subagent, since hooks fire on tool calls
     wherever they happen.
   - Misses: decisions that exist only in what the agent writes (patterns,
     module splits, naming); those aren't visible as a tool call.
   - Enforcement: the tool call that carries out the decision is denied
     unless the decision log has an approved entry — dependency changes
     (manifest edits, `npm install`, `flutter pub add`), switching test
     frameworks, edits under marked paths. A `SubagentStop`/`Stop` hook can
     also refuse to let an agent finish with unlogged decisions (enforces
     that it records, not that it decided well).
   - Cost: no tokens unless a gate fires; then the denial reason is shown to
     the agent.
   - Upkeep: a package in `claude-hooks` like the guard hooks; patterns grow
     as new decision types turn up.
   - Risk: medium — a wrong match blocks legitimate work; every gate needs
     tests.
2. **Overriding GSD's agents with copies in `~/.claude/agents/`** — advisory,
   strongest advisory.
   - Reaches: each copied agent. Misses: uncopied agents, the main session.
   - Enforcement: the block goes in the agent's own system prompt and GSD's
     conflicting rules can be removed.
   - Cost: no extra tokens beyond the block.
   - Upkeep: heavy — each copy replaces GSD's version entirely and must be
     re-merged after every GSD update.
   - Risk: high over time — a stale copy silently loses GSD fixes.
   - **Rejected** for its upkeep.
3. **`--append-subagent-system-prompt`** (and `-file`, v2.1.261+) — advisory,
   strong.
   - Reaches: every subagent's system prompt, nested included. Misses:
     interactive sessions (works only with `claude -p`), forked subagents.
   - Enforcement: system-prompt level beside the agent's rules; conflicts
     remain.
   - Cost: the block per subagent in that run. Upkeep: one flag. Risk: low;
     only fits if `autonomous` runs headless.
   - Not used: Claude's intermediate combination (gates, `SubagentStart`
     for subagents, a short CLAUDE.md pointer for the main session,
     `--append-subagent-system-prompt` for headless runs) included it and
     claimed one advisory copy per context. The final recommendation dropped
     it, giving only the reason that it works only in headless runs. In a
     headless run it would in fact put a second copy into every subagent
     `SubagentStart` already reaches. Whether `autonomous` runs are launched
     headless was never established.
4. **`PreToolUse` hook on the Agent tool appending the block to the prompt**
   — advisory, moderate.
   - Reaches: agents launched through the Agent tool. Misses: possibly
     workflow-script agents; the main session.
   - Enforcement: part of the task prompt, still beneath the system prompt.
   - Cost: the block per launch. Upkeep: a package in `claude-hooks`.
   - Risk: medium — undocumented for this use; `updatedInput` replaces the
     whole input, so a mistake breaks every agent launch.
   - Kept as the per-agent **fallback** only.
5. **`SubagentStart` hook** — advisory, weak.
   - Reaches: every subagent, plugin and workflow agents included per the
     docs (the event is seen firing for a GSD agent in the saved hook log;
     context delivery untested, PLAN §7), matched by agent type.
     Misses: the main session.
   - Enforcement: context at the start of the subagent's conversation, below
     its system prompt; where GSD's instructions conflict, GSD's usually win.
   - Cost: the block per subagent launch; nothing in sessions that launch
     no subagents. Upkeep: a package. Risk: low, documented; a failing hook
     can't break agent launches (unlike the `PreToolUse` rewrite).
   - **Chosen** for subagents.
6. **Section in `~/.claude/CLAUDE.md`** — advisory, weakest.
   - Reaches: main session and most subagents. Misses: Explore and Plan,
     agents with `omitClaudeMd: true`; plugin agents unconfirmed.
   - Cost: every session in every project. Upkeep: simplest; `@`-imports
     inside subagents unconfirmed.
   - Weakest because it competes with every other rule in an already long
     file. An `@`-import of a generated file would keep it current without
     editing CLAUDE.md itself. Risk: low to install; following it is the
     least reliable of the six.
   - **Rejected**; replaced by a `SessionStart` hook for the main session
     (same strength, no double copy in subagents).

Using several together: coverage adds up (each misses different places);
advisory strength doesn't add up the same way (two copies are only slightly
more prominent; an agent told to "pick the default" can still ignore both);
only gates add real enforcement, and pair well with advisory text (fewer gate
firings, denial reasons teach the rule mid-run). Duplication doubles tokens
and is harmful once copies disagree — so every copy is generated from one
source file. New gates run alongside `claude-guard-hooks`' `PreToolUse` hooks;
any one hook's deny blocks the call. Which of two Agent-input rewrites wins is
unverified — so only one hook may ever modify Agent input. Each layer should
log when it fires, so it's clear which reached an agent.

Claude first proposed gates + `SubagentStart` + a short CLAUDE.md pointer
for the main session + `--append-subagent-system-prompt` for headless runs.
The final recommendation replaced the CLAUDE.md pointer with a
`SessionStart` hook and dropped the flag.

### B.2 The gaps the delivery layers leave

1. **Decisions made only in code** — e.g. `bm-executor` adds a repository
   layer in a client repo where code called the database directly, or splits
   one module into three. Common; most are fine since code structure is an
   allowed kind. Covered by the reviewer; lint rules (deferred) for the
   mechanical principles; own orchestration (deferred) would cover it with
   prompt-level rules.
2. **Decisions an agent doesn't notice it's making** — e.g. caching in memory
   instead of the shared cache while fixing a bug, adding a retry loop,
   changing pagination. The logging gate depends on self-report, so it misses
   these. Most common, hard to estimate. Covered by the reviewer (reads the
   diff) and a phase-end audit (undecided).
3. **The executor's Rules 1–3** — Rule 1 fix bugs, Rule 2 add missing
   critical functionality (validation, error handling, auth checks), Rule 3
   fix blockers (types, env vars, build config); GSD says "no user permission
   needed". Already limited: Rule 3 may not run a package install as an
   auto-fix; a failed or not-found install goes to a blocking
   `checkpoint:human-verify` (`gate="blocking-human"`; no substitute names,
   no retries); installs a plan task calls for are not stated to be
   blocked. Rule 4 stops for architectural changes, and every deviation goes
   to `SUMMARY.md` with a "Cost if wrong" line. Deviations are tagged
   `[Rule N - Type]` in `SUMMARY.md`, which the after-each-plan reviewer and
   decision extraction could match on (not discussed with James); a new DB
   column is decided alone under Rules 1–2, while a new table is Rule 4.
   Covered by the after-each-plan review; own orchestration (deferred, PLAN
   §4.14) would cover it by replacing the executor for the work routed through
   it.
4. **Discuss steps that never ask** — infrastructure phases and
   `workflow.skip_discuss=true`. E.g. an "upgrade Flutter" phase judged
   infrastructure, so the planner picks the migration approach unasked.
   Covered by the infrastructure-skip check; `skip_discuss` already off.

What stays unprevented: a judgement call made in text inside a GSD step that
the reviewer misses; James's review sessions find it after the fact, as
would a phase-end audit if one is built (PLAN §8.3), so it can be undone,
not stopped.

### B.3 Gap fixes and their costs

- **Reviewer gate** — build: one hook package (prompt or agent hook,
  matchers for `SubagentStop` and `Stop`; the `git commit` and `bm-sdk …
  commit` matchers were for the rejected every-commit option), moderate.
  Running: ~3k tokens a typical check, ~12k at p90; at every commit plus stops
  roughly 20–30M tokens a year (an early figure, superseded by B.4's tables
  and the chosen review points; what "stops" added to the commits was not
  broken down). Cheap background tier by default. Seconds per check (timeouts
  30 s prompt / 60 s agent). Upkeep low. Risk: false blocks; agent type
  experimental. **Chosen**, at the review points in B.4.
- **Structural lint rules** — build: highest (dependency-cruiser for the JS/TS
  repos, `custom_lint` for Dart, an analyser or depguard for Go, deptrac for
  PHP; config committed per repo, via GSD in GSD repos and a PR everywhere).
  Running: no tokens. Upkeep: a rule per lintable principle across every
  repo's config. Enforcement as proposed: a gate runs the rules when an agent
  finishes and before `git commit`, and blocks on a violation; enforced only
  for principles that can be written mechanically, one rule per principle,
  added as principles are confirmed. **Deferred.**
- **Own orchestration** — build: high (Workflow scripts for discuss, plan,
  execute). Running: about the same tokens as GSD runs. Upkeep: ongoing;
  misses GSD's improvements. Strength (option text): "Prompt-level strength,
  no GSD conflict", since the decision rules sit in the scripts' agent
  prompts. **Deferred.**
- **Buildomator proposal** — a GitHub issue at `buildomator/buildomator`
  asking for a decision-policy file GSD's agents read. Build low; no upkeep
  if accepted; may be declined or take months; public, needs approval of
  exact text. **Dropped by James.**
- **Configuring GSD steps** — keep `skip_discuss` off; check infrastructure
  skips. Near-zero cost; covers discuss gaps only. **Chosen** (as the
  infrastructure-skip check).

### B.4 Where the reviewer runs

| | Every commit | After each plan | Before each wave | At review (phase end or PR) |
|---|---|---|---|---|
| Hook point | `PreToolUse` on `git commit` and `bm-sdk … commit`, or `Stop`/`SubagentStop` | `SubagentStop` on `gsd:bm-executor` | `PreToolUse` on the Agent call launching the next wave | phase-end audit or PR review |
| Work it sees | all commits | GSD execute runs only | GSD execute runs only | whatever is reviewed |
| Checks a year | a few thousand (from repo history) | ~750–1,000 (estimated, unmeasured; overstates, since only 6–8 of the active repos use GSD: 8 have `.planning/`, 6 a `config.json`, PLAN §8.1) | up to plan count; median phase 1 plan | one per phase or PR; unmeasured |
| Tokens per check | ~3k median, ~12k p90 | ~5–15k | one wave's diff | tens of thousands, chunked |
| Tokens a year | ~12–15M | same diff lines, ~4–5M less repeated overhead | similar to per plan | ~6M less than every commit |
| Found | straight away | before the plan hands back | before dependent work starts | after later work built on it |
| Cost of a catch | one commit | one plan | the last wave; nothing dependent started | can exceed the tokens saved |
| Fits park rule | partly | partly (other plans in the wave carry on) | yes | no |

James ruled out every commit, and review time because it risks too much
rework. **Chosen: after each plan** (wave check rejected as duplicating it;
GSD already waits for every plan in a wave before starting the next).

Main-session work (from four weeks of transcripts):

| | End of turn (repo changed) | Before push or PR | Both |
|---|---|---|---|
| Hook point | `Stop`, only if the repo changed since last review | `PreToolUse` on `git push` and the Bitbucket PR-create call | both |
| Sees | everything changed in the main session, committed or not | only pushed work | everything plus whole-branch view |
| Checks (4 weeks / year) | ~670 / ~8,700 | ~41 / ~530 | ~710 / ~9,200 |
| Tokens per check | ~2–4k | ~20–50k (≈8 commits per push) | both |
| Tokens a year | ~25–35M | ~15–25M | ~40–60M |
| Found | before James sees the reply | after commits/sessions built on it | both |
| Never reviewed | non-git folders; changes outside the working directory unless the hook is told | local-only repos, uncommitted work, abandoned branches, `~/claude-sandbox` | as end of turn |

The tokens-a-year row is the original estimate; checks × tokens per check
gives ~17–35M for end of turn and ~11–27M before push.

**Chosen: end of turn, when the repo changed.**

Non-GSD subagents: end of turn already covers most (their edits land in the
working tree during the turn), except worktree-isolated agents and background
agents outliving the turn. Options: `SubagentStop` for agents that changed
code (**chosen** — same boundary as the after-each-plan review), or widening
the end-of-turn check to scan worktrees and late changes (rejected — catches
background work later, only when a later turn runs).

Out-of-GSD work kinds, every one of which James included: `/gsd:fast` (runs
inline, no subagent — `workflows/fast.md`); main-session work in the active
repos without `.planning/`; non-GSD subagents that change code; Claude's
recommendations in ordinary sessions. `/gsd:quick` runs `bm-planner` and
`bm-executor`, so the after-each-plan review covers it (`workflows/quick.md`;
it can also spawn other agents, D.3).

### B.5 Other tools

- **Layers that work with any tool inside Claude Code:** `SessionStart` and
  `SubagentStart` blocks, gating hooks, end-of-turn review, `SubagentStop`
  review, the question record and its channels.
- **GSD-only layers:** after-each-plan review (matches `gsd:bm-executor`),
  infrastructure-skip check (GSD's minimal `CONTEXT.md`),
  `gsd_add_decision` (if used, PLAN §8.3), blocker mirroring.
- **Outside Claude Code** (other AI tools or editors): nothing applies.
- Plan-review boundary built as one reviewer with adapters (chosen) rather
  than a separate check per tool (copies drift) or GSD only.

### B.6 Packaging options considered

- **Two packages** (voice, decisions, pipeline split between them):
  rejected — shared extraction/anonymising/embedding code duplicated or
  entangled; a privacy fix in one copy and not the other sends data
  un-anonymised.
- **Three packages** (pipeline, voice, decision runtime incl. question
  record): superseded. Each released on its own (a reviewer fix ships
  without touching voice, a labelling change without touching the hooks);
  three installers, test suites and INVENTORY.md rows; a format change
  means coordinated releases.
- **Four packages** (three + question record split out): first offered as
  worth it only if the store would have other uses; after James's coupling
  point Claude recommended it outright, because anything else needing to
  ask mid-run would otherwise depend on the whole decision runtime.
- **Five packages** (four + `embedding-lib`): **chosen**, after James said
  coupling matters more than package count and pointed to the rrc/rrcd split.
- Embedding environment options: shared environment in the data directory
  set up by the pipeline (rejected — runtime packages would depend on the
  pipeline having run its setup); each runtime package installs its own
  (rejected — two copies, ~1 GB each); a small embeddings package
  (**chosen**).
- Working names before the final names: `embeddings`, `question-store`,
  `voice-decisions-pipeline`, `voice-model`, `decision-runtime`. Prefix sets
  offered and not chosen: `proxy-*`, `persona-*`, `delegate-*`. Suffix set
  Claude proposed: `voice-decision-builder`, `voice-runtime`,
  `decision-runtime`, `embedding-lib`, `question-store`; James changed
  `-builder` to `-pipeline`. His naming rule: a suffix naming what the
  package does, with the voice/decision prefixes kept (PLAN §5).

### B.7 The rrc/rrcd pattern followed

From `/mnt/sda/Development/github-lenny1882/claude-skills/packages/`:
`repo-remote-control-server` (rrcd) builds on `repo-remote-control-session`
(rrc), "which has to be installed first". Shared code (finding the repo,
trust, the lock, reading output) is in the session package's
`skill/lib/rrc-lib.sh`, which defines functions and runs nothing. `rrcd`
loads it from the session skill's directory, never `PATH`, checks
`RRC_LIB_VERSION` and refuses any other; the server install's `verify_probe`
fails without it (`repo-remote-control-server/DESIGN.md`, decided 2 Nov
2026). rrc and rrcd keep everything they write in the skill's `state/`,
which reinstalls keep.

### B.8 Embedding model options

| Model | Size | Context | Trade-off |
|---|---|---|---|
| `all-MiniLM-L6-v2` | ~90 MB | 256 tokens | fastest, weakest |
| `bge-small-en-v1.5` | ~130 MB | 512 tokens | fast, decent |
| `bge-base-en-v1.5` | ~440 MB | 512 tokens | better matching, CPU-friendly — **chosen** |
| `nomic-embed-text-v1.5` | ~550 MB | 8,192 tokens | whole threads, slower |

Estimate: tens of minutes to embed ~17k messages on this machine's CPU, once;
later runs add only new messages (unless the model changes and the pipeline
re-embeds, PLAN §5).

Install: `sentence-transformers`, CPU-only PyTorch, and
`BAAI/bge-base-en-v1.5` downloaded from Hugging Face (a network host the
install needs). Claude's reasons for it: well-tested English model, runs on
this CPU, good at short informal text. First proposed for the data
directory's own environment beside spaCy; later moved into
`embedding-lib`.

### B.9 Local-only vs API work

Local (nothing sent): corpus building, context, exclusions, redaction, all
measured statistics, audience grouping by channel and members, candidate
filtering, hold-back sets, dating. Needs a model: purpose labelling,
decision extraction, writing the guide and principles, choosing exemplars
that sound right, validation drafts and predictions. Anonymising options
reviewed: lists replace reliably (users.json names, client names, contact
details, client URLs); free-text names not in users.json, first names that
are common words (Will, Mark), identifying product/store/project names and
identifiable substance get through — hence spaCy.

Ways offered to cut what is sent: filter locally first (decisions phrased
unusually get missed), or a local model (none installed, no working GPU
visible; a small CPU model would be slow and much
weaker at judgement). Neither was chosen; James asked instead whether text
could be anonymised first.

---

## C. Rejected or dropped, and why

- **Jira as a source** — James dropped it (after hearing
  comment counting needs a per-issue scan). Claude had proposed it for
  James's formal written voice and for decisions on scope and approach;
  neither has a replacement source.
- **Email and documents as sources** — offered in Claude's first question
  about sources; James didn't name them (PLAN §1).
- **Transcripts as a voice source** — James, in a message sent mid-turn,
  limited Claude Code transcripts to technical decisions (stored in the
  transcript as a `queued_command` attachment). Claude's added reason: prompts
  are written to Claude, not colleagues.
- **Bitbucket outside `oneiota`** — Claude recommended all the cloned repos
  (personal and other-client repos show James's decisions when nobody else is
  steering); James chose `oneiota` only, and not all of its repos, and gave no
  reason. The option he adapted said it "Keeps to one employer's codebases and
  conventions; loses the personal and other-client repos."
- **A claude.ai page for questions** — James chose push, session and Slack;
  the page would send question text off the machine.
- **Anonymised Slack questions / notice-only Slack** — James chose real names
  in his own Slack DM.
- **Labels only / similarity only** for exemplars — both used together.
  Similarity alone (no labels) handles mixed messages better, but gives the
  guide nothing to state rules against and is harder for James to check.
  Labels alone need nothing installed. More purposes thin out small
  audiences: ten would leave some client cells with a handful of examples
  or none (Claude's reasons).
- **Curated exemplar bank** (150–300 messages James has seen and approved;
  every exemplar vetted, but unusual situations get weak matches) / **both,
  bank preferred** (bank first, whole corpus when nothing in the bank is
  close enough) — whole filtered corpus chosen (recommended): best matches for
  unusual situations; the pool searches locally.
- **CLAUDE.md wins for outward drafts** ("drafts read as a tidied-up you") /
  **decide per rule** (Claude lists each point of disagreement with examples
  and James chooses for each) — James's voice wins outward.
- **No label check** (labels used as assigned; errors show up only in the
  validation drafts) — James chose his sample and a second model, in
  parallel. The second-model option said: less of his time, more API use.
- **Skill only** (loads only when its description matches) / **reference
  file + CLAUDE.md** (no skill or package) for voice loading — skill +
  CLAUDE.md line chosen.
- **Fixed 5-message context / whole day's context** — thread or 2-hour
  window chosen. Fixed 5: simple, predictable size, but cuts long
  discussions short and drags in unrelated chatter after a quiet spell.
  Whole day: most context, but roughly multiplies corpus size several times
  over. The chosen option's reason: it follows how Slack conversations
  actually run.
- **Prompts alone / reply only** for transcripts — reply plus tool summaries
  chosen. It was not the recommended option; the option text said it
  roughly doubles the size of the transcript part (the size table's ≤0.7M
  words / ≤5 MB already included 10,032 tool-call summaries).
- **Path and line only / local-clone lookups** for PR comments — widen the
  token chosen.
- **Session temp directory or `/mnt/sda/User`** for the corpus —
  `~/claude-sandbox/voice-decisions-data` chosen.
- **Block mid-run / park until phase end** — park, continue independent work,
  stop dependent work, hold back new work.
- **Lookup only / full summary always** for agents — short rules + lookup.
  Lookup only: smallest context, but an agent that never calls the lookup
  decides exactly as it does today. Full summary always: no lookup step,
  but thousands of tokens per agent, growing with the model.
- **Nearest principle / its own default** when nothing covers — ask James.
- **Silently shaped recommendations / none** — name the principle.
- **GSD profiler as shipped** — run on anonymised copies only.
- **Leave reasons blank / infer without confirming** — infer, James confirms.
- **Exclude relayed decisions** — kept as constraints; count if he agreed.
- **Everything / filtered only** for decision candidates — broad filter plus
  10% sample.
- **Any confirmed case / approve each** for the evidence bar — "3+ cases,
  2+ settings" (two different projects or sources); below that, approval.
- **All updates in sessions / all live** — answers live for the exact
  question, rest in sessions.
- **Grading only / model judge only** for voice and decisions — both in
  parallel.
- **Accuracy threshold alone / judge from results** for the decision pass
  mark — all of them, starting high, with trust levels to lower it.
- **Equal weighting of written records / no written records** — weighted by
  origin (equal weighting would turn Claude's bulk-accepted recommendations
  into James's principles; no records would keep to Slack, PRs and
  transcripts).
- **Keeping the question record separate from the decision log** — answers
  copied in. Cost of copying: a few lines plus tests in `decision-runtime`,
  one small entry per answered question, no tokens, one extra entry field
  (asked or made alone). Benefit: review sessions, rebuilds and trust-level
  stats read one log, and decisions made alone can be compared with what
  James was asked in similar situations. Kept separate, every consumer
  would join the two records on the question id; nothing could drift.
  Copied in, drift is handled by superseding entries. James chose copying in.
- **Newer position wins automatically, change flagged** (Claude's proposal,
  twice) — replaced by James's rule: both kept and marked unresolved, every
  conflict listed for him once the work is finished (PLAN §2.4). Claude's
  reason: Slack thins out in 2026 and the transcripts are the newest
  source.
- **Record and add** (approved drafts join the exemplar pool automatically)
  / record only / nothing recorded — recorded and kept, fed back in review
  sessions (PLAN §3.8).
- **Local model for labelling and extraction** — slow and weaker on this
  CPU; anonymise-then-send chosen (B.9).

---

## D. References checked

### D.1 Claude Code (docs: https://code.claude.com/docs/en/hooks,
https://code.claude.com/docs/en/sub-agents,
https://code.claude.com/docs/en/memory,
https://code.claude.com/docs/en/workflows)

- `SubagentStart`: `hookSpecificOutput.additionalContext` supported ("context
  only", inserted before the first prompt); input has `agent_id`,
  `agent_type`, no prompt; matcher by agent type, plugin-scoped names such as
  `^my-plugin:reviewer$` need `^…$`. Doesn't support prompt or agent hook
  types.
- Subagents load user and project CLAUDE.md except Explore, Plan and agents
  with `omitClaudeMd: true`; plugin agents and `@`-imports inside subagents
  not stated. Main-session auto memory isn't loaded into subagents.
- `skills:` frontmatter preloads full skill content (first 32 names; not
  skills with `disable-model-invocation: true`); works without `Skill` in
  `tools`; plugin agents unconfirmed. Plugin agents ignore `hooks`,
  `mcpServers`, `permissionMode` frontmatter.
- `PreToolUse` `updatedInput` replaces the whole input; Agent is in the
  matcher list; `AskUserQuestion` and `ExitPlanMode` need `updatedInput`
  paired with "allow" (relevant to `-p` runs).
- `--append-subagent-system-prompt` (v2.1.205+, non-interactive only),
  `--append-subagent-system-prompt-file` (v2.1.261+).
- A user-level agent with the same name beats a plugin agent (managed
  settings > `--agents` > `.claude/agents/` > `~/.claude/agents/` > plugin).
- Prompt (`type: "prompt"`) and agent (`type: "agent"`, experimental) hooks
  on PermissionDenied, PostToolBatch, PostToolUse, PostToolUseFailure,
  PreToolUse, Stop, SubagentStop, TaskCompleted, TaskCreated, TeammateIdle,
  UserPromptExpansion, UserPromptSubmit (PermissionRequest: prompt only).
  Output `{"ok": true}` / `{"ok": false, "reason": …}`; prompt hooks may set
  `"impossible": true`, which lets the stop go ahead despite `ok: false`
  (the reviewer's way out when it can't decide). On Stop/SubagentStop the
  reason is fed back and the turn continues; on PreToolUse the call is denied
  and by default the turn ends (`continueOnBlock: true` returns it as a tool
  error; agent hooks behave as if `continueOnBlock: true`). Input via
  `$ARGUMENTS` (appended to the prompt if the placeholder is absent). Agent
  hooks can use Read, Grep, Glob, up to 50 turns; Bash not confirmed. `model`
  optional (defaults to the background model); timeouts 30 s prompt, 60 s
  agent.
- `SubagentStop` can block (`decision: "block"` + reason becomes the next
  instruction; exit 2 too); input includes `stop_hook_active`, `agent_id`,
  `agent_type`, `agent_transcript_path`, `last_assistant_message`; 8
  consecutive continuations maximum. Agent-frontmatter `Stop` hooks become
  `SubagentStop`.
- `ExitPlanMode` `PreToolUse` input: `plan` (injected from the plan file),
  `planFilePath`, `allowedPrompts` (deprecated); the model's own input is
  usually empty. `PostToolUse` `tool_response` has `plan` and `filePath`.
  Deny reason is shown to Claude. `permission_mode` values: `default`,
  `plan`, `acceptEdits`, `auto`, `dontAsk`, `bypassPermissions`.
- Hook event list (from `claude-package-kit/reference/hook-events.md`) and
  that kit's reference files: `hook-events.md`, `layout.md`, `monorepo.md`,
  `release.md`, `upgrade.md`.
- workflow-authoring reference: workflow agents get the same CLAUDE.md
  files as the main session (except built-in types that omit them, such as
  Explore and Plan). `agent()` takes `agentType`, so a workflow agent can
  run as a custom or built-in type instead of the default
  `workflow-subagent`; its `SubagentStart` matcher value would then differ.

### D.2 Hook behaviour, tested on 9 Nov 2026

- `SubagentStart`, `PreToolUse` and `SubagentStop` fire for workflow agents
  (agent type `workflow-subagent`) and for GSD plugin agents.
- GSD executors end with a `SubagentHandback` tool call, then `SubagentStop`
  a second later. So a `PreToolUse` hook matching `SubagentHandback` could be
  a second point at which a plan's hand-back is caught, before `SubagentStop`
  (PLAN §8.3).
- A hook in the global settings fires in every session running on the
  machine, so a hook `decision-runtime` installs globally would too.
- Main-session `PreToolUse` calls carry `agent_type` and `agent_id` as null;
  subagent calls carry both, so one gate or reviewer hook can tell
  main-session calls from subagent calls (relevant to the end-of-turn vs
  `SubagentStop` split and the shared review record).
- A `SubagentStop` can carry an empty agent type (`""`, not null), seen for an
  agent started before the hook was installed. A hook that matches
  `SubagentStop` by agent type would not match it.
- Plan mode: a `PreToolUse` hook can deny `ExitPlanMode`; the mode stays
  `plan`, the plan file can still be written and edited, and Bash still runs,
  so a denied plan is revised and resubmitted, and the revised plan then
  passes. Plan mode's rule that nothing but the plan file may be edited is
  documented, not tested.

### D.3 GSD 5.1.0 (paths relative to the plugin directory)

- `workflows/autonomous.md`: L3 "Pauses only for explicit user decisions
  (grey area acceptance, blockers, validation requests)", so a parked
  question pauses a run only through the blocker route; `--interactive`
  runs discuss inline (L56); `workflow.skip_discuss` read at L191–263 ("false
  (or unset)" runs discuss); non-interactive uses `smart_discuss` (L274, step
  at L536); `iterate` reads `STATE.md` blockers and goes to `handle_blocker`
  (Fix and retry / Skip this phase / Stop autonomous mode). With
  `workflow.skip_discuss=true`, `autonomous` writes a `CONTEXT.md` marked
  "Mode: Auto-generated (discuss skipped via workflow.skip_discuss)", saying
  all implementation choices are at Claude's discretion, and commits it with
  `bm-sdk query commit "docs(NN): auto-generated context (discuss skipped)"`
  (L216–258); the same check as the infrastructure skip could match it if
  `skip_discuss` is ever turned on. Success criteria: "No kickoff
  confirmation: phase plan is shown then execution begins in the same turn";
  "Discovered constraints surfaced as one-line notices that are acted on, not
  as gates that wait for a reply"; each phase runs "smart discuss → ui-phase →
  plan → execute → ui-review".
- `references/autonomous-smart-discuss.md`: infrastructure detection at
  L97–107 (goal keywords scaffolding, plumbing, setup, configuration,
  migration, refactor, rename, restructure, upgrade, infrastructure; technical
  success criteria only; no user-facing behaviour; displays "Phase
  ${PHASE_NUM}: Infrastructure phase — skipping discuss, writing minimal
  context." and goes straight to a minimal `CONTEXT.md`, whose defaults
  include "`<domain>`: Phase boundary from ROADMAP goal"); pre-selects a
  recommended answer from prior decisions, codebase patterns, domain
  conventions, ROADMAP criteria (L130); asks "Accept these answers for {Area
  Name}?" via AskUserQuestion (L151).
- `agents/bm-executor.md`: project `./CLAUDE.md` treated as hard constraints
  (L59); decision authority — stop only at `checkpoint:*` tasks (L116); it
  also says "resolve GSD-internal mechanics yourself and record them as
  deviations (which fix to apply, how to sequence, isolate-vs-work-on-main,
  safe or obvious gap handling)" and "Do not invent an ad-hoc pause to ask
  the user about mechanics", which pulls against the park rule for anything
  outside the three kinds that the executor treats as mechanics; deviation
  rules L147–246; package-manager installs not auto-fixable under Rule 3; a
  failed or not-found install returns a `checkpoint:human-verify` task with
  `gate="blocking-human"` (L180–198). The checkpoint asks James to verify that
  the package exists and is legitimate (an npmjs.com link), confirm the name
  in `PLAN.md`, and if it doesn't exist re-run `/gsd:plan-phase
  --research-phase <N>`. He resumes by typing "verified" with the correct
  name, or "abort" to stop the phase; Rule 4 asks about architectural changes
  — new table, major schema changes, new service layer, switching
  libraries/frameworks, changing auth, new infrastructure, breaking API
  changes (L205–211); code commits via `git add` per file and `git commit`
  (L496–525), sub-repo via `bm-sdk query commit-to-subrepo` (L519), docs via
  `bm-sdk query commit` (L704). In worktree mode it can also move WIP off the
  tree by committing it to a throwaway branch (`git checkout -b
  scratch-/<task>-wip && git add -A && git commit -m "wip"`, L563), which
  lives in the per-worktree namespace. Those `git commit` calls would match a
  commit gate, and they create commits on a branch the per-repo review record
  (PLAN §4.5) doesn't track. `bin/lib/commands.cjs` L339 runs `git commit -m`,
  or `git commit --amend --no-edit` when asked to amend, and L409 runs `git
  commit -m` in a sub-repo. These run inside Node, so a Bash `git commit`
  matcher never sees them; only a match on the `bm-sdk` command does. An amend
  rewrites a commit that may already have been reviewed, which the per-repo
  record of the last reviewed commit has to handle.
  `bin/lib/shell-command-projection.cjs` L385 and `craft-skill-insert.cjs`
  L120 (`rev-parse HEAD`) also call git through `spawnSync`; what L385 runs
  was not read.
- `workflows/quick.md`: spawns `bm-planner` (quick mode) and
  `bm-executor`(s) (L2, L24). It also has `subagent_type` calls for
  `gsd:bm-phase-researcher` (L411), `gsd:bm-planner` (L469) and
  `gsd:bm-plan-checker` (L532); when those run was not read. It tracks tasks
  in `.planning/quick/` and updates `STATE.md`'s "Quick Tasks Completed"
  table, so it needs `.planning/`.
  `workflows/fast.md`: inline, never spawns a subagent.
- `workflows/profile-user.md`: consent gate; `bm-sdk query profile-sample`
  (L148); spawns `bm-user-profiler` with the sample (L157–168); asks whether
  to write the profile to project CLAUDE.md, global CLAUDE.md or neither
  (L334–367). `references/user-profiling.md`: 8 dimensions — communication
  style, decision speed, explanation depth, debugging approach, UX
  philosophy, vendor philosophy, frustration triggers, learning style; 3
  quotes each; recent 30 days weighted ~3×. It also has "Sensitive Content
  Exclusion (Layer 1)" (L449), "Natural Language Priority", "Thin Data
  Handling" with "Message Thresholds" (L504–) and "Cross-Project
  Consistency"; these headings were listed but not read (PLAN §8.3). Never
  run here: no profile file, no CLAUDE.md section.
- `workflows/discuss-phase.md`: `--power` routes to
  `workflows/discuss-phase/modes/power.md` (L18, L136); writes questions to a
  file for answering at your own pace. A second file,
  `workflows/discuss-phase-power.md`, also defines power mode (L8). In power
  mode James can say "refresh", "finalize", "explain Q-N" or "exit power
  mode" (back to one-by-one discussion, answers kept). Flag precedence such
  as `--auto --power` is documented in each overlay file's "Combination
  rules" section (`discuss-phase.md` L364), which was not read.
- `README.md`: repository `github.com/buildomator/buildomator`; original
  `gsd-build/get-shit-done` locked; community continuation
  `open-gsd/get-shit-done-redux`; Buildomator reads `.agents/workspace.json`
  at SessionStart (L400; spec https://github.com/workspace-json/spec, also
  linked at L433). Contribution rules not read.
- `~/.claude/hooks/check-discuss-batch.sh` L32: skips when args carry
  `--batch`, `--no-batch`, `--auto` or `--power`.

### D.4 OpenSpec (https://github.com/Fission-AI/OpenSpec)

Change folder `openspec/changes/<change>/` with `proposal.md`, `specs/`,
`design.md`, `tasks.md`; archive to
`openspec/changes/archive/<date>-<change>/`; specs use `## ADDED
Requirements`. Commands (default profile) `/opsx:explore`, `/opsx:propose`,
`/opsx:apply`, `/opsx:archive` (`/opsx:propose` writes the plan,
`/opsx:apply` implements it, `/opsx:archive` files it away); expanded profile
adds `/opsx:new`, `/opsx:continue`, `/opsx:ff`, `/opsx:verify`,
`/opsx:bulk-archive`, `/opsx:onboard` (set with `openspec config profile`,
applied with `openspec update`). No formal approval gate ("no rigid phase
gates"); Claude's summary: "you're expected to review the plan before code is
written, and any file can change at any time" (PLAN §8.3). Subagents not
documented.

### D.5 grill-me / grill-with-docs (https://github.com/mattpocock/skills)

- `skills/productivity/grill-me/SKILL.md`: `disable-model-invocation: true`;
  calls the `grilling` skill.
- `skills/engineering/grill-with-docs/SKILL.md`: calls `grilling` and
  `domain-modeling`; "creates docs (ADR's and glossary) as we go".
- `skills/productivity/grilling/SKILL.md`: every question carries a
  recommended answer ("➡️ <your recommended answer>"; "Word each question so
  "yes" accepts your recommended answer"); asks the whole frontier in one
  numbered round; facts are its job ("dispatch a sub-agent with a fresh
  context window"); "The decisions are the user's: put each to them and
  wait."; writes no files.
- `skills/engineering/domain-modeling/SKILL.md`: `GLOSSARY.md` (root, or per
  context via `GLOSSARY-MAP.md`), updated inline; ADRs in `docs/adr/` (e.g.
  `0001-event-sourced-orders.md`), offered only when hard to reverse,
  surprising without context, and a real trade-off.
- Install routes listed by third parties: `claude plugin install
  mattpocock-skills@claude-plugins-official`, or `npx -y skills add
  mattpocock/skills --skill grill-with-docs --agent claude-code`. The name
  is `grill-with-docs`, not `grill-me-with-docs`. Also seen:
  https://www.aihero.dev/grill-with-docs.

### D.6 Bitbucket auth (`~/.claude/auth-recipes/bitbucket.md`)

A Bitbucket API token in `~/.netrc` is used. PR titles,
descriptions and comments can be read with that token as it stands,
fetched per repo through the API; only the code under inline
comments needs `read:repository`. No
`read:repository`, so branch refs (`/refs/branches/<branch>`, gotcha 5) and
PR diffstat (302 then 403, gotcha 8) are refused. Recipe workaround without
the scope: read a PR's file list from the local clone with `git diff
--name-status <base-sha>...<head-sha>`, after checking `.git/FETCH_HEAD` is
not stale (the local-clone route rejected in C). Git uses SSH; the token is
REST only, passed with `curl -n` and never read or echoed. "Network refused /
connection blocked" is the Claude Code sandbox, so pipeline API calls from
Claude's Bash tool need `api.bitbucket.org` allowed or an unsandboxed run.
Verified in use: the auto-mode classifier blocks only commands that build a
payload and POST it in one call. The recipe's gotcha 6: SSH keys aren't reachable from Claude's sandboxed
shell, so any `git fetch` to refresh the local clones before reading them has
to run unsandboxed or in James's terminal.

