# builds-sync

Carries voice and decision builds, and the live records the runtimes write,
between machines through one private git repo in which every file is
encrypted with `age`.

Builds go from the building machine to every machine; the records the
runtimes write (drafts and their approved versions, the decision log,
answered questions) come back. This package owns the clone, the key, `age`
and every pull, commit and push; the pipeline and the runtimes go through its
library and never touch the repo themselves.

Part of [claude-impersonator](https://github.com/lenny1882/claude-impersonator), which holds several packages
that are each versioned, released and installed on their own.

## What you actually see

At session start, when the last daily check found a newer build than the one
this machine runs, one line:

    builds-sync: build 20261103T100000Z is in the builds repo (installed: voice-runtime 20261102T100000Z). Install it with: builds-sync install

Nothing installs on its own. `builds-sync install` (or asking Claude, through
the skill) decrypts the build and hands each runtime installed here its part;
it logs to `/tmp/builds-sync-install.log` and ends with an
`install finished:` line. At session end this machine's new live records are
pushed in the background; nothing is shown.

`builds-sync status` says where the clone is, whether the key is there, the
newest build in the clone and on the remote, which build each runtime here
runs, and how much of each live file is not yet pushed.

## Install

Needs `curl`, `tar`, `jq`, `git`, `python3` (3.8 or newer, stdlib only), and
`age` with `age-keygen`. The key goes at `~/.config/age/builds.key`, mode
600, copied there by hand. From the newest release:

    v=$(curl -fsSL https://raw.githubusercontent.com/lenny1882/claude-impersonator/versions/versions.txt | awk '$1=="builds-sync" {print $2}')
    curl -fsSL "https://github.com/lenny1882/claude-impersonator/releases/download/builds-sync-v$v/builds-sync.tar.gz" | tar -xz
    cd builds-sync && ./install.sh

These lines never change between versions: `versions.txt` names the newest
stable release, and only once its tarball is uploaded. To pin a version,
download `.../releases/download/builds-sync-vX.Y.Z/builds-sync.tar.gz` instead.

    ./install.sh              # install; asks once where the clone is
    ./install.sh --yes        # no prompts; run builds-sync setup afterwards
    ./install.sh --link       # or symlink, so edits in the checkout are live
    ./install.sh --dry-run    # show the settings change, write nothing

The first install asks where the builds repo's clone is on this machine, and
for its git URL if it has to clone it; `builds-sync setup --clone <path>
[--remote <url>]` does the same at any time. It installs the skill in
`~/.claude/skills/builds-sync/`, the command in `~/.local/bin/builds-sync`,
a `SessionStart` (matcher `startup`) and a `SessionEnd` hook that call it, and
`builds-sync *` in `sandbox.excludedCommands`, because the command writes its
state and the clone and reaches the network. Re-running the installer is safe
and is how you upgrade; it merges into `settings.json` and touches only its
own entries.

## Commands

    builds-sync setup [--clone <path>] [--remote <url>] [--yes]
    builds-sync install [<build-time>]      the newest build, or that older one; manual only
    builds-sync check [--force]             look for a newer build; at most once a day
    builds-sync push                        this machine's new live records, now
    builds-sync status
    builds-sync publish <tar> --build-time <bt>    the pipeline's, through the library
    builds-sync pending                     what a push would send, as JSON
    builds-sync hook session-start|session-end     what the hooks run

Exit 3 is a refusal: something other than `README.md` or a `.age` file is
tracked in the clone or sits in an unpushed commit. Exit 75 means another
builds-sync run held the lock for longer than `BUILDS_SYNC_LOCK_TIMEOUT`
seconds (default 120).

Environment: `BUILDS_SYNC_CLONE` (the clone, over what setup recorded),
`BUILDS_SYNC_KEY` (the key, over `~/.config/age/builds.key`),
`BUILDS_SYNC_HOSTNAME` (the `live/` directory name, over the short hostname),
`BUILDS_SYNC_INSTALL_LOG`, `BUILDS_SYNC_LOCK_TIMEOUT`, `CLAUDE_DIR`.

## For dependents

The library is loaded by path from the install directory, never through
`PATH`, and checked for its API version:

    ~/.claude/skills/builds-sync/lib/builds_sync.py

    import importlib.util, os
    p = os.path.join(os.environ.get("CLAUDE_DIR") or os.path.expanduser("~/.claude"),
                     "skills", "builds-sync", "lib", "builds_sync.py")
    spec = importlib.util.spec_from_file_location("builds_sync", p)
    bs = importlib.util.module_from_spec(spec); spec.loader.exec_module(bs)
    assert bs.BUILDS_SYNC_API == 1

    bs.publish_build(tar_path, build_time)   # -> "builds/<build-time>.tar.age"; encrypts, commits, pushes
    bs.read_live("voice-runtime")            # -> [dict, ...]: every machine's segments, pulled first
    bs.install_dir()                         # -> ~/.claude/skills/builds-sync

Errors are `bs.BuildsSyncError` (a refusal is its subclass `bs.Refused`, a
held lock `bs.LockBusy`), with a message saying what to do. `read_live`
joins segments in push-time order and keeps a record repeated exactly (the
same JSON with sorted keys) once; choosing the newest line per id is the
caller's job. It returns what has been pushed: this machine's records join
once a session ending, or `builds-sync push`, sends them.

A runtime receives a build as

    <runtime> install-build <tmp>/<runtime> --build-time <bt>

run for each top-level directory of the build tarball whose runtime command
is on `PATH`, from a temp directory of mode 700 that is removed afterwards.
The runtime copies what it needs into its own state; builds-sync never writes
there. It reads each runtime's `manifest.json` to say which build runs here.

## Update

    ./update.sh            check, ask, upgrade, reinstall
    ./update.sh --check    report what is available and stop

Reads this package's line in `versions.txt`, so pre-releases, and releases of
the other packages in the repo, are never offered. Works from a downloaded
tarball as well as a clone, no git needed. This is the package's own release
notice, separate from the build notice above.

## Uninstall

    ./uninstall.sh                 ask before editing settings.json
    ./uninstall.sh --keep-settings leave settings.json alone
    ./uninstall.sh --keep-state    keep the package's state for a later reinstall

The uninstall refuses while this machine has live records or commits not yet
pushed, unless `--keep-state` is given; `builds-sync push` first clears that.
The clone is left where it is.

## How it works

The repo holds `README.md` (plaintext, no content), one `.tar.age` per build
under `builds/`, written only by the pipeline, and the live segments under
`live/`: one directory per machine (its hostname) and package, each segment
named by its push time, each machine writing only its own directory. Times are UTC
`YYYYMMDDTHHMMSSZ`. Encryption is `age -e -r <recipient>`, the recipient
derived from the key with `age-keygen -y`; decryption is `age -d -i <key>`.

The live files it carries, relative to `~/.claude`:

| Package | File |
|---|---|
| `voice-runtime` | `skills/voice-runtime/state/drafts.jsonl` |
| `decision-runtime` | `decision-runtime/decision-log.jsonl` |
| `question-store` | `question-store/questions.jsonl` |

State, in `~/.claude/skills/builds-sync/state/`: `config.json` (the clone's
location), `positions.json` (for each live file, the byte offset its last push
stopped at and a SHA-256 of everything before it), `last-check` (the day
stamp), `check.json` (what the last check found), `lock`, and
`last-push.log` (the background push's output).

- **Push** sends only the complete lines added since the last push. A file
  whose start no longer matches the recorded hash (rewritten by a schema
  migration) is sent again from the beginning; the repeats are exact and
  `read_live` drops them. The position moves when the segment is committed,
  so an offline push commits locally and the next push sends the commit; a
  push killed before its commit sends the same records again next time.
- **The plaintext guard** runs before anything is fetched, before each
  commit and before each push, over the index and every unpushed commit. A
  refused push withdraws the segment it wrote and leaves its records pending.
- **The update check** writes the day stamp before `git fetch`, so an
  unreachable remote costs one attempt a day. It only fetches; the clone's
  working tree moves when something is installed, pushed or read.
- **The lock** is one `flock` on `state/lock`, held for every change to the
  clone or the state. The `SessionEnd` hook starts the push detached and
  returns at once, because Claude Code cuts `SessionEnd` hooks short as it
  exits; two sessions ending together queue on the lock, and the second finds
  nothing new.
- Git runs with `GIT_TERMINAL_PROMPT=0` and SSH in batch mode, so a remote
  that wants credentials fails instead of waiting on a prompt no one sees.

## Tests

    ./test/run-tests.sh

Redirects `HOME` and `CLAUDE_DIR` into a temp directory, so your real config is
never touched, and logs to `/tmp/builds-sync-tests.log`
(`BUILDS_SYNC_TEST_LOG` moves it). The remote is a bare git repo in that
directory; `age` and `age-keygen` are stand-ins in `test/fake-bin/` (a
reversible transform that fails without the right key, not encryption), and
`test/fake-runtime/voice-runtime` records its `install-build` call. Two
machines are simulated with `BUILDS_SYNC_HOSTNAME`. `./test/run-tests.sh` at
the repo root runs every package's.

## Releasing

`/release builds-sync` at the repo root — bump `packages/builds-sync/VERSION` on `main`,
move `release/builds-sync-vX.x` onto it, tag `builds-sync-vX.Y.Z` there. The tag is what
publishes it. The release carries what `PAYLOAD` lists, and nothing else in
this directory.
