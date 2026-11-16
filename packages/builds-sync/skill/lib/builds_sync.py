"""builds-sync: carries builds and live files between machines through one
age-encrypted git repo.

Why this exists. The corpus is built on one machine only, but the runtimes run
on every machine, and the evidence they write (drafts, decisions, answers) has
to come back to the one machine that builds. Copying files by hand loses
records and leaks plaintext into places that keep history, so one package owns
the clone, the key and every pull, commit and push, and everything else goes
through it. The pipeline and the runtimes load this module by path from the
install directory (never from PATH) and check BUILDS_SYNC_API.

Things that look simplifiable and are not:

- Nothing but `README.md` and `*.age` is ever pushed. The repo's history is
  cloned to every machine and kept for ever, so one plaintext file committed
  by mistake is permanent. `check_tracked` looks at the index and at every
  unpushed commit, not just the files this call wrote, and refuses before the
  commit and again before the push.
- A live file is pushed as segments: only the complete lines added since the
  last push. The position is a byte offset plus a hash of everything before it,
  so a file rewritten in place (a schema migration) is noticed and re-sent from
  the start rather than read from the middle of a line. Re-sent records are
  exact repeats, which `read_live` keeps once.
- The position moves when the segment is committed locally, not when it is
  pushed. An offline session commits and the next push sends the commit; a
  session killed before the commit re-sends the same records next time.
- The update check writes its day stamp before `git fetch`, so a remote that
  hangs costs one attempt a day, not one per session start.
- Every write to the clone and the state happens under one lock, so two
  sessions ending together do not interleave commits.

Stdlib only, and Python 3.8-compatible: the command runs on whatever python3
the machine has (3.8 or newer), while the pipeline loads this module on
embedding-lib's bundled 3.14.
"""
from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone

BUILDS_SYNC_API = 1

PKG = "builds-sync"

# Live files this package carries: package -> path relative to CLAUDE_DIR.
LIVE_FILES = {
    "voice-runtime": "skills/voice-runtime/state/drafts.jsonl",
    "decision-runtime": "decision-runtime/decision-log.jsonl",
    "question-store": "question-store/questions.jsonl",
}

# Where each runtime records the build it runs (read only; the runtime writes it).
RUNTIME_MANIFESTS = {
    "voice-runtime": "skills/voice-runtime/state/manifest.json",
    "decision-runtime": "decision-runtime/manifest.json",
}

