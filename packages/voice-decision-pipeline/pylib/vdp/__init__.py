"""voice-decision-pipeline: builds the corpus the voice and decision models
are made from (PLAN.md §2), and later the models themselves.

This release covers corpus extraction only (PLAN §5, Releases): reading the
four sources, redacting credentials, anonymising, the per-source review
batches, `forget`, and the corpus embedding index. Nothing here sends
anything anywhere; the passes that send anonymised text come in later
releases and must check `sendable()` first.
"""

VDP_API = 1
SCHEMA_VERSION = 1
SOURCES = ("slack", "transcripts", "bitbucket", "gsd")
