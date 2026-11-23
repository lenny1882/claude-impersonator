"""A voice build (PLAN §5, Builds on every machine; the Stage 2 contract).

`voice build` assembles guide.json, exemplars.json, stats.json and
build.json, runs the leak check on them, and writes
voice/builds/<build-time>/build-<build-time>.tar in the state, its files
under voice-runtime/. A leak stops it before anything is written.

`voice publish` sends the newest build to the builds repo through
builds-sync's library, loaded from its install directory (PLAN §5,
Coupling). It refuses until the owner's label check has passed and the
validation run has passed (PLAN §3.4, §3.7): a runtime's version says
nothing about its model, which only validation lets through.
"""

import io
import json
import os
import sys
import tarfile
import time

from . import guide, inputs, labels, leaks, pool, state, validate
from .anonmap import Map

FILES = ("guide.json", "exemplars.json", "stats.json", "build.json")
DEFAULT_COUNT = 5
NEVER_SAY_KEYS = ("phrase", "self", "reference", "reference_count")


def builds_dir(*p):
    return state.path("voice", "builds", *p)


def build(log=print):
    bt = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    g = guide.assemble(bt)
    stats = state.read_json(state.path("voice", "stats.json"), None)
    if stats is None:
        raise SystemExit("voice-decision-pipeline: no statistics yet; run 'voice guide'")
    # A never-say entry's count field is "self"; an older stats.json gave it
    # another name, which is read as "self".
    stats = {**stats, "never_say": [{(k if k in NEVER_SAY_KEYS else "self"): v for k, v in x.items()}
                                    for x in stats.get("never_say", [])]}
    sm = guide.struck_summary(stats)
    stats, _ = guide.strike_stats(stats)
    stats = {**stats, "drafting": guide.drafting()}
    ex = pool.exemplars()
    k = validate.best_count() or DEFAULT_COUNT
    try:
        import embedding_lib as el
        ident = el.identity()
    except ImportError:
        raise SystemExit("voice-decision-pipeline: voice build runs on embedding-lib's interpreter")
    files = {
        "guide.json": g,
        "exemplars.json": {"schema_version": 1, "exemplars": ex},
        "stats.json": stats,
        "build.json": {"schema_version": 1, "build_time": bt,
                       "files": {"guide.json": 1, "exemplars.json": 1, "stats.json": 1},
                       "embedding_identity": ident, "exemplar_count": k,
                       "validation": validate.report()},
    }
    # embedding_identity is embedding-lib's description of its model, not
    # the corpus's words, so it isn't searched (as ids and source names
    # aren't in the copies); everything else in build.json is.
    searched = {**files, "build.json": {k: v for k, v in files["build.json"].items()
                                        if k != "embedding_identity"}}
    lr = leaks.scan_built(searched, inputs.load(), Map.load())
    state.write_json(leaks.build_report_file(), lr)
    # A term cleared by hand on the leak page, in the copies' check or the
    # build's, is cleared here too (PLAN §5).
    out_ = leaks.outstanding_built(lr)
    if out_:
        for t in out_[:10]:
            log(f"  leak  {t['kind']}: {t['count']}x in {', '.join(sorted({e['id'] for e in t['examples']}))}")
        raise SystemExit(f"voice-decision-pipeline: the leak check found {len(out_)} terms "
                         f"{sum(t['count'] for t in out_)} times in the built files; nothing was written "
                         "(voice/build-leak-report.json); look at each on the review page's leak check, "
                         "and fix it or clear it by hand there")
    out = builds_dir(bt, f"build-{bt}.tar")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name in FILES:
            data = (json.dumps(files[name], ensure_ascii=False, indent=1) + "\n").encode()
            ti = tarfile.TarInfo(f"voice-runtime/{name}")
            ti.size, ti.mtime, ti.mode = len(data), int(time.time()), 0o600
            tf.addfile(ti, io.BytesIO(data))
    with open(out + ".part", "wb") as f:
        f.write(buf.getvalue())
    os.replace(out + ".part", out)
    log(f"  ok    build {bt}: {len(ex)} exemplars, exemplar count {k}, "
        f"{len(g['own_rules'])} own rules, {len(g['audiences'])} audiences; "
        f"{sm['rules_matched']} struck rules and {sm['never_say_matched']} struck never-say phrases left out "
        f"({sm['rules'] - sm['rules_matched'] + sm['never_say'] - sm['never_say_matched']} struck lines match "
        "nothing now); leak check clean "
        f"({lr['terms_checked']} terms); {out}")
    return bt, out


def newest():
    """(build time, tarball) of the newest build, or (None, None) before the
    first: voice/builds/ only exists once a build has been written."""
    d = builds_dir()
    if not os.path.isdir(d):
        return None, None
    bts = sorted(x for x in os.listdir(d) if os.path.exists(os.path.join(d, x, f"build-{x}.tar")))
    return (bts[-1], os.path.join(d, bts[-1], f"build-{bts[-1]}.tar")) if bts else (None, None)


def gates():
    out = []
    c = labels.check_result()
    if not c.get("passed"):
        out.append("your label check hasn't passed" + (
            f" ({c['wrong']} wrong of {c['answered']} answered, {c['size']} drawn)" if c.get("drawn") else " (not drawn)"))
    r = validate.report()
    if not r.get("passed"):
        why = "not done" if not r.get("done") else (
            "blind test failed" if not r.get("blind_ok") else
            "grades failed" if not r.get("grades_ok") else
            f"failed for {', '.join(r['failed_audiences'])}" if r.get("failed_audiences") else
            f"more pairs needed for {', '.join(r['more_pairs_for'])}")
        out.append(f"validation run {r.get('run')} hasn't passed ({why})")
    return out


def load_builds_sync():
    # builds-sync installs its library as lib/builds_sync.py in its skill
    # directory (its README).
    home = os.environ.get("BUILDS_SYNC_HOME") or os.path.join(
        os.environ.get("CLAUDE_DIR") or os.path.expanduser("~/.claude"), "skills", "builds-sync")
    for sub in ("lib", "pylib", ""):
        p = os.path.join(home, sub)
        if os.path.exists(os.path.join(p, "builds_sync.py")) or os.path.isdir(os.path.join(p, "builds_sync")):
            sys.path.insert(0, p)
            import builds_sync
            if getattr(builds_sync, "BUILDS_SYNC_API", None) != 1:
                raise SystemExit("voice-decision-pipeline: builds-sync API 1 is required")
            return builds_sync
    raise SystemExit(f"voice-decision-pipeline: builds-sync is not installed ({home}); install it first")


def publish(log=print):
    bad = gates()
    if bad:
        raise SystemExit("voice-decision-pipeline: not published: " + "; ".join(bad))
    bt, tar = newest()
    if not bt:
        raise SystemExit("voice-decision-pipeline: no build yet; run 'voice build'")
    bs = load_builds_sync()
    where = bs.publish_build(tar, bt)
    log(f"  ok    build {bt} published to {where}")
    return bt
