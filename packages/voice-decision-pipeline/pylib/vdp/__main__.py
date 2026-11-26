"""Command line for the pipeline's Python half. bin/voice-decision-pipeline
handles setup, logging and which interpreter runs what, then calls this."""

import argparse
import json
import os
import sys
from collections import Counter

from . import SOURCES, VDP_API, inputs, state


def cmd_init_inputs(a):
    dest = inputs.file()
    if os.path.exists(dest) and not a.force:
        raise SystemExit(f"voice-decision-pipeline: {dest} already exists and may hold "
                         "forget and pick-repos changes; pass --force to replace it")
    with open(a.path, encoding="utf-8") as f:
        d = json.load(f)
    for k in ("self_user_id", "conversations", "slack_export"):
        if k not in d:
            raise SystemExit(f"voice-decision-pipeline: {a.path} has no {k}")
    struck_names = [x for x in d.get("struck_conversations") or [] if isinstance(x, str)]
    ids = {c.get("name"): c["id"] for c in d["conversations"]}
    d["struck_conversations"] = sorted({ids.get(x, x) for x in struck_names})
    state.write_json(dest, d)
    print(f"  ok    inputs copied to {dest}; the original at {a.path} can now be deleted")


def extract_one(source, d, counts, a):
    from . import bitbucket, gsd, slack, transcripts
    if source == "slack":
        return slack.extract(d, counts)
    if source == "transcripts":
        return transcripts.extract(d, counts)
    if source == "gsd":
        return gsd.extract(d, counts, roots=a.gsd_root or None)
    if source == "bitbucket":
        return bitbucket.extract(d, counts)
    raise SystemExit(f"unknown source {source}")


def cmd_extract(a):
    d = inputs.load()
    todo = SOURCES if a.source == "all" else [a.source]
    with state.lock():
        for s in todo:
            if s == "bitbucket" and a.source == "all" and not d.get("bitbucket_repos"):
                print("  skip  bitbucket: no repos picked yet (pick-repos)")
                continue
            counts = Counter()
            print(f"== extract {s}", flush=True)
            recs, stats = extract_one(s, d, counts, a)
            state.write_jsonl(state.corpus_file(s), recs)
            if s == "bitbucket":
                from . import bitbucket
                bitbucket.clear_progress()
            if s == "slack":
                state.write_json(state.path("slack-meta.json"),
                                 {"audiences_hash": inputs.audiences_hash(d)})
            print(f"  ok    corpus/{s}.jsonl: {len(recs)} records {dict(stats)}")
            if counts:
                print(f"  ok    credentials redacted, by type: {dict(counts)}")


def cmd_import_transcripts(a):
    d = inputs.load()
    src = os.path.abspath(a.dir)
    if not os.path.isdir(src):
        raise SystemExit(f"voice-decision-pipeline: no directory {src}")
    entry = {"dir": src, "machine": a.machine or os.path.basename(src.rstrip("/"))}
    d["transcript_imports"] = [i for i in d["transcript_imports"] if i["dir"] != src] + [entry]
    inputs.save(d)
    print(f"  ok    {src} will be read as machine {entry['machine']!r} by every transcript extraction")
    a.source = "transcripts"
    cmd_extract(a)


def cmd_pick_repos(a):
    d = inputs.load()
    if a.me:
        d["bitbucket_me"] = sorted(set(d.get("bitbucket_me") or []) | set(a.me))
    for r in a.repos:
        if r.count("/") != 1:
            raise SystemExit(f"voice-decision-pipeline: {r!r} isn't <workspace>/<repo>")
        if r not in d["bitbucket_repos"]:
            d["bitbucket_repos"].append(r)
    for r in a.remove or []:
        d["bitbucket_repos"] = [x for x in d["bitbucket_repos"] if x != r]
    inputs.save(d)
    print(f"  ok    Bitbucket repos: {', '.join(d['bitbucket_repos']) or 'none'}; "
          f"your Bitbucket account: {', '.join(d.get('bitbucket_me') or []) or 'not set'}")


