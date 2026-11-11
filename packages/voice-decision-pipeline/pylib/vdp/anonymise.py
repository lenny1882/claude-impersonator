"""Anonymised copies of the corpus: anon/<source>.jsonl (PLAN §2.3).

Nothing reaches the API except through these copies. The stored corpus
keeps real names so it stays readable (PLAN §2.2); this pass writes a
parallel copy where every person, client and client product is a stable
role-tagged pseudonym, and records where each replacement sits so the
review page can highlight it.

What is replaced, in order:
  1. Slack mentions <@U…> and channel links <#C…|name>
  2. email addresses ([email]) and phone numbers ([phone])
  3. every name users.json gives each person: full name, display name,
     handle, and first name where no other person shares it and it isn't
     an ordinary word
  4. client names (the candidate list in the inputs) and the client product,
     store and project names James kept on the mining page (PLAN §2.3),
     also inside channel names, repo names and URLs
  5. names spaCy (en_core_web_trf) tags as a person that no list knew; each
     becomes person-NN in the map, so it is replaced the same way everywhere

spaCy's organisation and product tags are not replaced: they become mining
candidates, alongside capitalised terms concentrated in one client's
conversations, for James to keep or strike before the first batch is sent.

Record ids, which carry repo and channel names, become opaque hashes in the
copies; `real_id()` maps them back locally.
"""

import hashlib
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

from . import SCHEMA_VERSION, SOURCES, inputs, state, textutil
from .anonmap import Map

ORDINARY_FIRST_NAMES = {
    "will", "may", "mark", "bill", "jack", "rob", "grace", "hope", "joy", "art",
    "sky", "dean", "frank", "pat", "ray", "rose", "june", "april", "summer", "max",
    "chase", "drew", "lane", "miles", "page", "reed", "rich", "sam", "sue", "victor",
    "faith", "amber", "crystal", "dawn", "eve", "holly", "iris", "ivy", "lily",
    "robin", "sandy", "stone", "wade", "cash", "chip", "gene", "guy", "hunter",
    "jay", "king", "major", "neil", "nick", "ted", "tom", "carol", "don", "ben",
}
SPACY_LABELS_PERSON = {"PERSON"}
SPACY_LABELS_MINE = {"ORG", "PRODUCT"}
MENTION = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>")
CHANNEL = re.compile(r"<#([CGD][A-Z0-9]+)(?:\|([^>]*))?>")
EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<![\w+])(?:\+\d{1,3}[\s-]?|0)\d{2,4}[\s-]?\d{3,4}[\s-]?\d{3,4}(?!\w)")
CAPWORD = re.compile(r"(?<![\w@#/.-])[A-Z][A-Za-z0-9]{2,}(?:[ -][A-Z][A-Za-z0-9]{2,})?")
SENT_FIELDS_NER = ("preceding_reply", "title")


def anon_id(rid):
    return "r" + hashlib.sha1(rid.encode()).hexdigest()[:16]


def real_id_index():
    """anonymised id -> real id, rebuilt from the corpus."""
    idx = {}
    for s in SOURCES:
        for r in state.read_jsonl(state.corpus_file(s)):
            idx[anon_id(r["id"])] = r["id"]
    return idx


def alias_pattern(alias):
    words = re.split(r"[\s\-_.]+", alias.strip())
    words = [re.escape(w) for w in words if w]
    if not words:
        return None
    body = r"[\s\-_.]?".join(words)
    return rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])"


# --- spaCy, cached by text hash so a rerun only tags new text --------------

