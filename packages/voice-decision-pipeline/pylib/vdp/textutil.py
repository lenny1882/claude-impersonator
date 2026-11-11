"""Credential redaction and span tagging, applied while the corpus is built.

Redaction (PLAN §2.3): AWS, Slack and Bitbucket keys, JWTs, private keys and
`password=` lines become `[REDACTED:<type>]` before anything is stored, so
no copy of the corpus — real-name or anonymised — ever holds one. Findings
are counted by type, never logged by value.

Tags (PLAN §2.1): code, log, link and attachment spans, so the voice
analysis can skip them and the decision analysis can read them. Offsets
are into the stored (redacted) text.
"""

import re
from collections import Counter

# Order matters: the private-key block first, so its body isn't also matched
# piecemeal by the shorter patterns.
SECRETS = [
    ("private-key", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)",
        re.S)),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("aws-secret-key", re.compile(
        r"(?i)(?<=aws_secret_access_key)(\s*[=:]\s*[\"']?)[A-Za-z0-9/+=]{40}")),
    ("slack-token", re.compile(r"\bxox[abposr]-[0-9A-Za-z-]{10,}")),
    ("slack-webhook", re.compile(
        r"https://hooks\.slack\.com/services/[A-Z0-9]+/[A-Z0-9]+/[A-Za-z0-9]+")),
    ("bitbucket-token", re.compile(r"\bATBB[0-9A-Za-z_-]{20,}|\bATCTT3x[0-9A-Za-z_=-]{20,}")),
    ("github-token", re.compile(r"\bgh[pousr]_[0-9A-Za-z]{30,}")),
    ("anthropic-key", re.compile(r"\bsk-ant-[0-9A-Za-z_-]{20,}")),
    ("jwt", re.compile(r"\beyJ[0-9A-Za-z_-]{8,}\.eyJ[0-9A-Za-z_-]{8,}\.[0-9A-Za-z_-]{8,}")),
    ("password", re.compile(
        r"(?i)(?<![A-Za-z])(?:password|passwd|pwd|secret|api[_-]?key)(\s*[=:]\s*)(?![\s\[])(\"[^\"\n]*\"|'[^'\n]*'|\S+)")),
]


def redact(text, counts=None):
    """Return text with credentials replaced. counts, a Counter, gets one per
    finding by type."""
    if not text:
        return text
    counts = counts if counts is not None else Counter()
    for kind, rx in SECRETS:
        def sub(m, kind=kind):
            counts[kind] += 1
            if kind == "password":
                return m.group(0)[: m.start(1) - m.start(0)] + m.group(1) + f"[REDACTED:{kind}]"
            if kind == "aws-secret-key":
                return m.group(1) + f"[REDACTED:{kind}]"
            return f"[REDACTED:{kind}]"
        text = rx.sub(sub, text)
    return text


FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)
INLINE = re.compile(r"(?<!`)`[^`\n]+`(?!`)")
URL = re.compile(r"<(https?://[^>|\s]+)(?:\|[^>]*)?>|https?://[^\s<>\"')\]]+")
LOGLINE = re.compile(
    r"^(?:\s*(?:at [\w$.<>]+\(.*\)|File \".*\", line \d+.*|Traceback \(most recent call last\):"
    r"|\S*(?:Error|Exception)\b[:\s].*"
    r"|\[?\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d.*"
    r"|\d\d:\d\d:\d\d(?:\.\d+)?\s.*"
    r"|(?:E|W|I|D)/\w+.*"
    r"|(?:ERROR|WARN(?:ING)?|INFO|DEBUG|FATAL|TRACE)\b.*"
    r"|#\d+\s+0x[0-9a-f]+.*))\s*$", re.M)


def tag(text):
    """Code, log and link spans in text, as [{"type", "start", "end"}]."""
    spans = []
    if not text:
        return spans
    taken = []

    def free(a, b):
        return all(b <= s or a >= e for s, e in taken)

    for m in FENCE.finditer(text):
        spans.append({"type": "code", "start": m.start(), "end": m.end()})
        taken.append((m.start(), m.end()))
    for m in INLINE.finditer(text):
        if free(m.start(), m.end()):
            spans.append({"type": "code", "start": m.start(), "end": m.end()})
            taken.append((m.start(), m.end()))
    for m in LOGLINE.finditer(text):
        if m.end() > m.start() and free(m.start(), m.end()):
            spans.append({"type": "log", "start": m.start(), "end": m.end()})
            taken.append((m.start(), m.end()))
    for m in URL.finditer(text):
        if free(m.start(), m.end()):
            spans.append({"type": "link", "start": m.start(), "end": m.end(),
                          "url": m.group(1) or m.group(0)})
    spans.sort(key=lambda s: s["start"])
    return spans