def cmd_anonymise(a):
    from . import anonymise
    with state.lock():
        anonymise.run()


def cmd_batch(a):
    from . import batches
    name, n = batches.draw(a.source)
    print(f"  ok    {name}: {n} items; review it with 'voice-decision-pipeline review'")


def cmd_review(a):
    from . import review
    review.serve(a.port, open_browser=not a.no_browser)


def cmd_forget(a):
    from . import forget
    with state.lock():
        forget.run(a.who)


def cmd_show(a):
    from . import show
    show.bitbucket(a.repo)


def cmd_index(a):
    from . import index
    with state.lock():
        index.build()


def cmd_status(a):
    from . import batches
    from .record import flags
    d = inputs.load(required=False)
    out = {"state": state.root(), "api": VDP_API, "inputs": bool(d.get("conversations")),
           "bitbucket_repos": d.get("bitbucket_repos", []), "sources": {}}
    rv = batches.load_review()
    for s in SOURCES:
        recs = list(state.read_jsonl(state.corpus_file(s)))
        out["sources"][s] = {
            "records": len(recs), "items": sum(1 for r in recs if "item" in flags(r)),
            "anonymised": os.path.exists(state.anon_file(s)),
            "approved_batches": rv[s]["approved"], "stopped": rv[s]["stopped"],
            "sendable": batches.sendable(s)}
    out["blocks_next_batch"] = batches.gates()
    bad = state.check_modes()
    out["not_owner_only"] = bad
    print(json.dumps(out, indent=1))
    return 1 if bad else 0


def cmd_sendable(a):
    from . import batches
    return 0 if batches.sendable(a.source) else 5


def cmd_probe(a):
    """The live check: anonymise one made-up message with the real spaCy
    model and confirm both names it holds are gone."""
    import spacy
    nlp = spacy.load("en_core_web_trf", disable=["tagger", "parser", "attribute_ruler", "lemmatizer"])
    doc = nlp("Alice Example said Bob Sample should merge it before Friday.")
    people = sorted(e.text for e in doc.ents if e.label_ == "PERSON")
    ok = people == ["Alice Example", "Bob Sample"]
    print(json.dumps({"ok": ok, "people": people, "spacy": spacy.__version__}))
    return 0 if ok else 1