class Ner:
    def __init__(self):
        self.backend = os.environ.get("VDP_NER", "spacy")
        self.cache_file = state.path("spacy-cache.jsonl")
        self.cache = {}
        for row in state.read_jsonl(self.cache_file):
            self.cache[row["h"]] = row["e"]
        self.nlp = None

    @staticmethod
    def key(text):
        return hashlib.sha1(text.encode()).hexdigest()

    def _load(self):
        if self.nlp is None:
            import spacy
            self.nlp = spacy.load("en_core_web_trf", disable=[
                "tagger", "parser", "attribute_ruler", "lemmatizer"])

    def tag_all(self, texts, log=print):
        """Fill the cache for every text not in it."""
        todo = {}
        for t in texts:
            if t and t.strip():
                h = self.key(t)
                if h not in self.cache:
                    todo[h] = t
        if not todo:
            return
        if self.backend == "none":
            for h in todo:
                self.cache[h] = []
            return
        self._load()
        items = list(todo.items())
        start = time.time()
        with open(self.cache_file, "a", encoding="utf-8") as f:
            os.chmod(self.cache_file, 0o600)
            for n, (h, doc) in enumerate(zip(
                    (h for h, _ in items),
                    self.nlp.pipe((self.blank_code(t) for _, t in items), batch_size=32)), 1):
                ents = [[e.start_char, e.end_char, e.label_] for e in doc.ents
                        if e.label_ in SPACY_LABELS_PERSON | SPACY_LABELS_MINE]
                self.cache[h] = ents
                f.write(json.dumps({"h": h, "e": ents}) + "\n")
                if n % 500 == 0 or n == len(items):
                    f.flush()
                    el = time.time() - start
                    log(f"  ner   {n}/{len(items)} texts, {el/60:.1f} min, "
                        f"about {el/n*(len(items)-n)/60:.0f} min left")

    @staticmethod
    def blank_code(text):
        """Code and log spans blanked to spaces, keeping offsets: spaCy reads
        identifiers in code as names."""
        out = list(text)
        for s in textutil.tag(text):
            if s["type"] in ("code", "log"):
                for i in range(s["start"], s["end"]):
                    if out[i] != "\n":
                        out[i] = " "
        return "".join(out)

    def ents(self, text):
        return self.cache.get(self.key(text), []) if text else []


# --- building the replacement lists ----------------------------------------

def slack_users(d):
    p = os.path.join(d.get("slack_export") or "", "users.json")
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def slack_meta(d):
    from .slack import conversation_meta
    exp = d.get("slack_export")
    return conversation_meta(exp) if exp and os.path.isdir(exp) else {}


