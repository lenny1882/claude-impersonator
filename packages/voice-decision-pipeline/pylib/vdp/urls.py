"""URLs in the corpus (PLAN §2.3).

Every URL whose host is not on PUBLIC_HOSTS becomes `[url]` in the
anonymised copies: API, client and internal hosts, with their paths, never
go out. A URL on a public host stays, so links to documentation are kept;
names inside its path are still replaced like any other text. A subdomain
counts with its host (`docs.github.com` with `github.com`).

Three forms are found: a URL with a scheme (`https://…`, Slack's
`<https://…|label>` included, up to the `|`), a bare host with a known
top-level domain (`api.example.com/v1`), and an IPv4 address. The bare form
needs a lower-case top-level domain from TLDS, not followed by another
`.word`, so file names (`main.dart`, `settings.local.json`, `model.pt`)
and a missing space after a full stop (`done.It`) are not taken for hosts.
"""

import hashlib
import json
import re

PUBLIC_HOSTS = (
    # code and packages
    "github.com", "raw.githubusercontent.com", "pub.dev", "dart.dev", "flutter.dev",
    "npmjs.com", "pypi.org", "python.org", "go.dev", "pkg.go.dev", "nodejs.org",
    "typescriptlang.org", "angular.dev", "angular.io", "jestjs.io", "git-scm.com",
    "semver.org",
    # questions and reference
    "stackoverflow.com", "stackexchange.com", "wikipedia.org", "developer.mozilla.org",
    "w3.org", "whatwg.org", "caniuse.com", "regex101.com", "json-schema.org",
    "swagger.io", "openapis.org",
    # platform documentation
    "developer.apple.com", "apple.com", "developer.android.com", "android.com",
    "docs.aws.amazon.com", "aws.amazon.com", "firebase.google.com", "cloud.google.com",
    "developers.google.com", "learn.microsoft.com",
    # infrastructure
    "docker.com", "hub.docker.com", "kubernetes.io", "terraform.io", "hashicorp.com",
    "serverless.com",
    # commerce and payments
    "shopify.dev", "adyen.com", "docs.adyen.com", "stripe.com",
    # AI
    "anthropic.com", "docs.claude.com",
    # articles and video
    "medium.com", "dev.to", "youtube.com", "youtu.be",
    # this machine
    "localhost", "127.0.0.1",
)

TLDS = ("com", "net", "org", "io", "dev", "app", "ai", "co", "uk", "eu", "de", "fr",
        "es", "nl", "ie", "ca", "au", "nz", "jp", "ch", "se", "dk", "fi", "ly", "gg",
        "tv", "cloud", "tech", "store", "shop", "online", "site", "xyz", "info", "biz")

# Recorded in anon-meta.json: copies built with another list are rebuilt
# before the next batch is drawn.
VERSION = hashlib.sha1(json.dumps([PUBLIC_HOSTS, TLDS]).encode()).hexdigest()[:12]

_PATH = r"[^\s<>\"'`|\\\]\)\}]*"
_SCHEME = re.compile(r"(?i:(?:https?|wss?|ftp)://)[^\s<>\"'`|\\\]\)\}/]+(?:/" + _PATH + r")?")
_BARE = re.compile(
    r"(?<![\w@./:-])(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+(?:"
    + "|".join(sorted(TLDS, key=len, reverse=True))
    + r")(?![\w-])(?!\.[A-Za-z])(?::\d{2,5})?(?:/" + _PATH + r")?")
_IP = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])(?::\d{2,5})?(?:/" + _PATH + r")?")
_TRAIL = ".,;:!?"


def host(url):
    h = re.sub(r"(?i)^[a-z]+://", "", url)
    h = re.split(r"[/?#]", h, 1)[0]
    h = h.rsplit("@", 1)[-1].split(":")[0].lower()
    return h[4:] if h.startswith("www.") else h


def is_public(h):
    return any(h == p or h.endswith("." + p) for p in PUBLIC_HOSTS)


def find(text):
    """[(start, end, host)] for every URL in text, earliest first, no overlaps."""
    found = []
    for rx in (_SCHEME, _BARE, _IP):
        for m in rx.finditer(text or ""):
            a, b = m.span()
            while b > a and text[b - 1] in _TRAIL:
                b -= 1
            if b > a:
                found.append((a, b))
    found.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    out, end = [], -1
    for a, b in found:
        if a >= end:
            out.append((a, b, host(text[a:b])))
            end = b
    return out


def private(text):
    """[(start, end, host)] for the URLs that must not go out."""
    return [u for u in find(text) if not is_public(u[2])]