def cmd_voice(a):
    """The voice build's steps (PLAN §3), in order: label, label --second,
    holdout, guide, validate, pairs, build, publish."""
    from . import guide, labels, pool, validate, voice, voicebuild
    step = a.step
    if step == "label":
        with state.lock():
            rc = labels.run("second" if a.second else "labeller",
                            redo=[x for x in (a.redo or "").split(",") if x])
            if not rc and labels.read("labeller") and labels.read("second"):
                labels.write_disagreements(new_sample=a.new_sample)
            if not rc and a.new_sample:
                labels.draw_sample(new=True)
            return rc
    if step == "holdout":
        with state.lock():
            if a.more:
                pool.holdout_more(a.more, a.count)
            else:
                pool.holdout(fresh=a.fresh)
        return 0
    if step == "rules":
        made = guide.init_rules()
        print(f"  ok    {guide.rules_file()}" + (" created from the template" if made else " already exists"))
        made = guide.init_struck()
        print(f"  ok    {guide.struck_file()}" + (" created from the template" if made else " already exists"))
        return 0
    if step == "guide":
        with state.lock():
            return 0 if guide.write() is not None else 6
    if step == "drafter":
        from . import drafter
        d = drafter.load()
        print(f"drafter settings: {drafter.file()}")
        try:
            judged, stale = validate.judged_audiences(), set(validate.stale_audiences())
        except (SystemExit, OSError, KeyError):
            judged, stale = set(), set()
        pr = state.read_json(validate.pairs_file(), None) or {}
        paired = {p["audience"] for p in validate.active(pr)}
        for aud, m in drafter.methods(d).items():
            pairs = "older method" if aud in stale else "current" if aud in paired else "none"
            print(f"  {aud}: method {m}; notes {len(d['notes'].get(aud, []))} lines; "
                  f"quoted-word shares {'yes' if aud in d['quoted_rates_for'] else 'no'}; "
                  f"judged under it {'yes' if aud in judged else 'no'}; pairs {pairs}")
        return 0
    if step == "settings":
        from . import settings
        if a.save:
            settings.save_copies()
            return 0
        d = settings.load()
        ch = settings.changed(d)
        print(f"settings: {settings.file()}")
        print("  differs from the defaults: " + (", ".join(ch) if ch else "nothing"))
        print("  audiences: " + ", ".join(a["slug"] + ("" if a["corpus"] else " (no corpus)") for a in d["audiences"]))
        print(f"  purposes: {', '.join(d['labels']['purposes'])}")
        print("  models: " + ", ".join(f"{k} {v}" for k, v in d["models"].items()))
        r = d["pass_rule"]
        print(f"  pass rule: overall {r['overall_bar']}, audience {r['audience_bar']}, sure {r['sure']}, "
              f"unsure {r['unsure']}, grades {r['grades_all']}/{r['grades_audience']}, "
              f"{r['pairs_per_audience']} pairs an audience, exemplar counts {r['exemplar_counts']}")
        di = settings.draft_inputs(d)
        print("  in the draft methods: " + (", ".join(sorted(di)) if di else "nothing (all defaults)"))
        return 0
    if step == "validate":
        with state.lock():
            return validate.drafts_and_judge(limit=a.limit, only_batch=a.batch)
    if step == "pairs":
        with state.lock():
            if a.redraw == "all":
                stale = validate.stale_audiences()
                if not stale:
                    print("  --    every audience's pairs are drafted under its current method; nothing to draw again")
                for aud in stale:
                    validate.redraw(aud)
            elif a.redraw:
                validate.redraw(a.redraw)
            elif a.drop:
                validate.drop_pairs([x for x in a.drop.split(",") if x],
                                    reason="dropped with voice pairs --drop")
            else:
                validate.make_pairs(audience=a.more)
            validate.judge_review()
        return 0
    if step == "upkeep":
        from . import upkeep
        with state.lock():
            if a.end_session:
                upkeep.end_session()
                return 0
            upkeep.match()
            d = upkeep.due()
            if d["due"] or a.suggest:
                return 0 if upkeep.suggest(force=a.suggest) is not None else 6
            print("  --    no review session due; nothing sent")
        return 0
    if step == "build":
        from . import upkeep
        with state.lock():
            upkeep.match()
            voicebuild.build()
        return 0
    if step == "publish":
        with state.lock():
            voicebuild.publish()
        return 0
    if step == "status":
        out = {"labels": labels.summary(), "holdout": (state.read_json(pool.holdout_file(), {}) or {}).get("run"),
               "best_count": validate.best_count(), "validation": validate.report(),
               "publish_blocked_by": voicebuild.gates(), "newest_build": voicebuild.newest()[0],
               "own_rules": guide.rules_file(), "struck_rules": guide.struck_file()}
        print(json.dumps(out, indent=1))
        return 0
    raise SystemExit(f"unknown voice step {step}")


def cmd_upkeep(a):
    from . import upkeep
    with state.lock():
        upkeep.import_records(a.file)


def cmd_due(a):
    from . import upkeep
    print(json.dumps(state.read_json(upkeep.path("due.json"), None) or {"due": False, "line": ""}))