class Replacer:
    def __init__(self, d, amap, ner):
        self.d, self.amap, self.ner = d, amap, ner
        self.me = inputs.me(d)
        self.people = {}       # slack id -> entry
        self.ids = {}          # any author id -> entry
        self._people(d)
        self._bitbucket_people()
        self._clients_and_products()
        self._compile()

    def _people(self, d):
        users = slack_users(d)
        meta = slack_meta(d)
        internal = set()
        for c in d.get("conversations", []):
            if inputs.audience(c.get("audience")) not in (None, "clients"):
                internal.update((meta.get(c["id"]) or {}).get("members") or [])
        my_team = next((u.get("team_id") for u in users if u.get("id") == self.me), None)
        firsts = Counter()
        for u in users:
            fn = ((u.get("profile") or {}).get("first_name") or "").strip()
            if fn:
                firsts[fn.lower()] += 1
        for u in users:
            if u.get("is_bot") or u.get("name") == "slackbot":
                continue
            p = u.get("profile") or {}
            if u["id"] == self.me:
                role = "self"
            elif u.get("team_id") == my_team or u["id"] in internal:
                role = "colleague"
            else:
                role = "client-contact"
            aliases = [u.get("real_name"), p.get("real_name"), p.get("display_name")]
            fn, ln = (p.get("first_name") or "").strip(), (p.get("last_name") or "").strip()
            if fn and ln:
                aliases.append(f"{fn} {ln}")
            handle = u.get("name") or ""
            if len(handle) >= 4:
                aliases.append(handle)
            e = self.amap.ensure(u["id"], kind="person", role=role, origin="users.json",
                                 aliases=[a for a in aliases if a and len(a) >= 3])
            e.setdefault("first_names", [])
            if fn and firsts[fn.lower()] == 1 and fn.lower() not in ORDINARY_FIRST_NAMES \
                    and len(fn) >= 3 and fn not in e["first_names"]:
                e["first_names"].append(fn)
                self.amap.dirty = True
            self.people[u["id"]] = e
            self.ids[u["id"]] = e

    def _bitbucket_people(self):
        from .bitbucket import people_file
        people = state.read_json(people_file(), {}) or {}
        idx = self.amap.alias_index()
        for key, p in people.items():
            bid = f"bitbucket:{key}"
            existing = self.amap.get(bid)
            if existing is None:
                match = [e for a in (p.get("display_name"), p.get("nickname")) if a
                         for e in idx.get(a.lower(), []) if e["kind"] == "person"]
                if match:
                    e = match[0]
                    if bid not in e.setdefault("ids", []):
                        e["ids"].append(bid)
                        self.amap.dirty = True
                    self.ids[bid] = e
                    continue
                existing = self.amap.ensure(
                    bid, kind="person", role="colleague", origin="bitbucket",
                    aliases=[p.get("display_name"), p.get("nickname")])
            self.ids[bid] = existing
        for e in self.amap.entries:
            for i in e.get("ids", []):
                self.ids[i] = e

    def _clients_and_products(self):
        names = (self.d.get("anonymiser_additions_candidates") or {}).get("names") or []
        for n in names:
            self.amap.ensure(f"client:{n.lower()}", kind="client", role="client",
                             origin="list", aliases=[n])
        decisions = state.read_json(state.path("mining-decisions.json"), {}) or {}
        for term, dec in sorted(decisions.items()):
            if dec.get("decision") == "keep":
                self.amap.ensure(f"product:{term.lower()}", kind="product", role="product",
                                 origin="mining", aliases=[term])

    def _compile(self):
        multi, single = [], {}
        for e in self.amap.entries:
            if e["kind"] == "person":
                for a in e["aliases"]:
                    multi.append((a, e))
                for fn in e.get("first_names", []):
                    single.setdefault(fn, []).append(e)
        orgs = [(a, e) for e in self.amap.entries if e["kind"] in ("client", "product")
                for a in e["aliases"]]
        # Longest first, so "Jane Smith" wins over "Jane".
        def build(pairs, flags):
            pairs = sorted({(a, id(e)): (a, e) for a, e in pairs}.values(),
                           key=lambda x: -len(x[0]))
            pats, lookup = [], {}
            for a, e in pairs:
                p = alias_pattern(a)
                if p:
                    pats.append(p)
                    lookup[re.sub(r"[\s\-_.]+", "", a.lower())] = e
            if not pats:
                return None, {}
            return re.compile("|".join(f"(?:{p})" for p in pats), flags), lookup
        self.person_rx, self.person_lookup = build(multi, re.I)
        self.org_rx, self.org_lookup = build(orgs, re.I)
        self.first_names = single
        self.first_rx = (re.compile(r"(?<![A-Za-z0-9])(" + "|".join(
            re.escape(f) for f in sorted(single, key=len, reverse=True)) + r")(?![A-Za-z0-9])")
            if single else None)

    @staticmethod
    def norm(s):
        return re.sub(r"[\s\-_.]+", "", s.lower())

    # -- one string --------------------------------------------------------

    def spans(self, text, use_ner):
        """Replacement spans [(start, end, replacement, kind)] for text."""
        found = []

        def add(a, b, rep, kind):
            found.append((a, b, rep, kind))

        for m in MENTION.finditer(text):
            e = self.ids.get(m.group(1))
            add(m.start(), m.end(), "@" + (e["pseudonym"] if e else "person"), "person")
        for m in CHANNEL.finditer(text):
            add(m.start(), m.end(), "#" + self.replace_plain(m.group(2) or "channel"), "channel")
        for m in EMAIL.finditer(text):
            add(m.start(), m.end(), "[email]", "email")
        for m in PHONE.finditer(text):
            if 10 <= sum(ch.isdigit() for ch in m.group(0)) <= 13:
                add(m.start(), m.end(), "[phone]", "phone")
        if self.person_rx:
            for m in self.person_rx.finditer(text):
                e = self.person_lookup.get(self.norm(m.group(0)))
                if e:
                    add(m.start(), m.end(), e["pseudonym"], "person")
        if self.org_rx:
            for m in self.org_rx.finditer(text):
                e = self.org_lookup.get(self.norm(m.group(0)))
                if e:
                    add(m.start(), m.end(), e["pseudonym"], e["kind"])
        if self.first_rx:
            for m in self.first_rx.finditer(text):
                es = self.first_names.get(m.group(1))
                if es and len(es) == 1:
                    add(m.start(), m.end(), es[0]["pseudonym"], "person")
        listed = list(found)
        if use_ner:
            for a, b, label in self.ner.ents(text):
                if label in SPACY_LABELS_PERSON:
                    name = text[a:b].strip()
                    if name and any(c.isalpha() for c in name):
                        # The pseudonym is filled in below, only if no list
                        # span already covers this one, so a name a list
                        # replaced never gets a person-NN entry of its own.
                        add(a, b, None, "person")
        # List spans first, then earliest; at the same start, longest wins;
        # overlaps dropped.
        found.sort(key=lambda x: (x[0], x[2] is None, -(x[1] - x[0])))
        out, end = [], -1
        for s in found:
            if s[0] >= end and not (s[2] is None and any(
                    l[0] < s[1] and s[0] < l[1] for l in listed)):
                if s[2] is None:
                    s = (s[0], s[1], self._spacy_person(text[s[0]:s[1]].strip())["pseudonym"], s[3])
                out.append(s)
                end = s[1]
        return out

    def _spacy_person(self, name):
        """The entry for a name spaCy tagged as a person: a known person
        whose alias it matches, else a person-NN entry of its own."""
        if not hasattr(self, "_person_norm"):
            self._person_norm = {}
            for x in self.amap.entries:
                if x["kind"] == "person":
                    for a in x["aliases"] + x.get("first_names", []):
                        self._person_norm.setdefault(self.norm(a), x)
        k = self.norm(name)
        e = self._person_norm.get(k)
        if e is None:
            e = self.amap.ensure(f"spacy:{k}", kind="person", role="person",
                                 origin="spacy", aliases=[name])
            self._person_norm[k] = e
        return e

    def apply(self, text, use_ner=True):
        """(anonymised text, [{start, end, kind, pseudonym}] in the new text)."""
        if not text:
            return text or "", []
        out, marks, pos = [], [], 0
        n = 0
        for a, b, rep, kind in self.spans(text, use_ner):
            out.append(text[pos:a])
            n += len(text[pos:a])
            marks.append({"start": n, "end": n + len(rep), "kind": kind})
            out.append(rep)
            n += len(rep)
            pos = b
        out.append(text[pos:])
        return "".join(out), marks

    def replace_plain(self, s):
        return self.apply(s, use_ner=False)[0] if isinstance(s, str) else s

    def deep(self, v):
        if isinstance(v, str):
            return self.replace_plain(v)
        if isinstance(v, list):
            return [self.deep(x) for x in v]
        if isinstance(v, dict):
            return {k: self.deep(x) for k, x in v.items()}
        return v

    def author(self, a):
        if not a:
            return None
        e = self.ids.get(a)
        if e:
            return e["pseudonym"]
        if a.startswith("B"):
            return "bot"
        return "person-unknown"


