"""Command-line face of embedding_lib, run by bin/embedding-lib through the
bundled interpreter. Each command prints JSON so shell callers and tests can
read it without importing anything.

  identity          the record an index stores (one JSON object)
  embed             JSONL on stdin: {"id": ..., "text": "..."} per line;
                    JSONL on stdout: {"id": ..., "vector": [...]} per line
  tokens            same input; {"id": ..., "tokens": N} per line
  check-identity    a recorded identity (JSON) on stdin; exit 3 and the
                    differences on stderr if it doesn't match
  probe             embeds two fixed sentences and checks the result; used by
                    `embedding-lib check` and the installer's verify_probe
"""

import json
import sys

import embedding_lib as el


def _read_items():
    items = []
    for n, line in enumerate(sys.stdin, 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            items.append((obj["id"], obj["text"]))
        except (ValueError, KeyError, TypeError):
            sys.exit(f"line {n}: expected {{\"id\": ..., \"text\": \"...\"}}")
        if not isinstance(items[-1][1], str):
            sys.exit(f"line {n}: text must be a string")
    return items


def main(argv):
    cmd = argv[0] if argv else ""
    try:
        if cmd == "identity":
            print(json.dumps(el.identity(), sort_keys=True))
        elif cmd == "embed":
            items = _read_items()
            vecs = el.embed([t for _, t in items]) if items else []
            for (i, _), v in zip(items, vecs):
                print(json.dumps({"id": i, "vector": [round(float(x), 7) for x in v]}))
        elif cmd == "tokens":
            items = _read_items()
            for (i, _), n in zip(items, el.count_tokens([t for _, t in items])):
                print(json.dumps({"id": i, "tokens": n}))
        elif cmd == "check-identity":
            el.check_identity(json.load(sys.stdin))
            print("matches")
        elif cmd == "probe":
            v = el.embed(["Can you review the PR?",
                          "Please take a look at my pull request",
                          "The weather is nice today"])
            norms = [float((r * r).sum()) for r in v]
            near, far = float(v[0] @ v[1]), float(v[0] @ v[2])
            ok = (v.shape == (3, el.DIMENSION)
                  and all(abs(n - 1) < 1e-4 for n in norms) and near > far)
            print(json.dumps({"ok": ok, "shape": list(v.shape),
                              "similar": round(near, 3), "unrelated": round(far, 3)}))
            return 0 if ok else 1
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except el.NotSetUp as e:
        print(f"embedding-lib: {e}", file=sys.stderr)
        return 4
    except el.Mismatch as e:
        print(f"embedding-lib: {e}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
