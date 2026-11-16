---
name: voice-runtime
description: Use before drafting anything the user will send to other people — a Slack message or reply, a PR description, a PR review comment, a Jira comment, or any other message in their name — so the draft is written in their voice from their voice guide and their closest real messages. Also use when such a draft is approved, edited or discarded, to record the final version. Not for text Claude writes to the user.
allowed-tools:
  - Bash
  - Read
  - Write
---

# voice-runtime

Drafts for other people are written in the user's voice: the guide for the
audience and purposes, plus the user's closest real messages, from the voice build
installed on this machine. Every step goes through the `voice-runtime`
command; never read the files under `state/` directly, because the command is
what refuses a build it can't trust.

```bash
voice-runtime guide  --audience <a> --purposes <p,...>
voice-runtime search --audience <a> --purposes <p,...> --situation "<text>"
voice-runtime save-draft --audience <a> --purposes <p,...> --destination <d> --text-file <f>
voice-runtime save-final --id <draft id> --text-file <f> [--status approved|discarded]
voice-runtime status
```

## Steps

1. **Work out the audience** from where the draft is going:

   | Going to | Audience |
   |---|---|
   | a client channel, or a DM with a client-side contact | `clients` |
   | an internal project channel, or any other internal channel | `project-team` |
   | a technical channel; any Bitbucket PR description or review comment | `technical-team` |
   | a senior or management channel, or a group DM with those people | `senior` |
   | a one-to-one DM with a colleague | `one-to-one` |
   | a Jira comment | `jira` |

   A group DM of anyone else has no rule: ask the user which audience it is.

2. **Work out the purposes** from the request, in the order the message
   will carry them: `push-back`, `decline`, `ask`, `chase`, `status`,
   `explain`, `approve`, `own-mistake`, `thank`, `escalate`, `small-talk`,
   `other`. A message can have several.

3. **Show both above the draft**, every time, so the user can correct them:

       Audience: technical-team · Purposes: status, ask

   If the user corrects either, run steps 4 and 5 again with their values.

4. **Load the guide**: `voice-runtime guide --audience <a> --purposes <p,...>`.
   The user's own rules come first and win over every other rule in it. For
   `jira`, the Jira section is the rules and there are no exemplars.

5. **Find exemplars**: `voice-runtime search --audience <a> --purposes <p,...>
   --situation "<what the draft has to do, and the message it answers>"`.
   It returns JSON: the closest of the user's messages, each with the message it
   answered. Use them for tone, length, openings and phrasing. Never copy a
   name, client, product or detail out of them: they are anonymised
   (`client-03`, `colleague-12`, `[code]`), and the draft is about the
   situation in hand.

6. **Draft in the user's voice.** For drafts to other people that voice wins over
   the CLAUDE.md writing rules (PLAN §3.5): if the user would apologise, thank, or
   use an exclamation mark to that audience, the draft does too. The CLAUDE.md
   rules still govern everything said to the user around the draft.

   Where a tool sets the format, keep the tool's structure and write only the
   wording inside it in the user's voice: the PR description templates in
   `/gsd:ship` and `/bm:ship`, the comment format of `/code-review
   --comment`.

7. **Save the draft** before showing it. Write the text to a file in
   `$TMPDIR`, then:

       voice-runtime save-draft --audience <a> --purposes <p,...> \
         --destination <d> --text-file <f>

   `<d>` is `slack:<conversation>`, `bitbucket:<repo>#<pr>`, `jira:<key>`
   or `other`. It prints the draft's id; keep it for step 9.

8. **Show the draft and wait.** Nothing is sent, posted or updated without
   the user's explicit approval of the exact text, in that moment. Edits from
   the user are not approval: apply them, show the new text, ask again. Approval
   covers that one text only.

9. **Record the outcome** with the id from step 7:
   - sent as approved, including every edit the user made in the conversation:
     `voice-runtime save-final --id <id> --text-file <final text>`
   - dropped: `voice-runtime save-final --id <id> --text-file <last draft> --status discarded`

   When the user edits the text after it leaves Claude (in Slack, say), record what
   the user approved here; the next build matches it to what was actually sent.

## When the voice model is unavailable

`guide` and `search` exit 3 with one line when there is no build on this
machine yet, when the index was embedded by a different embedding-lib setup,
or when a file has a schema version this release doesn't read. Then, before
drafting:

1. Tell the user the voice model is unavailable and why, quoting the line,
   including the fix it names.
2. Offer to draft anyway, marked at the top as **not in your voice**, written
   to the CLAUDE.md rules. Don't run `save-draft` for it: the record has no
   way to mark a draft as not in the user's voice, and the next build would take it
   as one.

Any other non-zero exit (1, 2) is a mistake in the call, such as an unknown
audience or an empty text file; the message says what. Fix the call rather
than drafting without the model.

## The part that is easy to get wrong

- Skipping the audience and purposes line because they look obvious. It is
  the only place the user can catch a wrong audience, and a wrong audience
  gives a wrong guide and the wrong exemplars with no error: a client
  message drafted in the voice the user uses with developers.
- Treating an exemplar as content. The exemplars show how the user writes, not
  what to say; a pseudonym or `[code]` in a draft means one was copied.
- Saving the final only when the text changed. Approved-as-drafted is the
  strongest evidence the build has; it needs its `save-final` line too.
