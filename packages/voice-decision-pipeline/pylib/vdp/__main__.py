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
    for k in ("james_user_id", "conversations", "slack_export"):
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
          f"James's account: {', '.join(d.get('bitbucket_me') or []) or 'not set'}")


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
    s = sub.add_parser("index"); s.set_defaults(f=cmd_index)
    s = sub.add_parser("status"); s.set_defaults(f=cmd_status)
    s = sub.add_parser("sendable"); s.add_argument("source", choices=SOURCES); s.set_defaults(f=cmd_sendable)
    s = sub.add_parser("probe"); s.set_defaults(f=cmd_probe)
    a = p.parse_args(argv)
    return a.f(a) or 0


if __name__ == "__main__":
    sys.exit(main())
