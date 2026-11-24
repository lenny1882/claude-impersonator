"""Command line for voice-runtime. bin/voice-runtime picks the interpreter
and sets the umask, then calls this. The subcommands and the drafts.jsonl
record are fixed by the Stage 2 interface contract (§3): builds-sync calls
`install-build`, and the pipeline reads drafts.jsonl, so neither may change
here without them."""

import argparse
import datetime
import fcntl
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import uuid

from . import (ACCEPTED, AUDIENCES, BUILD_FILES, DEFAULT_COMPARED, DRAFTS_SCHEMA,
               NEEDS_EMBEDDING_LIB_API, PKG, PURPOSES, state_dir)

BUILD_TIME_RE = re.compile(r"^\d{8}T\d{6}Z$")
DESTINATION_RE = re.compile(r"^(slack:.+|bitbucket:.+#\d+|jira:.+|other)$")
FIX_SCHEMA = ("update voice-runtime (./update.sh in its release directory) "
              "or install a build it reads (builds-sync install)")


class Refusal(Exception):
    """The voice model can't be used. One line; the command exits 3."""


class Failure(Exception):
    """Anything else that stops a command. Exits 1."""


# --- files -------------------------------------------------------------------

def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    """Written beside the target and renamed over it, so a reader never sees
    half a file; mode 600 whatever the umask."""
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix="." + os.path.basename(path) + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def ensure_dir(path):
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def owner_only(top):
    """Dirs 700 and files 600 under top: the build holds the owner's words."""
    for root, dirs, files in os.walk(top):
        os.chmod(root, 0o700)
        for f in files:
            os.chmod(os.path.join(root, f), 0o600)


def builds_dir():
    return os.path.join(state_dir(), "builds")


def manifest_path():
    return os.path.join(state_dir(), "manifest.json")


def drafts_path():
    return os.path.join(state_dir(), "drafts.jsonl")


def schema_of(name, obj):
    v = obj.get("schema_version") if isinstance(obj, dict) else None
    if v not in ACCEPTED[name]:
        raise Refusal(
            "voice model unavailable: %s has schema version %s; this voice-runtime "
            "accepts %s. Fix: %s" % (name, json.dumps(v), accepted_text(name), FIX_SCHEMA))
    return v


def accepted_text(name):
    return ", ".join(str(v) for v in ACCEPTED[name])


def read_checked(path, name):
    try:
        obj = read_json(path)
    except FileNotFoundError:
        raise Failure("%s is missing" % path)
    except ValueError as e:
        raise Failure("%s is not valid JSON: %s" % (path, e))
    schema_of(name, obj)
    return obj


# --- the installed build -----------------------------------------------------

class Build(object):
    """The build manifest.json names, with each file read and checked only
    when a command asks for it (a voice-only change shouldn't make an
    unrelated command refuse)."""

    def __init__(self):
        mp = manifest_path()
        if not os.path.isfile(mp):
            raise Refusal("voice model unavailable: no voice build is installed on "
                          "this machine yet. Fix: builds-sync install")
        try:
            self.manifest = read_json(mp)
        except ValueError as e:
            raise Failure("%s is not valid JSON: %s" % (mp, e))
        schema_of("manifest.json", self.manifest)
        self.build_time = self.manifest.get("build_time")
        if not isinstance(self.build_time, str) or not BUILD_TIME_RE.match(self.build_time):
            raise Failure("%s names no valid build_time" % mp)
        self.dir = os.path.join(builds_dir(), self.build_time)
        if not os.path.isdir(self.dir):
            raise Refusal("voice model unavailable: the installed build %s is missing "
                          "from %s. Fix: builds-sync install" % (self.build_time, builds_dir()))
        self._cache = {}

    def file(self, name):
        if name in self._cache:
            return self._cache[name]
        if name in BUILD_FILES:
            listed = (self.manifest.get("files") or {}).get(name)
            if listed not in ACCEPTED[name]:
                raise Refusal(
                    "voice model unavailable: manifest.json lists %s at schema version %s; "
                    "this voice-runtime accepts %s. Fix: %s"
                    % (name, json.dumps(listed), accepted_text(name), FIX_SCHEMA))
        obj = read_checked(os.path.join(self.dir, name), name)
        self._cache[name] = obj
        return obj


# --- embedding-lib -----------------------------------------------------------

