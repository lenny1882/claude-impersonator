"""The anonymising map: anonymising-map.json (PLAN §2.2, §2.3).

One append-only file. Each entry holds a real id, every alias seen, its
kind (person, client, product), role, pseudonym and origin (users.json, a
list, spacy, mining, bitbucket). A counter per role means a pseudonym number
is never reused or renumbered, and `forget` keeps a person's entry so
mentions of them in other people's messages are still replaced and their
number never passes to someone else (James, 11 Nov 2026).

Pseudonyms carry a role tag: colleague-07, client-contact-02, client-03,
product-04, person-05 (a name spaCy found that no list knew), and self-01
for James (James, 11 Nov 2026: role-tagged pseudonyms, one per person across
every source).
"""

from . import SCHEMA_VERSION, state

ROLES = ("self", "colleague", "client-contact", "person", "client", "product")


def file():
    return state.path("anonymising-map.json")


class Map:
    def __init__(self, data=None):
        data = data or {}
        self.counters = dict(data.get("counters") or {})
        self.entries = list(data.get("entries") or [])
        self.by_id = {e["real_id"]: e for e in self.entries}
        self.dirty = False

    @classmethod
    def load(cls):
        return cls(state.read_json(file()))

    def save(self):
        if self.dirty:
            state.write_json(file(), {"schema_version": SCHEMA_VERSION,
                                      "counters": self.counters, "entries": self.entries})
            self.dirty = False

    def get(self, real_id):
        return self.by_id.get(real_id)

    def ensure(self, real_id, *, kind, role, origin, aliases=()):
        """The entry for real_id, created with the next number for its role
        if new. Aliases are added, never removed."""
        e = self.by_id.get(real_id)
        if e is None:
            if role not in ROLES:
                raise ValueError(f"unknown role {role}")
            n = self.counters.get(role, 0) + 1
            self.counters[role] = n
            e = {"real_id": real_id, "aliases": [], "kind": kind, "role": role,
                 "pseudonym": f"{role}-{n:02d}", "origin": origin}
            self.entries.append(e)
            self.by_id[real_id] = e
            self.dirty = True
        for a in aliases:
            a = (a or "").strip()
            if a and a not in e["aliases"]:
                e["aliases"].append(a)
                self.dirty = True
        return e

    def alias_index(self):
        """lower-case alias -> list of entries carrying it."""
        idx = {}
        for e in self.entries:
            for a in e["aliases"]:
                idx.setdefault(a.lower(), []).append(e)
        return idx
