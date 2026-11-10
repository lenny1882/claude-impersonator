# embedding-lib

Pinned, local text embeddings for the voice and decision models:
`BAAI/bge-base-en-v1.5` on CPU PyTorch, in an environment the package
downloads and owns, on a bundled Python 3.14.

The voice model finds exemplar messages by meaning: the pipeline embeds the
corpus once, and `voice-runtime` embeds each draft's context and searches
that index. If the two embeddings come from different setups — another
model, another library version, another Python — the search still returns
results, just wrong ones, with no error. The machines this runs on don't
share a system Python (this one has 3.8, the WorkSpace 3.12, EndeavourOS
3.14 and moving), so the package brings its own and pins everything, and
each index records exactly which setup built it so a consumer can refuse one
that doesn't match.

Part of [claude-impersonator](https://github.com/lenny1882/claude-impersonator), which holds several packages
that are each versioned, released and installed on their own.

## What you actually see

At install, one question: download about 1.9 GB (Python, libraries, model)
into `~/.local/share/embedding-lib/`? After that, `embedding-lib check`
embeds two related sentences and one unrelated one and reports
`"ok": true`. Reinstalling or updating to a release that changes no pin
downloads nothing.

    $ printf '{"id":1,"text":"Can you review the PR?"}\n' | embedding-lib embed
    {"id": 1, "vector": [0.0153198, 0.023223, ...]}        # 768 numbers, unit length

Nothing touches the network after setup. A missing file is an error naming
the command that fixes it, never a download in the middle of drafting.

## Install

Needs `curl`, `tar`, `jq`, `sha256sum`, about 2.6 GB free, and these hosts
during setup: `github.com` (the Python), `pypi.org` and
`files.pythonhosted.org` (libraries), `download.pytorch.org` (CPU torch),
`huggingface.co` (the model). From the newest release:

    v=$(curl -fsSL https://raw.githubusercontent.com/lenny1882/claude-impersonator/versions/versions.txt | awk '$1=="embedding-lib" {print $2}')
    curl -fsSL "https://github.com/lenny1882/claude-impersonator/releases/download/embedding-lib-v$v/embedding-lib.tar.gz" | tar -xz
    cd embedding-lib && ./install.sh

These lines never change between versions: `versions.txt` names the newest
stable release, and only once its tarball is uploaded. To pin a version,
download `.../releases/download/embedding-lib-vX.Y.Z/embedding-lib.tar.gz` instead.

    ./install.sh              # install; asks before the 1.9 GB download
    ./install.sh --yes        # no prompts, downloads without asking
    ./install.sh --link       # or symlink, so edits in the checkout are live
    ./install.sh --dry-run    # show the settings change, write nothing

Without a terminal and without `--yes`, setup refuses rather than guess, and
the install fails. `embedding-lib setup` on its own repairs or completes an
environment at any time. Setup logs to `/tmp/embedding-lib-setup.log`.

## Commands

    embedding-lib setup [--yes]   download what's missing
    embedding-lib check           embed test sentences; exit 0 if it works
    embedding-lib identity        the JSON record an index stores
    embedding-lib check-identity  stdin: a recorded identity; exit 3 unless it matches
    embedding-lib embed           stdin JSONL {"id","text"} -> stdout JSONL {"id","vector"}
    embedding-lib tokens          stdin JSONL {"id","text"} -> stdout JSONL {"id","tokens"}
    embedding-lib paths           where everything lives

Exit 4 means not set up, or an environment that no longer starts or was
built for other pins; the message says to run `embedding-lib setup`.

## For dependents

Python code that embeds runs on embedding-lib's interpreter, from its install
directory, never through `PATH`:

    ~/.local/share/embedding-lib/venv/bin/python

    import embedding_lib as el
    assert el.EMBEDDING_LIB_API == 1
    vectors = el.embed(["text", ...])          # numpy float32, (n, 768), unit length
    el.count_tokens(["text", ...])             # the model's 512-token limit applies
    record = el.identity()                     # store this beside the index
    el.check_identity(stored)                  # raises el.Mismatch, naming each difference

A dependent's install check fails if `embed` isn't there or
`EMBEDDING_LIB_API` isn't the version it was written for. What counts as a
match is `api`, `model`, `revision`, `dimension`, `normalised`, `python`
and `lock_sha256`; `libraries` is there for people to read, the lock's hash
already covers every version in it.

## Update

    ./update.sh            check, ask, upgrade, reinstall
    ./update.sh --check    report what is available and stop

Reads this package's line in `versions.txt`, so pre-releases, and releases of
the other packages in the repo, are never offered. A release that changes the
bundled Python or the lock rebuilds the environment at install, and changes
`identity()`, so the pipeline re-embeds before the runtimes use the index
again (PLAN §5).

## Uninstall

    ./uninstall.sh                 ask before editing settings.json
    ./uninstall.sh --keep-settings leave settings.json alone

Removes `~/.local/bin/embedding-lib` and all of
`~/.local/share/embedding-lib/`: Python, venv and model. The package holds
no data, so `--keep-state` keeps nothing of note.

## How it works

`~/.local/share/embedding-lib/` holds:

| Path | From | Replaced when |
|---|---|---|
| `pylib/` | the package: the module, `requirements.txt`, `runtime.env` | every install |
| `python/` | python-build-standalone, checked against `runtime.env`'s SHA256 | `runtime.env` changes |
| `venv/` | `pip install --require-hashes --no-deps -r requirements.txt` | the lock or the Python changes |
| `hf/` | the model's files at commit `a5beb1e3` | never, for this model |

`.python-stamp` and `.venv-stamp` record what each was built from; setup
compares them with the package's pins to decide what to download, and every
command refuses an environment whose stamp doesn't match. The venv's stamp is
removed before it is rebuilt and written back last, so one that dies halfway
is rebuilt next time and refused meanwhile.

torch comes from PyTorch's CPU index, not PyPI, whose default build carries
several GB of CUDA libraries.

### Changing a pin

Both pinned files are generated, never edited by hand:

    tools/pin-python.sh <release> <version>    # writes pylib/runtime.env
    tools/lock.sh <path-to-uv>                 # writes pylib/requirements.txt from requirements.in

Either change alters `identity()`, which makes every runtime refuse existing
indexes until the pipeline re-embeds — tens of minutes, once.

## Tests

    EMBEDDING_LIB_TEST_HOME=<a home built by setup> ./test/run-tests.sh

Redirects `HOME` and `CLAUDE_DIR` into a temp directory, so your real config is
never touched, and logs to `/tmp/embedding-lib-tests.log`. Setup's refusals
run against stubbed `curl`, `uname` and `df`. The real-environment tests embed
with the network shut off, against an environment already built, because
building one is the 1.9 GB download; without `EMBEDDING_LIB_TEST_HOME` they
fail, unless `EMBEDDING_LIB_SKIP_REAL=1`. `./test/run-tests.sh` at the repo
root runs every package's.

## Releasing

`/release embedding-lib` at the repo root — bump `packages/embedding-lib/VERSION` on `main`,
move `release/embedding-lib-vX.x` onto it, tag `embedding-lib-vX.Y.Z` there. The tag is what
publishes it. The release carries what `PAYLOAD` lists, and nothing else in
this directory.