def load_embedding_lib():
    """From embedding-lib's install directory (PYTHONPATH, set by
    bin/voice-runtime), never PATH, with its API checked (PLAN §5 Coupling)."""
    try:
        import embedding_lib as el
    except ImportError:
        raise Refusal("voice model unavailable: embedding-lib is not installed or not "
                      "set up. Fix: install embedding-lib, then run: embedding-lib setup")
    api = getattr(el, "EMBEDDING_LIB_API", None)
    if api != NEEDS_EMBEDDING_LIB_API:
        raise Refusal("voice model unavailable: embedding-lib's API is %s; this "
                      "voice-runtime needs %s. Fix: update embedding-lib or voice-runtime"
                      % (api, NEEDS_EMBEDDING_LIB_API))
    return el


def identity_diffs(el, recorded, here):
    keys = getattr(el, "COMPARED", None) or DEFAULT_COMPARED
    recorded = recorded if isinstance(recorded, dict) else {}
    return ["%s: index %s, here %s" % (k, json.dumps(recorded.get(k)), json.dumps(here.get(k)))
            for k in keys if recorded.get(k) != here.get(k)]


def pair_text(ex):
    answered = ex.get("answered") or ""
    text = ex.get("text") or ""
    return answered + "\n\n" + text if answered else text


def fit_pairs(el, exemplars):
    """The text embedded for each exemplar: answered + blank line + text,
    with words dropped from the start of `answered` until the pair fits the
    model's limit (contract §1). A text too long on its own goes in alone and
    the model cuts its end."""
    limit = getattr(el, "MAX_TOKENS", 512)
    texts = [pair_text(e) for e in exemplars]
    if not texts:
        return texts
    counts = el.count_tokens(texts)
    for i, (e, n) in enumerate(zip(exemplars, counts)):
        if n <= limit or not e.get("answered"):
            continue
        words = e["answered"].split()
        text = e.get("text") or ""

        def joined(drop):
            rest = " ".join(words[drop:])
            return rest + "\n\n" + text if rest else text

        lo, hi = 1, len(words)
        while lo < hi:  # the fewest words dropped that fit
            mid = (lo + hi) // 2
            if el.count_tokens([joined(mid)])[0] <= limit:
                hi = mid
            else:
                lo = mid + 1
        texts[i] = joined(lo)
    return texts


# --- install-build -----------------------------------------------------------