def main(argv=None):
    p = argparse.ArgumentParser(prog="voice-decision-pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init-inputs"); s.add_argument("path"); s.add_argument("--force", action="store_true")
    s.set_defaults(f=cmd_init_inputs)
    s = sub.add_parser("extract"); s.add_argument("source", choices=list(SOURCES) + ["all"])
    s.add_argument("--gsd-root", action="append"); s.set_defaults(f=cmd_extract)
    s = sub.add_parser("import-transcripts"); s.add_argument("dir"); s.add_argument("--machine")
    s.set_defaults(f=cmd_import_transcripts, gsd_root=None)
    s = sub.add_parser("pick-repos"); s.add_argument("repos", nargs="*")
    s.add_argument("--me", action="append"); s.add_argument("--remove", action="append")
    s.set_defaults(f=cmd_pick_repos)
    s = sub.add_parser("anonymise"); s.set_defaults(f=cmd_anonymise)
    s = sub.add_parser("batch"); s.add_argument("source", choices=SOURCES); s.set_defaults(f=cmd_batch)
    s = sub.add_parser("review"); s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true"); s.set_defaults(f=cmd_review)
    s = sub.add_parser("forget"); s.add_argument("who"); s.set_defaults(f=cmd_forget)
    s = sub.add_parser("show"); s.add_argument("source", choices=["bitbucket"])
    s.add_argument("--repo"); s.set_defaults(f=cmd_show)
    s = sub.add_parser("index"); s.set_defaults(f=cmd_index)
    s = sub.add_parser("status"); s.set_defaults(f=cmd_status)
    s = sub.add_parser("sendable"); s.add_argument("source", choices=SOURCES); s.set_defaults(f=cmd_sendable)
    s = sub.add_parser("probe"); s.set_defaults(f=cmd_probe)
    s = sub.add_parser("upkeep"); s.add_argument("action", choices=["import"]); s.add_argument("file")
    s.set_defaults(f=cmd_upkeep)
    s = sub.add_parser("due"); s.set_defaults(f=cmd_due)
    s = sub.add_parser("voice")
    s.add_argument("step", choices=["label", "holdout", "rules", "guide", "drafter", "settings", "validate", "pairs",
                                    "upkeep", "build", "publish", "status"])
    s.add_argument("--second", action="store_true", help="label: the second model's blind pass")
    s.add_argument("--redo", help="label: send again items either model gave one of these purposes")
    s.add_argument("--new-sample", action="store_true", help="label: draw a fresh label-check sample and disagreement-grade sample")
    s.add_argument("--fresh", action="store_true", help="holdout: draw a fresh holdout (a new validation run)")
    s.add_argument("--save", action="store_true", help="settings: save the next numbered copy of each hand-edited settings file that changed")
    s.add_argument("--limit", type=int, help="validate: only the first N held-back messages")
    s.add_argument("--more", help="pairs: 12 more pairs for this audience; holdout: hold back more of it")
    s.add_argument("--count", type=int, default=12, help="holdout --more: how many more to hold back")
    s.add_argument("--redraw", help="pairs: draw this audience's pairs again from its new drafts; 'all' for every audience")
    s.add_argument("--batch", action="store_true", help="validate: draft only one batch per audience of messages never shown")
    s.add_argument("--drop", help="pairs: leave these pairs out of the result and draw as many new ones")
    s.add_argument("--suggest", action="store_true", help="upkeep: make the session's rule suggestions now, due or not")
    s.add_argument("--end-session", action="store_true", help="upkeep: end the review session")
    s.set_defaults(f=cmd_voice)
    a = p.parse_args(argv)
    # Keep a numbered copy of each hand-edited settings file that changed
    # since its last copy, before anything reads it (settings.py).
    if a.f not in (cmd_probe, cmd_init_inputs) and not (a.f is cmd_voice and a.step == "settings" and a.save):
        from . import settings
        try:
            settings.save_copies(quiet=True)
        except OSError as e:
            print(f"  warn  settings history not saved: {e}")
    return a.f(a) or 0


if __name__ == "__main__":
    sys.exit(main())
