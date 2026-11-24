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

def build_drafting():
    """stats.json's drafting section of the installed build, or {} when no
    build can be read (the command's own read then refuses it)."""
    try:
        return Build().file("stats.json").get("drafting") or {}
    except (Refusal, Failure):
        return {}


def build_purposes():
    """The purposes the installed build was labelled with, else this
    release's own list."""
    ps = build_drafting().get("purposes")
    if isinstance(ps, list) and ps and all(isinstance(p, str) and p for p in ps):
        return tuple(ps)
    return PURPOSES


def build_audiences():
    """[{slug, corpus, routing}] of the installed build, else this release's
    own audiences, jira the one without a corpus."""
    au = build_drafting().get("audiences")
    if isinstance(au, list) and au and all(isinstance(a, dict) and isinstance(a.get("slug"), str) for a in au):
        return au
    return [{"slug": a, "corpus": a != "jira", "routing": []} for a in AUDIENCES]


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
    known = [x["slug"] for x in build_audiences()]
    if a not in known:
        raise Failure("unknown audience %s; audiences are: %s" % (a, ", ".join(known)))
    return a


# The pipeline's rule for the words a guide rule quotes (voicestats.quoted):
# up to 3 words of letters only, so their shares can be shown beside the rules.
QUOTE = re.compile(r"(?:(?<=^)|(?<=[\s(]))['\"‘“]([^'\"’”]{2,40}?)['\"’”](?=[\s,.;:)!?]|$)")
SLOT = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def quoted(rule):
    out = []
    for m in QUOTE.finditer(rule):
        q = m.group(1).strip(" .,-!?")
        if q and re.fullmatch(r"[A-Za-z' ,]+", q) and len(q.split()) <= 3:
            out.append(q.lower())
    return out


def fill(template, **slots):
    """The pipeline's settings.fill: each {name} replaced once."""
    return SLOT.sub(lambda m: str(slots[m.group(1)]) if m.group(1) in slots else m.group(0), template)


def render_text(g, stats, audience, purposes, notes, quoted_on, rare_below, w, corpus):
    """The pipeline's guide.render_text, the guide a validation draft read,
    with the wording w the build carries."""
    bl = lambda rs: "\n".join("- %s" % r for r in rs)
    out = []
    if g.get("own_rules"):
        out.append(w["own_rules"] + "\n" + bl(g["own_rules"]))
    if notes:
        out.append(w["notes"] + "\n" + bl(notes))
    if not corpus:
        out.append(w["jira"] + "\n" + bl(g.get("jira", [])))
        return "\n\n".join(out)
    if g.get("general"):
        out.append(w["general"] + "\n" + bl(g["general"]))
    a = g.get("audiences", {}).get(audience, {})
    if a.get("rules"):
        out.append(fill(w["audience"], audience=audience) + "\n" + bl(a["rules"]))
    for p in purposes:
        if a.get("purposes", {}).get(p):
            out.append(fill(w["purpose"], purpose=p) + "\n" + bl(a["purposes"][p]))
    if len(purposes) > 1 and g.get("combinations"):
        out.append(w["combining"] + "\n" + bl(g["combinations"]))
    st = (stats or {}).get("audiences", {}).get(audience)
    if st:
        out.append(fill(w["measured"], audience=audience, median_words=st["median_words"],
                        p90_words=st["p90_words"], lowercase_start=int(st["lowercase_start"] * 100),
                        full_stop_end=int(st["full_stop_end"] * 100),
                        exclamation_per_message=st["exclamation_per_message"],
                        emoji_per_message=st["emoji_per_message"]))
        if st.get("style"):
            out.append(fill(w["style"], audience=audience,
                            shares=", ".join("%s %s" % (k, format(v, ".0%")) for k, v in st["style"].items())))
        for p in purposes:
            sp = st.get("purposes", {}).get(p)
            if sp:
                out.append(fill(w["purpose_measured"], audience=audience, purpose=p,
                                median_words=sp["median_words"], p90_words=sp["p90_words"],
                                messages=sp["messages"]))
    shown_rules = list(g.get("general", [])) + list(a.get("rules", []))
    for p in purposes:
        shown_rules += a.get("purposes", {}).get(p, [])
    if len(purposes) > 1:
        shown_rules += list(g.get("combinations", []))
    rates = (stats or {}).get("quoted", {}).get(audience, {}) if quoted_on else {}
    rare = sorted({q for r in shown_rules for q in quoted(r) if q in rates and rates[q] < rare_below},
                  key=lambda q: (rates[q], q))
    if rare:
        out.append(fill(w["quoted"], audience=audience,
                        shares=", ".join('"%s" %s' % (q, format(rates[q], ".1%")) for q in rare)))
    ns = [x["phrase"] for x in (stats or {}).get("never_say", []) if isinstance(x, dict) and x.get("phrase")]
    if ns:
        out.append(fill(w["never_say"], phrases="; ".join('"%s"' % p for p in ns[:w["never_say_max"]])))
    return "\n\n".join(out)


RENDER_KEYS = ("own_rules", "notes", "jira", "general", "audience", "purpose", "combining", "measured",
               "style", "purpose_measured", "quoted", "never_say", "never_say_max")


def cmd_guide(a):
    audience = check_audience(a.audience)
    purposes = split_purposes(a.purposes)
    b = Build()
    g = b.file("guide.json")
    st = b.file("stats.json")
    dr = st.get("drafting") or {}
    w = dr.get("render")
    if not isinstance(w, dict) or any(k not in w for k in RENDER_KEYS) or not isinstance(dr.get("draft_system"), str):
        raise Refusal("voice model unavailable: build %s carries no drafting wording. Fix: voice-decision-pipeline voice build, then "
                      "publish and builds-sync install" % b.build_time)
    corpus = next((x.get("corpus", True) for x in build_audiences() if x["slug"] == audience), True)
    text = render_text(g, st, audience, purposes, (dr.get("notes") or {}).get(audience) or [],
                       audience in (dr.get("quoted_rates_for") or []), dr.get("rare_below", 0), w, corpus)
    out = ["# Voice guide: %s; %s (build %s)" % (audience, ", ".join(purposes), b.build_time), "",
           "## How to draft (the prompt this build was validated with)", dr["draft_system"].strip(), "",
           "## The guide", text]
    sys.stdout.write("\n".join(out).rstrip("\n") + "\n")


def cmd_audiences(a):
    """The build's audiences and where a draft goes for each."""
    for x in build_audiences():
        routing = [r for r in x.get("routing") or [] if isinstance(r, str)]
        print("%s: %s" % (x["slug"], "; ".join(routing) if routing else "(no routing given)"))


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
    s = sub.add_parser("audiences", help="the build's audiences and where a draft goes for each")
    s.set_defaults(fn=cmd_audiences)
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