# --- mining ----------------------------------------------------------------

def mine(recs, rep, ner, convs_by_client):
    """Candidate client product/store/project names (PLAN §2.3)."""
    kinds = defaultdict(set)
    count = Counter()
    per_client = defaultdict(Counter)
    lower = Counter()
    examples = defaultdict(list)
    # Names spaCy guessed were people stay candidates: a product name tagged
    # as a person (it happens) should still reach James as a product.
    known = {rep.norm(a) for e in rep.amap.entries if e.get("origin") != "spacy"
             for a in e["aliases"]}
    for r in recs:
        t = r.get("text") or ""
        if not t:
            continue
        for w in re.findall(r"\b[a-z][a-z0-9]{2,}\b", t):
            lower[w] += 1
        client = convs_by_client.get(r["conversation"])
        for a, b, label in ner.ents(t):
            if label in SPACY_LABELS_MINE:
                term = t[a:b].strip()
                if term and rep.norm(term) not in known:
                    kinds[term].add("spacy-" + label.lower())
                    count[term] += 1
                    if len(examples[term]) < 3:
                        examples[term].append(r["id"])
        if client:
            for m in CAPWORD.finditer(t):
                term = m.group(0)
                if rep.norm(term) in known:
                    continue
                per_client[term][client] += 1
                if len(examples[term]) < 3:
                    examples[term].append(r["id"])
    cands = {}
    for term, c in count.items():
        if c >= 2 and lower[term.lower()] < c:
            cands[term] = {"term": term, "kinds": sorted(kinds[term]), "count": c}
    for term, pc in per_client.items():
        total = sum(pc.values())
        top, n = pc.most_common(1)[0]
        if total >= 3 and n / total >= 0.8 and lower[term.lower()] < total:
            c = cands.setdefault(term, {"term": term, "kinds": [], "count": 0})
            c["kinds"] = sorted(set(c["kinds"]) | {"concentrated"})
            c["count"] = max(c["count"], total)
            c["client"] = top
            c["share"] = round(n / total, 2)
    for term, c in cands.items():
        c["examples"] = examples[term]
    return sorted(cands.values(), key=lambda c: (-c["count"], c["term"]))