BUILD_TIME_RE = re.compile(r"^\d{8}T\d{6}Z$")
SEGMENT_RE = re.compile(r"^(\d{8}T\d{6}Z)\.jsonl\.age$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_REFUSED = 3
EXIT_BUSY = 75


class BuildsSyncError(Exception):
    """Something went wrong; the message says what and what to do."""
    code = EXIT_ERROR


class Refused(BuildsSyncError):
    """A push was refused because a tracked file is not encrypted."""
    code = EXIT_REFUSED


class LockBusy(BuildsSyncError):
    code = EXIT_BUSY


# --- paths and settings -------------------------------------------------------

def claude_dir() -> str:
    return os.environ.get("CLAUDE_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def install_dir() -> str:
    """The installed skill directory; the library lives in its lib/."""
    return os.path.join(claude_dir(), "skills", PKG)


def state_dir() -> str:
    return os.path.join(install_dir(), "state")


def _state(name: str) -> str:
    return os.path.join(state_dir(), name)


def key_path() -> str:
    return os.environ.get("BUILDS_SYNC_KEY") or os.path.join(
        os.path.expanduser("~"), ".config", "age", "builds.key")


def hostname() -> str:
    h = os.environ.get("BUILDS_SYNC_HOSTNAME") or socket.gethostname().split(".")[0]
    h = re.sub(r"[^A-Za-z0-9._-]", "-", h).strip(".-") or "unknown-host"
    return h


def install_log_path() -> str:
    return os.environ.get("BUILDS_SYNC_INSTALL_LOG") or "/tmp/builds-sync-install.log"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def utc_stamp(dt: datetime | None = None) -> str:
    return (dt or _now()).strftime("%Y%m%dT%H%M%SZ")


def _read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def config() -> dict:
    return _read_json(_state("config.json"), {})


def clone_dir(required: bool = True) -> str | None:
    """The clone's location: BUILDS_SYNC_CLONE, else what setup recorded."""
    d = os.environ.get("BUILDS_SYNC_CLONE") or config().get("clone")
    if d:
        d = os.path.abspath(os.path.expanduser(d))
    if required:
        if not d:
            raise BuildsSyncError(
                "the builds repo's clone is not set up: run "
                "`builds-sync setup --clone <path> [--remote <url>]`")
        if not os.path.isdir(os.path.join(d, ".git")):
            raise BuildsSyncError("%s is not a git clone: run `builds-sync setup` again" % d)
    return d


# --- the lock -----------------------------------------------------------------

class _Lock:
    """One flock on state/lock for every write to the clone or the state."""

    def __init__(self, timeout: float | None = None):
        if timeout is None:
            timeout = float(os.environ.get("BUILDS_SYNC_LOCK_TIMEOUT", "120"))
        self.timeout = timeout
        self.fd = None

    def __enter__(self):
        os.makedirs(state_dir(), mode=0o700, exist_ok=True)
        self.fd = os.open(_state("lock"), os.O_RDWR | os.O_CREAT, 0o600)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as e:
                if e.errno not in (errno.EAGAIN, errno.EACCES):
                    raise
                if time.monotonic() >= deadline:
                    os.close(self.fd)
                    self.fd = None
                    raise LockBusy("another builds-sync run holds %s; try again when it ends"
                                   % _state("lock"))
                time.sleep(0.1)
        os.ftruncate(self.fd, 0)
        os.write(self.fd, ("%d\n" % os.getpid()).encode())
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None
        return False


def lock(timeout: float | None = None) -> _Lock:
    return _Lock(timeout)


# --- git ----------------------------------------------------------------------

def _git_env() -> dict:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    return env


def git(repo: str, *args: str, check: bool = True, timeout: float = 120) -> str:
    ident = []
    if args and args[0] == "commit":
        # A machine with no git identity (a fresh box, the tests) can still commit.
        for k, v in (("user.name", PKG), ("user.email", PKG + "@localhost")):
            r = subprocess.run(["git", "-C", repo, "config", k], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, universal_newlines=True)
            if not r.stdout.strip():
                ident += ["-c", "%s=%s" % (k, v)]
    try:
        r = subprocess.run(["git", "-C", repo] + ident + list(args), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True,
                           env=_git_env(), timeout=timeout)
    except subprocess.TimeoutExpired:
        raise BuildsSyncError("git %s timed out after %ds" % (args[0], timeout))
    if check and r.returncode != 0:
        raise BuildsSyncError("git %s failed: %s" % (" ".join(args[:2]),
                                                    (r.stderr or r.stdout).strip()))
    return r.stdout


def _branch(repo: str) -> str:
    return git(repo, "symbolic-ref", "--short", "HEAD").strip()


def _has_head(repo: str) -> bool:
    return subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "-q", "HEAD"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def _remote_ref(repo: str) -> str | None:
    ref = "refs/remotes/origin/" + _branch(repo)
    r = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "-q", ref],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return ref if r.returncode == 0 else None


def sync(repo: str, strict: bool = True) -> bool:
    """Fetch and bring local commits on top of origin's. Returns False when
    offline and strict is False; raises otherwise."""
    try:
        git(repo, "fetch", "--quiet", "origin", timeout=60)
    except BuildsSyncError:
        if strict:
            raise
        return False
    ref = _remote_ref(repo)
    if ref is None:
        return True          # an empty remote: nothing to bring in
    if not _has_head(repo):
        git(repo, "reset", "--quiet", "--hard", ref)
        return True
    # --autostash: a push killed after `git add` leaves staged segments, which
    # would otherwise stop every later rebase.
    git(repo, "rebase", "--quiet", "--autostash", ref)
    return True


def _ahead(repo: str) -> int:
    if not _has_head(repo):
        return 0
    ref = _remote_ref(repo)
    rng = (ref + "..HEAD") if ref else "HEAD"
    return int(git(repo, "rev-list", "--count", rng).strip() or 0)


def _allowed(path: str) -> bool:
    return path == "README.md" or path.endswith(".age")


def check_tracked(repo: str) -> None:
    """Refuse when the index, or any commit not yet on origin, holds a file
    other than README.md that does not end in .age."""
    bad = set(p for p in git(repo, "ls-files").splitlines() if p and not _allowed(p))
    if _has_head(repo):
        ref = _remote_ref(repo)
        rng = (ref + "..HEAD") if ref else "HEAD"
        out = git(repo, "log", "--name-only", "--format=", "--no-renames", rng)
        bad |= set(p for p in out.splitlines() if p and not _allowed(p))
    if bad:
        raise Refused(
            "refusing to push: the builds repo holds files that are not encrypted "
            "(only README.md and *.age may be tracked): %s. Remove them from the "
            "index and from any unpushed commit, then run again." % ", ".join(sorted(bad)))


def _withdraw(repo: str, paths: list) -> None:
    """Unstage and delete files this call wrote, after a refusal."""
    git(repo, "reset", "--quiet", "--", *paths, check=False)
    for p in paths:
        try:
            os.unlink(os.path.join(repo, p))
        except OSError:
            pass


def _push_commits(repo: str) -> None:
    """Push what is committed and not yet on origin, rebasing on a rejection."""
    if _ahead(repo) == 0:
        return
    check_tracked(repo)
    branch = _branch(repo)
    last = None
    for _ in range(3):
        try:
            git(repo, "push", "--quiet", "origin", "HEAD:refs/heads/" + branch, timeout=120)
            return
        except BuildsSyncError as e:
            last = e
            sync(repo, strict=True)
            check_tracked(repo)
    raise BuildsSyncError("push failed; the commits stay local for the next push: %s" % last)


# --- age ----------------------------------------------------------------------

def _key() -> str:
    k = key_path()
    if not os.path.isfile(k):
        raise BuildsSyncError(
            "no key at %s: copy builds.key there from its backup, mode 600" % k)
    if os.stat(k).st_mode & 0o077:
        raise BuildsSyncError("%s is readable by other users: chmod 600 %s" % (k, k))
    return k


def _run_age(args: list) -> None:
    if shutil.which(args[0]) is None:
        raise BuildsSyncError("`%s` is not installed (needs age and age-keygen on PATH)" % args[0])
    r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    if r.returncode != 0:
        raise BuildsSyncError("%s failed: %s" % (" ".join(args[:2]), r.stderr.strip()))


def recipient() -> str:
    k = _key()
    if shutil.which("age-keygen") is None:
        raise BuildsSyncError("`age-keygen` is not installed")
    r = subprocess.run(["age-keygen", "-y", k], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, universal_newlines=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise BuildsSyncError("age-keygen -y %s failed: %s" % (k, r.stderr.strip()))
    return r.stdout.strip().splitlines()[-1]


def encrypt(src: str, dst: str) -> None:
    tmp = dst + ".part"
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        _run_age(["age", "-e", "-r", recipient(), "-o", tmp, src])
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def decrypt(src: str, dst: str) -> None:
    _run_age(["age", "-d", "-i", _key(), "-o", dst, src])


def decrypt_bytes(src: str) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        os.chmod(d, 0o700)
        out = os.path.join(d, "plain")
        decrypt(src, out)
        with open(out, "rb") as f:
            return f.read()


# --- builds -------------------------------------------------------------------

def _check_build_time(bt: str) -> None:
    if not BUILD_TIME_RE.match(bt or ""):
        raise BuildsSyncError("build time %r is not UTC YYYYMMDDTHHMMSSZ" % bt)


def _tar_members(tf: tarfile.TarFile) -> list:
    """Every member, checked: relative, no '..', regular files and directories
    only, and everything under a top-level directory."""
    members = tf.getmembers()
    for m in members:
        name = m.name
        parts = [p for p in name.split("/") if p not in ("", ".")]
        if name.startswith("/") or ".." in parts or not parts:
            raise BuildsSyncError("build tarball has an unsafe path: %r" % name)
        if not (m.isfile() or m.isdir()):
            raise BuildsSyncError("build tarball has a link or special file: %r" % name)
        if len(parts) == 1 and not m.isdir():
            raise BuildsSyncError("build tarball has a file at the top level: %r" % name)
        if not NAME_RE.match(parts[0]):
            raise BuildsSyncError("build tarball has a bad top-level name: %r" % parts[0])
    return members


def _extract(tar_path: str, dest: str) -> list:
    with tarfile.open(tar_path) as tf:
        members = _tar_members(tf)
        if hasattr(tarfile, "data_filter"):
            tf.extractall(dest, members=members, filter="data")
        else:
            tf.extractall(dest, members=members)
    return sorted(set(m.name.split("/")[0] for m in members if m.name.strip("./")))


def list_builds(repo: str, ref: str = "HEAD") -> list:
    if ref == "HEAD" and not _has_head(repo):
        return []
    out = git(repo, "ls-tree", "--name-only", ref, "builds/", check=False)
    found = []
    for line in out.splitlines():
        name = line.rsplit("/", 1)[-1]
        if name.endswith(".tar.age") and BUILD_TIME_RE.match(name[:-len(".tar.age")]):
            found.append(name[:-len(".tar.age")])
    return sorted(found)


def publish_build(tar_path: str, build_time: str) -> str:
    """Encrypt a build tarball to builds/<build-time>.tar.age, commit and push.
    Returns the path in the repo. Publishing the same tarball again only pushes."""
    _check_build_time(build_time)
    if not os.path.isfile(tar_path) or not tarfile.is_tarfile(tar_path):
        raise BuildsSyncError("%s is not a tar file" % tar_path)
    with tarfile.open(tar_path) as tf:
        _tar_members(tf)
    rel = "builds/%s.tar.age" % build_time
    with lock():
        repo = clone_dir()
        check_tracked(repo)
        sync(repo, strict=True)
        dst = os.path.join(repo, rel)
        if os.path.exists(dst):
            with open(tar_path, "rb") as f:
                if decrypt_bytes(dst) != f.read():
                    raise BuildsSyncError("%s is already in the repo with different contents" % rel)
        else:
            encrypt(tar_path, dst)
            git(repo, "add", "--", rel)
            try:
                check_tracked(repo)
            except Refused:
                _withdraw(repo, [rel])
                raise
            git(repo, "commit", "--quiet", "-m", "build %s" % build_time)
        _push_commits(repo)
    return rel


def installed_builds() -> dict:
    """runtime -> the build_time its manifest.json names, or None, for each
    runtime whose executable is on this machine."""
    out = {}
    for rt, rel in RUNTIME_MANIFESTS.items():
        if shutil.which(rt) is None:
            continue
        m = _read_json(os.path.join(claude_dir(), rel), {})
        out[rt] = m.get("build_time") if isinstance(m, dict) else None
    return out


def _log(fh, msg: str) -> None:
    line = "%s %s" % (datetime.now().strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    if fh:
        fh.write(line + "\n")
        fh.flush()


def install(build_time: str | None = None) -> int:
    """Decrypt a build and hand each runtime its directory. Manual only.
    Logs to install_log_path() as well as stdout. Returns the exit status."""
    logp = install_log_path()
    try:
        fh = open(logp, "w", encoding="utf-8")
    except OSError:
        fh = None
    try:
        _log(fh, "builds-sync install %s, log %s" % (build_time or "(newest)", logp))
        if build_time:
            _check_build_time(build_time)
        with lock():
            repo = clone_dir()
            if not sync(repo, strict=False):
                _log(fh, "warn: could not fetch; installing from the clone as it is")
            builds = list_builds(repo)
            if not builds:
                raise BuildsSyncError("the builds repo holds no builds yet")
            bt = build_time or builds[-1]
            if bt not in builds:
                raise BuildsSyncError("no build %s in the repo; builds: %s" % (bt, ", ".join(builds)))
            src = os.path.join(repo, "builds", bt + ".tar.age")
        tmp = tempfile.mkdtemp(prefix="builds-sync-")
        os.chmod(tmp, 0o700)
        try:
            tar = os.path.join(tmp, "build.tar")
            _log(fh, "decrypting builds/%s.tar.age" % bt)
            decrypt(src, tar)
            tops = _extract(tar, tmp)
            os.unlink(tar)
            ran = failed = 0
            for rt in tops:
                exe = shutil.which(rt)
                if exe is None:
                    _log(fh, "skip %s: not installed on this machine" % rt)
                    continue
                ran += 1
                _log(fh, "run %s install-build %s --build-time %s" % (rt, os.path.join(tmp, rt), bt))
                p = subprocess.Popen([exe, "install-build", os.path.join(tmp, rt), "--build-time", bt],
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     universal_newlines=True)
                for line in p.stdout:
                    _log(fh, "  %s: %s" % (rt, line.rstrip("\n")))
                if p.wait() != 0:
                    failed += 1
                    _log(fh, "FAIL %s install-build exited %d" % (rt, p.returncode))
                else:
                    _log(fh, "ok   %s has build %s" % (rt, bt))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if ran == 0:
            _log(fh, "install finished: nothing installed, no runtime for %s is on this machine"
                 % ", ".join(tops))
            return EXIT_ERROR
        _log(fh, "install finished: %s (%d runtime(s), %d failed)"
             % ("ok" if failed == 0 else "FAILED", ran, failed))
        return 0 if failed == 0 else EXIT_ERROR
    except BuildsSyncError as e:
        _log(fh, "install finished: FAILED: %s" % e)
        return e.code
    finally:
        if fh:
            fh.close()


# --- live files ---------------------------------------------------------------

def _positions() -> dict:
    return _read_json(_state("positions.json"), {})


def _push_time(repo: str, host: str) -> str:
    """A UTC push time not yet used by this machine's segments."""
    while True:
        pt = utc_stamp()
        if not any(os.path.exists(os.path.join(repo, "live", host, pkg, pt + ".jsonl.age"))
                   for pkg in LIVE_FILES):
            return pt
        time.sleep(0.2)


def pending() -> dict:
    """package -> bytes of complete lines not yet pushed; plus '_commits'."""
    out = {}
    pos = _positions()
    for pkg, rel in LIVE_FILES.items():
        start, end, _ = _new_region(pkg, rel, pos)
        if end > start:
            out[pkg] = end - start
    d = clone_dir(required=False)
    if d and os.path.isdir(os.path.join(d, ".git")):
        n = _ahead(d)
        if n:
            out["_commits"] = n
    return out


def _new_region(pkg: str, rel: str, pos: dict):
    path = os.path.join(claude_dir(), rel)
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return 0, 0, b""
    p = pos.get(pkg) or {}
    start = int(p.get("offset", 0))
    if (p.get("path") != rel or start > len(data)
            or hashlib.sha256(data[:start]).hexdigest() != p.get("sha256")):
        start = 0           # new, moved or rewritten: send it all again
    end = data.rfind(b"\n") + 1
    return start, max(end, start), data


def push(quiet: bool = False) -> dict:
    """Push this machine's new live-file records as segments, and any commit
    left unpushed. Returns {"segments": [...], "pushed": bool, "offline": bool}."""
    result = {"segments": [], "pushed": False, "offline": False}
    with lock():
        repo = clone_dir()
        check_tracked(repo)
        online = sync(repo, strict=False)
        result["offline"] = not online
        host = hostname()
        pos = _positions()
        pt = None
        moved = {}
        for pkg, rel in LIVE_FILES.items():
            start, end, data = _new_region(pkg, rel, pos)
            if end <= start:
                continue
            moved[pkg] = {"path": rel, "offset": end,
                          "sha256": hashlib.sha256(data[:end]).hexdigest()}
            chunk = data[start:end]
            if not chunk.strip():
                continue
            pt = pt or _push_time(repo, host)
            seg = "live/%s/%s/%s.jsonl.age" % (host, pkg, pt)
            with tempfile.TemporaryDirectory() as d:
                os.chmod(d, 0o700)
                plain = os.path.join(d, "segment.jsonl")
                with open(plain, "wb") as f:
                    f.write(chunk)
                encrypt(plain, os.path.join(repo, seg))
            result["segments"].append(seg)
        if result["segments"]:
            git(repo, "add", "--", *result["segments"])
            try:
                check_tracked(repo)
            except Refused:
                _withdraw(repo, result["segments"])
                raise
            git(repo, "commit", "--quiet", "-m", "live %s %s" % (host, pt))
        if moved:
            pos.update(moved)
            _write_json(_state("positions.json"), pos)
        check_tracked(repo)
        if _ahead(repo):
            if not online:
                raise BuildsSyncError("offline: %d commit(s) stay local for the next push"
                                      % _ahead(repo))
            _push_commits(repo)
            result["pushed"] = True
    if not quiet:
        for s in result["segments"]:
            print("pushed %s" % s if result["pushed"] else "committed %s" % s)
        if not result["segments"] and not result["pushed"]:
            print("nothing new to push")
    return result


def read_live(package: str) -> list:
    """Every machine's segments of one package's live file, this machine's
    included, pulled first and joined in push-time order. A record repeated
    exactly (same JSON, sorted keys) is kept once. Choosing the newest line
    per id is the caller's job."""
    if not NAME_RE.match(package or ""):
        raise BuildsSyncError("bad package name %r" % package)
    with lock():
        repo = clone_dir()
        sync(repo, strict=True)
        root = os.path.join(repo, "live")
        segs = []
        if os.path.isdir(root):
            for host in os.listdir(root):
                d = os.path.join(root, host, package)
                if not os.path.isdir(d):
                    continue
                for name in os.listdir(d):
                    m = SEGMENT_RE.match(name)
                    if m:
                        segs.append((m.group(1), host, os.path.join(d, name)))
        segs.sort()
        seen = set()
        out = []
        for pt, host, path in segs:
            for n, line in enumerate(decrypt_bytes(path).decode("utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    sys.stderr.write("builds-sync: skipped a line that is not JSON: "
                                     "live/%s/%s/%s.jsonl.age line %d\n" % (host, package, pt, n))
                    continue
                k = json.dumps(rec, sort_keys=True)
                if k in seen:
                    continue
                seen.add(k)
                out.append(rec)
    return out


# --- the update check ---------------------------------------------------------

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def checked_today() -> bool:
    try:
        with open(_state("last-check"), encoding="utf-8") as f:
            return f.read().strip() == _today()
    except OSError:
        return False


def check(force: bool = False) -> dict | None:
    """At most once a day (unless forced): fetch and record whether the repo
    holds a build newer than the one installed. Silent; the notice is shown
    by the next session start."""
    if not force and checked_today():
        return None
    os.makedirs(state_dir(), mode=0o700, exist_ok=True)
    with open(_state("last-check"), "w", encoding="utf-8") as f:     # before the fetch
        f.write(_today() + "\n")
    with lock():
        repo = clone_dir()
        git(repo, "fetch", "--quiet", "origin", timeout=60)
        ref = _remote_ref(repo) or "HEAD"
        builds = list_builds(repo, ref)
        newest = builds[-1] if builds else None
        found = {"newest": newest, "checked_at": utc_stamp()}
        _write_json(_state("check.json"), found)
    return found


def notice() -> str | None:
    """The line the last check left, if a runtime here is behind it."""
    found = _read_json(_state("check.json"), {})
    newest = found.get("newest")
    if not newest:
        return None
    inst = installed_builds()
    behind = [rt for rt, bt in inst.items() if bt is None or bt < newest]
    if not behind:
        return None
    have = ", ".join("%s %s" % (rt, inst[rt] or "none") for rt in sorted(behind))
    return ("builds-sync: build %s is in the builds repo (installed: %s). "
            "Install it with: builds-sync install" % (newest, have))


def _spawn_detached(args: list, log: str | None = None) -> None:
    out = open(log, "a") if log else subprocess.DEVNULL
    try:
        subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                         start_new_session=True, close_fds=True)
    finally:
        if log:
            out.close()


def hook_session_start(self_cmd: list) -> None:
    msg = notice()
    if msg:
        print(json.dumps({"systemMessage": msg}))
    if clone_dir(required=False) and not checked_today():
        _spawn_detached(self_cmd + ["check"])


def hook_session_end(self_cmd: list) -> None:
    # SessionEnd hooks are cut short when Claude Code exits, so the push runs
    # detached; the lock keeps two at once from colliding.
    if clone_dir(required=False):
        os.makedirs(state_dir(), mode=0o700, exist_ok=True)
        _spawn_detached(self_cmd + ["push", "--quiet"], log=_state("last-push.log"))


# --- setup and status ---------------------------------------------------------

def setup(clone: str | None, remote: str | None, interactive: bool) -> int:
    cfg = config()
    if not clone and cfg.get("clone"):
        print("builds repo clone: %s" % cfg["clone"])
        _warn_prereqs()
        return 0
    if not clone and interactive:
        clone = input("Where is the builds repo's clone on this machine (or where should it be "
                      "cloned to)? [~/builds-repo] ").strip() or "~/builds-repo"
    if not clone:
        print("builds-sync is not set up: run `builds-sync setup --clone <path> [--remote <url>]`")
        return 0
    clone = os.path.abspath(os.path.expanduser(clone))
    if not os.path.isdir(os.path.join(clone, ".git")):
        if not remote and interactive:
            remote = input("%s is not a clone. The builds repo's git URL to clone: " % clone).strip()
        if not remote:
            raise BuildsSyncError("%s is not a git clone and no --remote was given" % clone)
        r = subprocess.run(["git", "clone", "--quiet", remote, clone], env=_git_env(),
                           stderr=subprocess.PIPE, universal_newlines=True)
        if r.returncode != 0:
            raise BuildsSyncError("git clone failed: %s" % r.stderr.strip())
    cfg.update({"schema_version": 1, "clone": clone})
    _write_json(_state("config.json"), cfg)
    print("builds repo clone: %s (recorded)" % clone)
    _warn_prereqs()
    return 0


def _warn_prereqs() -> None:
    for exe in ("age", "age-keygen"):
        if shutil.which(exe) is None:
            print("warn: `%s` is not on PATH; builds-sync needs it" % exe)
    if not os.path.isfile(key_path()):
        print("warn: no key at %s yet: copy it from its backup, mode 600" % key_path())


def status() -> None:
    d = clone_dir(required=False)
    print("builds-sync (library API %d)" % BUILDS_SYNC_API)
    print("  clone:        %s" % (d or "(not set up)"))
    k = key_path()
    print("  key:          %s%s" % (k, "" if os.path.isfile(k) else " (missing)"))
    print("  hostname:     %s" % hostname())
    ok_clone = bool(d) and os.path.isdir(os.path.join(d, ".git"))
    if ok_clone:
        local = list_builds(d)
        ref = _remote_ref(d)
        remote = list_builds(d, ref) if ref else []
        print("  newest build: %s in the clone, %s on origin (as last fetched)"
              % (local[-1] if local else "none", remote[-1] if remote else "none"))
        print("  unpushed:     %d commit(s)" % _ahead(d))
    inst = installed_builds()
    if inst:
        for rt in sorted(inst):
            print("  %-13s %s" % (rt + ":", inst[rt] or "no build installed"))
    else:
        print("  runtimes:     none installed on this machine")
    pos = _positions()
    for pkg, rel in LIVE_FILES.items():
        start, end, data = _new_region(pkg, rel, pos)
        if not data and pkg not in pos:
            continue
        print("  live %-17s %d bytes, %d not yet pushed" % (pkg + ":", len(data), end - start))
    print("  last check:   %s" % (_read_json(_state("check.json"), {}).get("checked_at") or "never"))
    msg = notice()
    if msg:
        print("  -> " + msg)


# --- command line -------------------------------------------------------------

USAGE = """usage: builds-sync <command> [options]

  setup [--clone <path>] [--remote <url>]   record (or clone) the builds repo
  install [<build-time>]           install the newest build, or that one (manual only);
                                   logs to /tmp/builds-sync-install.log
  check [--force]                  look for a newer build, at most once a day
  push                             push this machine's new live-file records
  status                           clone, key, builds, what each runtime runs
  publish <tar> --build-time <bt>  encrypt and push a build (the pipeline's)
  pending                          what a push would send, as JSON
  hook session-start|session-end   what the hooks run

Environment: BUILDS_SYNC_CLONE, BUILDS_SYNC_KEY, BUILDS_SYNC_HOSTNAME,
BUILDS_SYNC_INSTALL_LOG, BUILDS_SYNC_LOCK_TIMEOUT, CLAUDE_DIR."""


def main(argv: list, self_cmd: list) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0 if argv else EXIT_USAGE
    cmd, rest = argv[0], argv[1:]

    def opt(name):
        if name in rest:
            i = rest.index(name)
            if i + 1 >= len(rest):
                raise BuildsSyncError("%s needs a value" % name)
            v = rest[i + 1]
            del rest[i:i + 2]
            return v
        return None

    def flag(name):
        if name in rest:
            rest.remove(name)
            return True
        return False

    try:
        if cmd == "setup":
            c, r = opt("--clone"), opt("--remote")
            yes = flag("--yes")
            return setup(c, r, interactive=not yes and sys.stdin.isatty())
        if cmd == "install":
            if len(rest) > 1:
                raise BuildsSyncError("install takes at most one build time")
            return install(rest[0] if rest else None)
        if cmd == "check":
            found = check(force=flag("--force"))
            if found is not None and sys.stdout.isatty():
                print("newest build in the repo: %s" % (found["newest"] or "none"))
            return 0
        if cmd == "push":
            push(quiet=flag("--quiet"))
            return 0
        if cmd == "pending":
            print(json.dumps(pending(), sort_keys=True))
            return 0
        if cmd == "status":
            status()
            return 0
        if cmd == "publish":
            bt = opt("--build-time")
            if len(rest) != 1 or not bt:
                raise BuildsSyncError("usage: builds-sync publish <tar> --build-time <bt>")
            print(publish_build(rest[0], bt))
            return 0
        if cmd == "hook":
            # A hook never fails a session: anything wrong shows in `status`.
            which = rest[0] if rest else ""
            try:
                if which == "session-start":
                    hook_session_start(self_cmd)
                elif which == "session-end":
                    hook_session_end(self_cmd)
            except Exception:
                pass
            return 0
        if cmd == "api":
            print(BUILDS_SYNC_API)
            return 0
        sys.stderr.write("builds-sync: unknown command %r\n%s\n" % (cmd, USAGE))
        return EXIT_USAGE
    except BuildsSyncError as e:
        sys.stderr.write("builds-sync: %s\n" % e)
        return e.code
    except KeyboardInterrupt:
        return 130
