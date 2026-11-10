# claude-impersonator

The packages that build and use two models made from James's own writing
and decisions: a voice model, so Claude can draft Slack messages, PR
descriptions and review comments and Jira comments in his voice for his
approval, and a decision model, so orchestrators and agents can settle some
technical questions the way he would and ask him about the rest. They share one
repo because they share one data format and one embedding environment, and
are built in one order; the plan is `PLAN.md`, the evidence behind it
`APPENDIX.md`. No data is ever committed here: each package keeps its data in
its own state on the machine it runs on, and the tests use made-up fixtures.

Every package under `packages/` is versioned, released and installed on its
own. A fault in one says nothing about another, so each can be fixed and
shipped without touching the rest.

## Packages

| Package | What it does |
| --- | --- |
| [`embedding-lib`](packages/embedding-lib/) | Pinned local text embeddings (`bge-base-en-v1.5`, CPU) on a bundled Python 3.14, with an identity record each index stores so a mismatched one is refused |
<!-- new-package.sh --monorepo adds a row above this line -->

## Install a package

Needs `curl`, `tar` and `jq`. Set `pkg` to a name from the table:

    pkg=<package>
    v=$(curl -fsSL https://raw.githubusercontent.com/lenny1882/claude-impersonator/versions/versions.txt | awk -v p="$pkg" '$1 == p {print $2}')
    curl -fsSL "https://github.com/lenny1882/claude-impersonator/releases/download/$pkg-v$v/$pkg.tar.gz" | tar -xz
    cd "$pkg" && ./install.sh

`versions.txt` lists each package's newest stable version. The release workflow
writes a package's line only after that release's tarball is uploaded, so the
lines above never change between versions and always fetch something that
exists. To pin a version instead:

    https://github.com/lenny1882/claude-impersonator/releases/download/<package>-vX.Y.Z/<package>.tar.gz

Each package's own README has the same lines with its name filled in, and
covers updating and uninstalling.

## Tests

    ./test/run-tests.sh

Runs every package's own suite, one section each, and fails if any of them
does.

## Releasing

`/release <package>` in this repo — bump `packages/<package>/VERSION` on
`main`, move `release/<package>-vX.x` onto it, and tag `<package>-vX.Y.Z` there.
The tag is what publishes it. See `.claude/skills/release/SKILL.md`.