def lock_state():
    ensure_dir(state_dir())
    fd = os.open(os.path.join(state_dir(), ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def previous_index(el, here):
    """Rows of the current build's index, keyed by exemplar hash, when it was
    embedded by this same setup; None when there is none or the identity
    differs, so everything is embedded again (PLAN §5 Builds repo)."""
    import numpy as np
    mp = manifest_path()
    if not os.path.isfile(mp):
        return None, "no previous build"
    try:
        m = read_json(mp)
        idx = os.path.join(builds_dir(), m["build_time"], "index")
        recorded = read_json(os.path.join(idx, "identity.json"))
        hashes = read_json(os.path.join(idx, "hashes.json"))
        vectors = np.load(os.path.join(idx, "vectors.npy"), allow_pickle=False)
    except (OSError, ValueError, KeyError, TypeError):
        return None, "previous index unreadable"
    if identity_diffs(el, recorded, here):
        return None, "embedding-lib identity changed"
    if len(hashes) != len(vectors):
        return None, "previous index inconsistent"
    return {h: vectors[i] for i, h in enumerate(hashes)}, None


def cmd_install_build(a):
    if not BUILD_TIME_RE.match(a.build_time):
        raise Failure("--build-time must be YYYYMMDDTHHMMSSZ, got %r" % a.build_time)
    src = os.path.abspath(a.dir)
    if not os.path.isdir(src):
        raise Failure("%s is not a directory" % src)

    build = read_checked(os.path.join(src, "build.json"), "build.json")
    if build.get("build_time") != a.build_time:
        raise Failure("build.json says build_time %s, but --build-time is %s"
                      % (build.get("build_time"), a.build_time))
    listed = build.get("files") or {}
    for name in BUILD_FILES:
        if listed.get(name) not in ACCEPTED[name]:
            raise Refusal("voice model unavailable: build.json lists %s at schema version %s; "
                          "this voice-runtime accepts %s. Fix: %s"
                          % (name, json.dumps(listed.get(name)), accepted_text(name), FIX_SCHEMA))
    docs = {name: read_checked(os.path.join(src, name), name) for name in BUILD_FILES}
    exemplars = docs["exemplars.json"].get("exemplars")
    if not isinstance(exemplars, list):
        raise Failure("exemplars.json has no exemplars list")
    seen = set()
    for n, e in enumerate(exemplars):
        if not isinstance(e, dict) or not all(isinstance(e.get(k), str) and e.get(k)
                                              for k in ("id", "hash", "text", "audience")):
            raise Failure("exemplars.json entry %d lacks id, hash, text or audience" % n)
        if e["id"] in seen:
            raise Failure("exemplars.json repeats id %s" % e["id"])
        seen.add(e["id"])

    el = load_embedding_lib()
    import numpy as np
    lock = lock_state()
    try:
        ensure_dir(builds_dir())
        here = el.identity()
        reuse, why = previous_index(el, here)
        reuse = reuse or {}

        stage = tempfile.mkdtemp(dir=builds_dir(), prefix=".staging-%s-" % a.build_time)
        try:
            for name in BUILD_FILES + ("build.json",):
                shutil.copyfile(os.path.join(src, name), os.path.join(stage, name))
            todo = [i for i, e in enumerate(exemplars) if e["hash"] not in reuse]
            new = {}
            if todo:
                texts = fit_pairs(el, [exemplars[i] for i in todo])
                vecs = np.asarray(el.embed(texts), dtype=np.float32)
                for i, v in zip(todo, vecs):
                    new[i] = v
            dim = int(here.get("dimension") or 0)
            rows = [new[i] if i in new else reuse[e["hash"]] for i, e in enumerate(exemplars)]
            if rows:
                vectors = np.vstack(rows).astype(np.float32)
            else:
                vectors = np.zeros((0, dim), dtype=np.float32)
            idx = ensure_dir(os.path.join(stage, "index"))
            with open(os.path.join(idx, "vectors.npy"), "wb") as f:
                np.save(f, vectors, allow_pickle=False)
            write_json(os.path.join(idx, "ids.json"), [e["id"] for e in exemplars])
            write_json(os.path.join(idx, "hashes.json"), [e["hash"] for e in exemplars])
            write_json(os.path.join(idx, "identity.json"), here)
            owner_only(stage)

            # The new build goes in under its own name. Reinstalling the build
            # that is current (to re-embed after an embedding-lib change) moves
            # the old copy aside first; the manifest still names it, and a
            # reader in that instant gets "missing", never a mixed build.
            target = os.path.join(builds_dir(), a.build_time)
            aside = None
            if os.path.exists(target):
                aside = tempfile.mkdtemp(dir=builds_dir(), prefix=".old-%s-" % a.build_time)
                os.rename(target, os.path.join(aside, "build"))
            os.rename(stage, target)
            stage = None
        finally:
            if stage and os.path.isdir(stage):
                shutil.rmtree(stage)

        # Last: from here on every command reads the new build.
        write_json(manifest_path(), {
            "schema_version": 1,
            "build_time": a.build_time,
            "files": {name: docs[name]["schema_version"] for name in BUILD_FILES},
        })

        # Then everything else in builds/ goes: the previous build, a copy
        # moved aside, and staging left by an install that died.
        for name in os.listdir(builds_dir()):
            if name != a.build_time:
                p = os.path.join(builds_dir(), name)
                shutil.rmtree(p) if os.path.isdir(p) else os.unlink(p)
        owner_only(state_dir())
    finally:
        os.close(lock)

    reused = len(exemplars) - len(new)
    note = " (%s)" % why if why and why != "no previous build" else ""
    print("installed %s: %d exemplars, %d embedded, %d reused%s"
          % (a.build_time, len(exemplars), len(new), reused, note))


# --- guide -------------------------------------------------------------------

def build_purposes():
    """The purposes the installed build was labelled with (stats.json's
    drafting.purposes), else this release's own list. A build that can't be
    read gives this release's list here; the command's own read refuses it."""
    try:
        dr = Build().file("stats.json").get("drafting") or {}
    except (Refusal, Failure):
        return PURPOSES
    ps = dr.get("purposes")
    if isinstance(ps, list) and ps and all(isinstance(p, str) and p for p in ps):
        return tuple(ps)
    return PURPOSES


def split_purposes(s):
    known = build_purposes()
    ps = [p.strip() for p in (s or "").split(",") if p.strip()]
    if not ps:
        raise Failure("--purposes needs at least one of: %s" % ", ".join(known))
    bad = [p for p in ps if p not in known]
    if bad:
        raise Failure("unknown purpose %s; purposes are: %s" % (", ".join(bad), ", ".join(known)))
    return ps


def check_audience(a):
    if a not in AUDIENCES:
        raise Failure("unknown audience %s; audiences are: %s" % (a, ", ".join(AUDIENCES)))
    return a


def bullets(out, title, items):
    items = [x for x in (items or []) if isinstance(x, str) and x.strip()]
    if not items:
        return
    out.append("## " + title)
    out.extend("- " + x for x in items)
    out.append("")


# The pipeline's rule for the words a guide rule quotes (voicestats.quoted):
# up to 3 words of letters only, so their shares can be shown beside the rules.
QUOTE = re.compile(r"(?:(?<=^)|(?<=[\s(]))['\"\u2018\u201c]([^'\"\u2019\u201d]{2,40}?)['\"\u2019\u201d](?=[\s,.;:)!?]|$)")


def quoted(rule):
    out = []
    for m in QUOTE.finditer(rule):
        q = m.group(1).strip(" .,-!?")
        if q and re.fullmatch(r"[A-Za-z' ,]+", q) and len(q.split()) <= 3:
            out.append(q.lower())
    return out


def cmd_guide(a):
    audience = check_audience(a.audience)
    purposes = split_purposes(a.purposes)
    b = Build()
    g = b.file("guide.json")
    st = b.file("stats.json")
    cell = (g.get("audiences") or {}).get(audience) or {}

    out = ["# Voice guide: %s; %s (build %s)" % (audience, ", ".join(purposes), b.build_time), ""]
    dr = st.get("drafting") or {}
    ds = dr.get("draft_system")
    if isinstance(ds, str) and ds.strip():
        out.append("## How to draft (the prompt this build was validated with)")
        out.append(ds.strip())
        out.append("")
    bullets(out, "self-01's own rules (these win over every rule below)", g.get("own_rules"))
    bullets(out, "How to write it", (dr.get("notes") or {}).get(audience))
    if audience == "jira":
        bullets(out, "Jira comments", g.get("jira"))
    bullets(out, "General", g.get("general"))
    bullets(out, "Audience: %s" % audience, cell.get("rules"))
    for p in purposes:
        bullets(out, "Purpose: %s" % p, (cell.get("purposes") or {}).get(p))
    shown = [r for r in (g.get("general") or []) + (cell.get("rules") or []) if isinstance(r, str)]
    for p in purposes:
        shown += [r for r in (cell.get("purposes") or {}).get(p) or [] if isinstance(r, str)]
    if len(purposes) > 1:
        bullets(out, "Combining purposes", g.get("combinations"))
        shown += [r for r in g.get("combinations") or [] if isinstance(r, str)]

    s = (st.get("audiences") or {}).get(audience)
    if s:
        out.append("## How self-01 writes to %s (measured over %s messages)"
                   % (audience, s.get("messages", "?")))
        out.append("- length: median %s words, 90%% under %s"
                   % (s.get("median_words", "?"), s.get("p90_words", "?")))
        for key, label in (("lowercase_start", "start in lower case"),
                           ("full_stop_end", "end with a full stop")):
            if isinstance(s.get(key), (int, float)):
                out.append("- %d%% %s" % (round(100 * s[key]), label))
        for key, label in (("exclamation_per_message", "exclamation marks"),
                           ("emoji_per_message", "emoji")):
            if isinstance(s.get(key), (int, float)):
                out.append("- %s per message: %.2f" % (label, s[key]))
        style = s.get("style") or {}
        if style:
            out.append("- share of messages holding each: %s. Use each about as often: put one in "
                       "only where the exemplars for this message have it, and keep it where they do"
                       % ", ".join("%s %d%%" % (k, round(100 * v)) for k, v in style.items()
                                   if isinstance(v, (int, float))))
        for key, label in (("openings", "openings"), ("signoffs", "sign-offs")):
            pairs = [p for p in s.get(key) or [] if isinstance(p, list) and len(p) == 2]
            if pairs:
                out.append("- %s: %s" % (label, ", ".join('"%s" (%s)' % (w, n) for w, n in pairs)))
        out.append("")
    if audience in (dr.get("quoted_rates_for") or []):
        rates = (st.get("quoted") or {}).get(audience) or {}
        below = dr.get("rare_below", 0)
        rare = sorted({q for r in shown for q in quoted(r)
                       if isinstance(rates.get(q), (int, float)) and rates[q] < below},
                      key=lambda q: (rates[q], q))
        if rare:
            out.append("## Words the rules quote, by share of messages holding them")
            out.append("- " + ", ".join('"%s" %.1f%%' % (q, 100 * rates[q]) for q in rare) +
                       ". Most messages use none of them: use one only where the exemplars for "
                       "this message do (a word the content needs is always fine).")
            out.append("")
    sp = st.get("spelling") or {}
    if sp:
        out.append("## Spelling: British %s, American %s" % (sp.get("british", 0), sp.get("american", 0)))
        out.append("")
    never = [x for x in st.get("never_say") or [] if isinstance(x, dict) and x.get("phrase")]
    if never:
        out.append("## Never say (self-01's count; how common it is elsewhere)")
        for x in never:
            out.append('- "%s": self-01 %s, %s %s' % (x["phrase"], x.get("self", 0),
                                                    x.get("reference", "reference"),
                                                    x.get("reference_count", "?")))
        out.append("")
    sys.stdout.write("\n".join(out).rstrip("\n") + "\n")


# --- search ------------------------------------------------------------------

def cmd_search(a):
    audience = check_audience(a.audience)
    purposes = split_purposes(a.purposes)
    if not a.situation.strip():
        raise Failure("--situation is empty")
    b = Build()
    info = b.file("build.json")
    k = a.k if a.k is not None else info.get("exemplar_count")
    if not isinstance(k, int) or isinstance(k, bool) or k < 0:
        raise Failure("no exemplar count: build.json has exemplar_count %s; pass --k N"
                      % json.dumps(info.get("exemplar_count")))
    exemplars = b.file("exemplars.json").get("exemplars") or []

    el = load_embedding_lib()
    import numpy as np
    idx = os.path.join(b.dir, "index")
    try:
        recorded = read_json(os.path.join(idx, "identity.json"))
        ids = read_json(os.path.join(idx, "ids.json"))
        vectors = np.load(os.path.join(idx, "vectors.npy"), allow_pickle=False)
    except (OSError, ValueError):
        raise Refusal("voice model unavailable: build %s has no readable index. "
                      "Fix: builds-sync install %s" % (b.build_time, b.build_time))
    diffs = identity_diffs(el, recorded, el.identity())
    if diffs:
        raise Refusal("voice model unavailable: the index was embedded by another "
                      "embedding-lib setup (%s). Fix: builds-sync install %s, which "
                      "re-embeds it" % ("; ".join(diffs), b.build_time))
    if ids != [e.get("id") for e in exemplars] or len(vectors) != len(ids):
        raise Refusal("voice model unavailable: build %s's index doesn't match its "
                      "exemplars. Fix: builds-sync install %s" % (b.build_time, b.build_time))

    pool = [i for i, e in enumerate(exemplars) if e.get("audience") == audience]
    if pool and k:
        q = np.asarray(el.embed([a.situation]), dtype=np.float32)[0]
        scores = vectors[pool] @ q
        ranked = sorted(zip(pool, (float(s) for s in scores)), key=lambda t: -t[1])
    else:
        ranked = []
    want = set(purposes)
    first = [(i, s, "purpose") for i, s in ranked if want & set(exemplars[i].get("purposes") or [])]
    picked = first[:k]
    if len(picked) < k:  # PLAN §3.5: the rest from the same audience, any purpose
        taken = set(i for i, _, _ in picked)
        picked += [(i, s, "audience") for i, s in ranked if i not in taken][:k - len(picked)]
    print(json.dumps({
        "build_time": b.build_time, "audience": audience, "purposes": purposes, "k": k,
        "exemplars": [{
            "id": exemplars[i]["id"], "purposes": exemplars[i].get("purposes") or [],
            "answered": exemplars[i].get("answered") or "", "text": exemplars[i]["text"],
            "score": round(s, 4), "matched": how,
        } for i, s, how in picked],
    }, ensure_ascii=False, indent=1))


# --- drafts ------------------------------------------------------------------

def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            t = f.read()
    except OSError as e:
        raise Failure("can't read --text-file: %s" % e)
    if not t.strip():
        raise Failure("--text-file %s is empty" % path)
    return t.rstrip("\n")


def installed_build_time():
    try:
        m = read_json(manifest_path())
        return m.get("build_time") if isinstance(m, dict) else None
    except (OSError, ValueError):
        return None


def append_draft(rec):
    ensure_dir(state_dir())
    fd = os.open(drafts_path(), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, (json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def record(kind, audience, purposes, destination, text, status, build_time, id_=None):
    return {"id": id_ or str(uuid.uuid4()), "ts": now(), "kind": kind,
            "audience": audience, "purposes": purposes, "destination": destination,
            "text": text, "status": status, "build_time": build_time,
            "host": socket.gethostname(), "schema_version": DRAFTS_SCHEMA}


def cmd_save_draft(a):
    audience = check_audience(a.audience)
    purposes = split_purposes(a.purposes)
    if not DESTINATION_RE.match(a.destination):
        raise Failure("--destination must be slack:<conversation>, bitbucket:<repo>#<pr>, "
                      "jira:<key> or other, got %r" % a.destination)
    rec = record("draft", audience, purposes, a.destination, read_text(a.text_file),
                 "drafted", installed_build_time())
    append_draft(rec)
    print(rec["id"])


def latest(id_):
    last = None
    try:
        with open(drafts_path(), encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("id") == id_:
                    last = r
    except FileNotFoundError:
        pass
    return last


def cmd_save_final(a):
    prev = latest(a.id)
    if prev is None:
        raise Failure("no draft with id %s in %s" % (a.id, drafts_path()))
    rec = record("final", prev.get("audience"), prev.get("purposes"), prev.get("destination"),
                 read_text(a.text_file), a.status, prev.get("build_time"), id_=a.id)
    append_draft(rec)
    print("%s %s" % (a.id, a.status))


# --- status ------------------------------------------------------------------

def cmd_status(a):
    out = {"state": state_dir(), "build_time": None, "usable": False, "refusal": None,
           "exemplars": None, "drafts": 0}
    try:
        with open(drafts_path(), encoding="utf-8") as f:
            out["drafts"] = len(set(json.loads(l).get("id") for l in f if l.strip()))
    except (OSError, ValueError):
        pass
    try:
        b = Build()
        out["build_time"] = b.build_time
        for name in ("guide.json", "stats.json", "build.json"):
            b.file(name)
        out["exemplars"] = len(b.file("exemplars.json").get("exemplars") or [])
        el = load_embedding_lib()
        recorded = read_json(os.path.join(b.dir, "index", "identity.json"))
        diffs = identity_diffs(el, recorded, el.identity())
        if diffs:
            raise Refusal("voice model unavailable: the index was embedded by another "
                          "embedding-lib setup (%s). Fix: builds-sync install %s"
                          % ("; ".join(diffs), b.build_time))
        out["usable"] = True
    except (Refusal, Failure) as e:
        out["refusal"] = str(e)
    except (OSError, ValueError) as e:
        out["refusal"] = "voice model unavailable: %s" % e
    print(json.dumps(out, indent=1))


# --- main --------------------------------------------------------------------

def parser():
    p = argparse.ArgumentParser(prog=PKG, description="guide and exemplar search for drafts in your voice")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("install-build", help="install a build from builds-sync")
    s.add_argument("dir")
    s.add_argument("--build-time", required=True)
    s.set_defaults(fn=cmd_install_build)
    for name, fn in (("guide", cmd_guide), ("search", cmd_search)):
        s = sub.add_parser(name)
        s.add_argument("--audience", required=True)
        s.add_argument("--purposes", required=True)
        if name == "search":
            s.add_argument("--situation", required=True)
            s.add_argument("--k", type=int)
        s.set_defaults(fn=fn)
    s = sub.add_parser("save-draft")
    s.add_argument("--audience", required=True)
    s.add_argument("--purposes", required=True)
    s.add_argument("--destination", required=True)
    s.add_argument("--text-file", required=True)
    s.set_defaults(fn=cmd_save_draft)
    s = sub.add_parser("save-final")
    s.add_argument("--id", required=True)
    s.add_argument("--text-file", required=True)
    s.add_argument("--status", choices=("approved", "discarded"), default="approved")
    s.set_defaults(fn=cmd_save_final)
    s = sub.add_parser("status")
    s.set_defaults(fn=cmd_status)
    return p


def main(argv):
    os.umask(0o077)
    p = parser()
    a = p.parse_args(argv)
    if not getattr(a, "fn", None):
        p.print_help()
        return 2
    try:
        a.fn(a)
    except Refusal as e:
        print("%s: %s" % (PKG, e), file=sys.stderr)
        return 3
    except Failure as e:
        print("%s: %s" % (PKG, e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
