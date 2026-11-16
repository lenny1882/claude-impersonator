"""voice-decision-pipeline: builds the corpus the voice and decision models
are made from (PLAN.md §2), and later the models themselves.

Corpus extraction (PLAN §2): reading the four sources, redacting
credentials, anonymising, the per-source review batches, `forget`, and the
corpus embedding index. The voice build (PLAN §3; voice.py and the modules
it names): the only part that sends anything, anonymised, through
model.py, and only once voice.require_sendable() holds.
"""

VDP_API = 1
SCHEMA_VERSION = 1
SOURCES = ("slack", "transcripts", "bitbucket", "gsd")
