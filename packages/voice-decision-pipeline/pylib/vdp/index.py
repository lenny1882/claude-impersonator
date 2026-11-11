"""The corpus embedding index: index/vectors.npy, ids.json, identity.json
(PLAN §2.2, §3.5).

Built from James's voice items (Slack and Bitbucket; never transcripts,
GSD records, reactions, approvals or his self-DM). Each is embedded with
the message it answers (Claude's design, confirmed by James, 10 Nov 2026):
in a thread, the nearest earlier message by someone else; outside one, the
nearest earlier message by someone else in its window; for a PR comment,
its parent comment or else the PR's title and description. The pair is
kept inside the model's 512 tokens by trimming the start of the answered
message, never James's own words.

Runs on embedding-lib's interpreter (it imports embedding_lib from that
package's install directory, PLAN §5 Coupling), not the pipeline's venv.
identity.json holds embedding_lib.identity(), so a reader refuses an index
built by another setup.
"""

import json
import os

from . import state
from .record import flags

VOICE_SOURCES = ("slack", "bitbucket")
MAX_TOKENS = 512


def index_dir():
    return os.path.join(state.root(), "index")


def voice_item(r):
    f = flags(r)
    return ("item" in f and "no-voice" not in f and "approval" not in f
            and not any(x.startswith("reaction:") for x in f) and (r.get("text") or "").strip())


def answered(r, by_id):
    sf = r.get("source_fields") or {}
    ctx = [by_id[c] for c in r.get("context_ids") or [] if c in by_id]
    if r["source"] == "bitbucket":
        parent = sf.get("parent")
        if parent:
            pid = r["id"].rsplit(":c:", 1)[0] + f":c:{parent}"
            if pid in by_id:
                return by_id[pid]["text"]
        pr = r["id"].split(":c:", 1)[0]
        return by_id[pr]["text"] if pr in by_id else ""
    earlier = [c for c in ctx if c["ts"] < r["ts"] and c.get("author") != r.get("author")]
    return earlier[-1]["text"] if earlier else ""


def pairs():
    recs = []
    for s in VOICE_SOURCES:
        recs.extend(state.read_jsonl(state.corpus_file(s)))
    by_id = {r["id"]: r for r in recs}
    out = []
    for r in recs:
        if voice_item(r):
            out.append((r["id"], answered(r, by_id), r["text"]))
    return out


def fit(el, items):
    texts = []
    for _, ans, msg in items:
        texts.append(f"{ans}\n\n{msg}" if ans else msg)
    for _ in range(4):
        counts = el.count_tokens(texts)
        over = [i for i, n in enumerate(counts) if n > MAX_TOKENS]
        if not over:
            break
        for i in over:
            _, ans, msg = items[i]
            if not ans:
                continue
            keep = max(0, int(len(ans) * (MAX_TOKENS - 8) / counts[i]) -
                       (len(texts[i]) - len(ans)))
            ans = ans[-keep:] if keep > 0 else ""
            items[i] = (items[i][0], ans, msg)
            texts[i] = f"{ans}\n\n{msg}" if ans else msg
    return texts


def build(log=print):
    import numpy as np
    import embedding_lib as el
    if getattr(el, "EMBEDDING_LIB_API", None) != 1:
        raise SystemExit("voice-decision-pipeline: embedding-lib API 1 is required")
    items = pairs()
    if not items:
        raise SystemExit("voice-decision-pipeline: no voice items in the corpus; run extract first")
    log(f"== index: {len(items)} voice items")
    texts = fit(el, items)
    vecs = []
    step = 512
    for i in range(0, len(texts), step):
        vecs.append(el.embed(texts[i:i + step]))
        log(f"  embed {min(i + step, len(texts))}/{len(texts)}")
    m = np.vstack(vecs).astype("float32")
    d = index_dir()
    os.makedirs(d, mode=0o700, exist_ok=True)
    tmp = os.path.join(d, ".vectors.tmp.npy")
    np.save(tmp, m)
    os.chmod(tmp, 0o600)
    os.replace(tmp, os.path.join(d, "vectors.npy"))
    state.write_json(os.path.join(d, "ids.json"), [i for i, _, _ in items])
    state.write_json(os.path.join(d, "identity.json"), el.identity())
    log(f"  ok    index: {m.shape[0]} x {m.shape[1]}")
    return m.shape


def drop_rows(ids):
    """Rewrite the matrix without the given record ids (forget)."""
    d = index_dir()
    p = os.path.join(d, "vectors.npy")
    if not ids or not os.path.exists(p):
        return 0
    import numpy as np
    order = state.read_json(os.path.join(d, "ids.json"), [])
    keep = [i for i, x in enumerate(order) if x not in ids]
    if len(keep) == len(order):
        return 0
    m = np.load(p)[keep]
    tmp = os.path.join(d, ".vectors.tmp.npy")
    np.save(tmp, m)
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)
    state.write_json(os.path.join(d, "ids.json"), [order[i] for i in keep])
    return len(order) - len(keep)
