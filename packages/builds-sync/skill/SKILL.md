---
name: builds-sync
description: Use when the user wants to install a voice or decision build on this machine, see which build this machine runs, push this machine's live records (drafts, decision log, questions) to the builds repo now, or check for a newer build. Runs the builds-sync command, which owns the encrypted builds repo's clone, the age key and every pull, commit and push.
allowed-tools:
  - Bash
  - Read
---

# builds-sync

Wraps the `builds-sync` command in `~/.local/bin`, which does the work. Do not
reimplement its steps by hand (no `git` in the clone, no `age` on its files):
the command is what refuses plaintext and takes the lock.

```bash
builds-sync status                 # clone, key, newest build, what each runtime runs
builds-sync install [<build-time>] # newest build, or that one
builds-sync push                   # this machine's new live records, now
builds-sync check --force          # look for a newer build now
```

## Installing a build

Installing is only ever done when the user asks. Nothing installs on its own.

1. Run `builds-sync install` (or `builds-sync install <build-time>` for an
   older build) with the Bash tool's `run_in_background`. It can take minutes:
   each runtime embeds the build's new exemplars.
2. Watch `/tmp/builds-sync-install.log` with a monitor that reports every
   `FAIL` line and the final `install finished:` line, which carries the
   result. Poll every 5–10 seconds.
3. Report what the last line says, and each runtime's `ok` or `FAIL` line.
   A runtime that is not installed on this machine is skipped, and says so.

## Pushing and checking

`push` and `check` also run from hooks: `SessionEnd` pushes in the background,
and `SessionStart` shows the notice the last check left and starts the next
check at most once a day. Run them by hand only when the user wants it now.

## The part that is easy to get wrong

A refusal that names files "not encrypted" means something other than
`README.md` and `*.age` is tracked in the clone, or sits in a commit not yet
pushed. Do not work round it by committing or pushing from the clone with
`git`: the repo's history is cloned to every machine and kept, so a plaintext
file pushed once is there for good. Tell the user which files it named and
stop.

Exit status 3 is that refusal; 75 means another builds-sync run holds the lock
(two sessions ending together), and running again shortly is the fix.
