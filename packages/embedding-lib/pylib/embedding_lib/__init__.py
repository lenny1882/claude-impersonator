"""embedding-lib: the one place text becomes vectors for the voice and
decision models.

Why it exists. Exemplar search compares a draft's context with every message
in the voice corpus by meaning (PLAN §3.5). That only works if the corpus
index and the query at drafting time come out of the same model, the same
library versions and the same Python; vectors from two different setups sit
in different spaces, and a nearest-neighbour search across them returns
confident nonsense with no error. The pipeline builds the index on one
machine and `voice-runtime` queries it on up to three (this one, the
WorkSpace, EndeavourOS), whose system Pythons are 3.8, 3.12 and 3.14. So the
environment lives here, once, on a bundled Python, and every index records
`identity()` so a consumer can refuse one built by anything else
(PLAN §5).

Dependents load this module through embedding-lib's own interpreter,
``~/.local/share/embedding-lib/venv/bin/python``, never through PATH, and
check ``EMBEDDING_LIB_API`` before use (the rrc/rrcd pattern, PLAN §5).

Nothing here touches the network. The model is read from the snapshot
`embedding-lib setup` downloaded, with Hugging Face's offline switches set
before the libraries are imported, so a missing file is an error, never a
silent download in the middle of drafting.
"""

import hashlib
import os
import platform

# Bumped only when a function here changes in a way a dependent would notice.
EMBEDDING_LIB_API = 1

MODEL = "BAAI/bge-base-en-v1.5"
# The model repo's commit, so a re-upload upstream can't change the vectors.
REVISION = "a5beb1e3e68b9ab74eb54cfd186867f64f240e1a"
DIMENSION = 768
MAX_TOKENS = 512

PYLIB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.environ.get("EMBEDDING_LIB_HOME") or os.path.join(
    os.path.expanduser("~"), ".local", "share", "embedding-lib")
MODEL_DIR = os.path.join(
    HOME, "hf", "hub", "models--BAAI--bge-base-en-v1.5", "snapshots", REVISION)

# What must be equal for two sets of vectors to be comparable. `libraries`
# is informational: the lock's hash already covers every version in it.
COMPARED = ("api", "model", "revision", "dimension", "normalised",
            "python", "lock_sha256")


class NotSetUp(RuntimeError):
    """The environment or the model isn't there. The message says what to run."""


class Mismatch(ValueError):
    """An index was built by a different setup. The message names each difference."""


def _offline():
    os.environ["HF_HOME"] = os.path.join(HOME, "hf")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def _lock_sha256():
    with open(os.path.join(PYLIB, "requirements.txt"), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def identity():
    """The record every index stores beside its vectors (PLAN §5)."""
    from importlib.metadata import version
    return {
        "api": EMBEDDING_LIB_API,
        "model": MODEL,
        "revision": REVISION,
        "dimension": DIMENSION,
        "normalised": True,
        "python": platform.python_version(),
        "lock_sha256": _lock_sha256(),
        "libraries": {p: version(p) for p in
                      ("torch", "sentence-transformers", "transformers")},
    }


def check_identity(recorded):
    """Raise Mismatch unless `recorded` (an index's stored identity) matches
    this environment. The caller adds which file it was reading."""
    here = identity()
    diffs = [f"{k}: index has {recorded.get(k)!r}, this environment has {here[k]!r}"
             for k in COMPARED if recorded.get(k) != here[k]]
    if diffs:
        raise Mismatch(
            "embedding model or environment differs from the one that built "
            "the index:\n  " + "\n  ".join(diffs) +
            "\nThe pipeline has to re-embed with this environment before the "
            "index can be used.")


_model = None


def _load():
    global _model
    if _model is None:
        if not os.path.isfile(os.path.join(MODEL_DIR, "model.safetensors")):
            raise NotSetUp(f"the model isn't at {MODEL_DIR}; run: embedding-lib setup")
        _offline()
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_DIR, device="cpu")
        _model.max_seq_length = MAX_TOKENS
    return _model


def embed(texts, batch_size=32):
    """Unit-length float32 vectors, one row per text, DIMENSION wide.

    Text past MAX_TOKENS is cut off by the model; use count_tokens first
    where that matters (the pipeline's message-plus-reply pairs, PLAN §3.5)."""
    if isinstance(texts, str):
        raise TypeError("embed takes a list of strings, not one string")
    return _load().encode(list(texts), batch_size=batch_size,
                          normalize_embeddings=True, convert_to_numpy=True,
                          show_progress_bar=False)


def count_tokens(texts):
    """Tokens each text takes, counted as the model counts them, including
    the two markers it adds."""
    tok = _load().tokenizer
    return [len(tok(t, add_special_tokens=True)["input_ids"]) for t in texts]
