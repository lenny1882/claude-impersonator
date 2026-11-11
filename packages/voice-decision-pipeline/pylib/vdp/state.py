"""Where the pipeline keeps its data, and how it writes it.

All of it lives in ~/.claude/voice-decision-pipeline/ (PLAN §2.2, §5 Data
and state): owner-only (directories 700, files 600, umask 077), never
backed up, kept until James deletes it. Every file is written to a temporary
name and renamed into place, so a run that dies halfway leaves the previous
file whole.
"""

import contextlib
import fcntl
import json
import os
import tempfile

os.umask(0o077)


def root():
    d = os.environ.get("VDP_STATE") or os.path.join(
        os.environ.get("CLAUDE_DIR") or os.path.expanduser("~/.claude"),
        "voice-decision-pipeline")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def path(*parts):
    p = os.path.join(root(), *parts)
    os.makedirs(os.path.dirname(p), mode=0o700, exist_ok=True)
    return p


def corpus_file(source):
    return path("corpus", f"{source}.jsonl")


def anon_file(source):
    return path("anon", f"{source}.jsonl")


def _atomic(dest, write):
    d = os.path.dirname(dest)
    os.makedirs(d, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            write(f)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def write_json(dest, obj):
    _atomic(dest, lambda f: (json.dump(obj, f, ensure_ascii=False, indent=1),
                             f.write("\n")))


def read_json(src, default=None):
    try:
        with open(src, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_jsonl(dest, records):
    def w(f):
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True))
            f.write("\n")
    _atomic(dest, w)


def read_jsonl(src):
    try:
        with open(src, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)
    except FileNotFoundError:
        return


@contextlib.contextmanager
def lock():
    """One writer at a time across the whole state directory."""
    with open(path(".lock"), "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("voice-decision-pipeline: another run holds the "
                             "state lock; wait for it to finish")
        yield


def check_modes():
    """Paths under the state directory that aren't owner-only."""
    bad = []
    for d, dirs, files in os.walk(root()):
        if os.stat(d).st_mode & 0o077:
            bad.append(d)
        for name in files:
            p = os.path.join(d, name)
            if os.stat(p).st_mode & 0o077:
                bad.append(p)
    return bad