def conversation_clients(d, recs, rep):
    """conversation -> client code, where a conversation's name or repo
    names a client."""
    out = {}
    names = {}
    for c in d.get("conversations", []):
        names[c["id"]] = c.get("name") or ""
    for r in recs:
        sf = r.get("source_fields") or {}
        n = names.get(r["conversation"]) or sf.get("conversation_name") or sf.get("repo") \
            or sf.get("repo_name") or r["conversation"]
        if rep.org_rx:
            m = rep.org_rx.search(n or "")
            if m:
                e = rep.org_lookup.get(rep.norm(m.group(0)))
                if e and e["kind"] == "client":
                    out[r["conversation"]] = e["pseudonym"]
    return out


# --- the pass --------------------------------------------------------------

def run(log=print):
    d = inputs.load()
    amap = Map.load()
    ner = Ner()
    corpus = {s: list(state.read_jsonl(state.corpus_file(s))) for s in SOURCES}
    allrecs = [r for s in SOURCES for r in corpus[s]]
    if not allrecs:
        raise SystemExit("voice-decision-pipeline: the corpus is empty; run extract first")
    log(f"== anonymise: {len(allrecs)} records")
    texts = []
    for r in allrecs:
        texts.append(r.get("text") or "")
        for k in SENT_FIELDS_NER:
            v = (r.get("source_fields") or {}).get(k)
            if isinstance(v, str):
                texts.append(v)
    ner.tag_all(texts, log=log)
    rep = Replacer(d, amap, ner)
    counts = Counter()
    for s in SOURCES:
        out = []
        for r in corpus[s]:
            text, marks = rep.apply(r.get("text") or "")
            sf = {}
            for k, v in (r.get("source_fields") or {}).items():
                if k in SENT_FIELDS_NER and isinstance(v, str):
                    sf[k] = rep.apply(v)[0]
                elif k in ("slack_ts", "thread_ts"):
                    sf[k] = v
                elif k in ("repo", "cwd"):
                    # Full paths and workspace/repo slugs carry client and
                    # directory names the lists may not know; only the last
                    # part goes, anonymised.
                    if isinstance(v, str) and v:
                        sf.setdefault("repo_name" if k == "repo" else "project",
                                      rep.replace_plain(os.path.basename(v.rstrip("/"))))
                elif k in ("repo_name", "project"):
                    sf[k] = rep.replace_plain(os.path.basename(str(v or "").rstrip("/")))
                else:
                    sf[k] = rep.deep(v)
            for m in marks:
                counts[m["kind"]] += 1
            out.append({
                "id": anon_id(r["id"]),
                "source": r["source"],
                "conversation": anon_id(r["conversation"] or ""),
                "author": rep.author(r.get("author")),
                "audience": r.get("audience"),
                "ts": r.get("ts"),
                "text": text,
                "tags": [t for t in r["tags"] if "start" not in t] + textutil.tag(text),
                "context_ids": [anon_id(x) for x in r.get("context_ids") or []],
                "reactions": [{"name": x["name"], "count": x.get("count", 0),
                               "users": [rep.author(u) for u in x.get("users", [])]}
                              for x in r.get("reactions") or []],
                "source_fields": sf,
                "replacements": marks,
                "schema_version": SCHEMA_VERSION,
            })
        state.write_jsonl(state.anon_file(s), out)
        log(f"  ok    anon/{s}.jsonl: {len(out)} records")
    cands = mine(allrecs, rep, ner, conversation_clients(d, allrecs, rep))
    old = {c["term"]: c for c in state.read_json(state.path("mining-candidates.json"), []) or []}
    for c in cands:
        old[c["term"]] = c
    state.write_json(state.path("mining-candidates.json"),
                     sorted(old.values(), key=lambda c: (-c["count"], c["term"])))
    amap.save()
    decisions = state.read_json(state.path("mining-decisions.json"), {}) or {}
    state.write_json(state.path("anon-meta.json"), {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "decisions_hash": hashlib.sha1(json.dumps(decisions, sort_keys=True).encode()).hexdigest(),
        "map_entries": len(amap.entries),
        "replacements": dict(counts),
    })
    undecided = sum(1 for c in old.values() if c["term"] not in decisions)
    log(f"  ok    {sum(counts.values())} replacements {dict(counts)}; "
        f"{len(amap.entries)} map entries; {undecided} mining candidates undecided")
    return counts
