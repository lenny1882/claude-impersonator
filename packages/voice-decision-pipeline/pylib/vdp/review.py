"""The local review page: `voice-decision-pipeline review` (PLAN §2.3).

Two jobs, both James's, both before anything is sent:
  - mining: keep or strike each candidate client product, store or project
    name. Kept terms join the replacement list at the next `anonymise`.
  - batches: read 50 anonymised items from one source, every replacement
    highlighted, and approve or reject the batch; stop a source once
    satisfied.

Served on 127.0.0.1 only, from this machine's state; real text appears on
the mining page because the page never leaves the machine. Every click is
written straight to state, so closing the tab loses nothing.
"""

import html
import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import SOURCES, batches, state
from .record import flags

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1c1a;--muted:#6b6862;--line:#e3e0d8;--card:#fff;
--mark:#ffe08a;--markfg:#1d1c1a;--ok:#1f7a3a;--bad:#a12a2a;--accent:#2f5d9b}
@media (prefers-color-scheme:dark){:root{--bg:#1a1a18;--fg:#ecebe6;--muted:#a19d94;
--line:#34332f;--card:#22211f;--mark:#6b5410;--markfg:#fff3cf;--ok:#5fc27e;--bad:#e07a7a;--accent:#8fb3e8}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 system-ui,sans-serif}main{max-width:980px;margin:0 auto;padding:16px}
a{color:var(--accent)}h1{font-size:22px;margin:8px 0 16px}h2{font-size:17px;margin:20px 0 8px}
table{width:100%;border-collapse:collapse}td,th{border-bottom:1px solid var(--line);
padding:6px 8px;text-align:left;vertical-align:top}th{color:var(--muted);font-weight:600}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;margin:10px 0}
.meta{color:var(--muted);font-size:13px}pre{white-space:pre-wrap;word-break:break-word;
margin:6px 0;font:14px/1.45 ui-monospace,monospace}mark{background:var(--mark);color:var(--markfg);
border-radius:3px;padding:0 2px}button{font:inherit;padding:5px 12px;border-radius:6px;
border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer}
button.keep[aria-pressed=true]{background:var(--ok);color:#fff}
button.strike[aria-pressed=true]{background:var(--bad);color:#fff}
details{margin-top:6px}.err{color:var(--bad)}textarea{width:100%;font:inherit}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
"""

JS = """
async function post(url, body){const r=await fetch(url,{method:'POST',
headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
const t=await r.text();if(!r.ok){alert(t);throw t}return t}
function mark(btn,term,d){post('/api/mining',{[term]:d}).then(()=>{
for(const b of btn.parentElement.querySelectorAll('button'))b.setAttribute('aria-pressed',
b.dataset.d===d?'true':'false');const left=document.getElementById('left');
if(left)left.textContent=document.querySelectorAll('tr[data-term]').length-
document.querySelectorAll('tr[data-term] button[aria-pressed=true]').length})}
function bulk(d){const body={};for(const tr of document.querySelectorAll('tr[data-term]')){
if(!tr.querySelector('button[aria-pressed=true]'))body[tr.dataset.term]=d}
if(!Object.keys(body).length)return;if(!confirm(Object.keys(body).length+' undecided terms will be marked '+d))return;
post('/api/mining',body).then(()=>location.reload())}
"""


def page(title, body):
    return (f"<!doctype html><html lang=en><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style><script>{JS}</script>"
            f"<main><p class=meta><a href='/'>Review home</a></p><h1>{html.escape(title)}</h1>"
            f"{body}</main></html>")


def highlighted(text, marks):
    out, pos = [], 0
    for m in sorted(marks or [], key=lambda m: m["start"]):
        out.append(html.escape(text[pos:m["start"]]))
        out.append(f"<mark title='{html.escape(m['kind'])}'>"
                   f"{html.escape(text[m['start']:m['end']])}</mark>")
        pos = m["end"]
    out.append(html.escape(text[pos:]))
    return "".join(out)


def home():
    rv = batches.load_review()
    rows = []
    for s in SOURCES:
        recs = list(state.read_jsonl(state.anon_file(s)))
        items = sum(1 for r in recs if "item" in flags(r))
        st = rv[s]
        open_ = [b["name"] for b in st["batches"] if b["status"] == "open"]
        rows.append(
            f"<tr><td><a href='/batch?source={s}'>{s}</a></td><td>{len(recs)}</td><td>{items}</td>"
            f"<td>{st['approved']}</td><td>{'stopped' if st['stopped'] else (open_[0] if open_ else '—')}</td>"
            f"<td>{'yes' if batches.sendable(s) else 'no'}</td></tr>")
    cands = state.read_json(state.path("mining-candidates.json"), []) or []
    dec = state.read_json(state.path("mining-decisions.json"), {}) or {}
    left = sum(1 for c in cands if c["term"] not in dec)
    gates = batches.gates()
    g = ("".join(f"<li class=err>{html.escape(x)}</li>" for x in gates)
         if gates else "<li>none: batches can be drawn</li>")
    return page("Corpus review", f"""
<h2>Mining: client product, store and project names</h2>
<p><a href='/mining'>{len(cands)} candidates</a>, {left} undecided.</p>
<h2>What blocks the next batch</h2><ul>{g}</ul>
<h2>Sources</h2>
<table><tr><th>Source</th><th>Records</th><th>Items</th><th>Approved batches</th>
<th>Open batch</th><th>May be sent</th></tr>{''.join(rows)}</table>""")


def mining():
    cands = state.read_json(state.path("mining-candidates.json"), []) or []
    dec = state.read_json(state.path("mining-decisions.json"), {}) or {}
    real = {}
    for s in SOURCES:
        for r in state.read_jsonl(state.corpus_file(s)):
            real[r["id"]] = r.get("text") or ""
    rows = []
    for c in cands:
        d = (dec.get(c["term"]) or {}).get("decision")
        ex = []
        for i in c.get("examples", [])[:2]:
            t = real.get(i, "")
            k = t.find(c["term"])
            snip = t[max(0, k - 80):k + len(c["term"]) + 80] if k >= 0 else t[:160]
            ex.append(html.escape(snip).replace(html.escape(c["term"]),
                                                f"<mark>{html.escape(c['term'])}</mark>"))
        t = html.escape(c["term"])
        rows.append(
            f"<tr data-term='{t}'><td><b>{t}</b><div class=meta>{', '.join(c.get('kinds', []))}"
            f"{' · ' + html.escape(c['client']) + ' ' + str(int(c.get('share', 0) * 100)) + '%' if c.get('client') else ''}"
            f" · {c['count']}×</div>{''.join(f'<pre>{x}</pre>' for x in ex)}</td>"
            f"<td class=row><button class=keep data-d=keep aria-pressed={'true' if d == 'keep' else 'false'} "
            f"onclick=\"mark(this,this.closest('tr').dataset.term,'keep')\">Keep</button>"
            f"<button class=strike data-d=strike aria-pressed={'true' if d == 'strike' else 'false'} "
            f"onclick=\"mark(this,this.closest('tr').dataset.term,'strike')\">Strike</button></td></tr>")
    left = sum(1 for c in cands if c["term"] not in dec)
    return page("Mining candidates", f"""
<p>Keep a term to add it to the replacement list: it then becomes product-NN everywhere.
Strike it to leave it as written. <span id=left>{left}</span> undecided. Each click is saved.</p>
<p class=row><button onclick="bulk('strike')">Strike every undecided term</button>
<button onclick="bulk('keep')">Keep every undecided term</button></p>
<table><tr><th>Term, where it was found, two examples</th><th></th></tr>{''.join(rows)}</table>""")


def batch_page(source):
    rv = batches.load_review()
    st = rv.get(source)
    if st is None:
        return page("Unknown source", "<p>No such source.</p>")
    open_ = [b for b in st["batches"] if b["status"] == "open"]
    done = "".join(f"<li>{b['name']}: {b['status']}{(' — ' + html.escape(b.get('note') or '')) if b.get('note') else ''}</li>"
                   for b in st["batches"] if b["status"] != "open")
    if not open_:
        gates = batches.gates()
        g = "".join(f"<li class=err>{html.escape(x)}</li>" for x in gates)
        stop = (f"<button onclick=\"if(confirm('Stop reviewing {source}? No more batches will be drawn for it.'))"
                f"post('/api/stop',{{source:'{source}'}}).then(()=>location.reload())\">Stop reviewing {source}</button>"
                if st["approved"] and not st["stopped"] else "")
        draw = ("" if st["stopped"] or gates else
                f"<button onclick=\"post('/api/draw',{{source:'{source}'}}).then(()=>location.reload())\">"
                f"Draw the next batch of {batches.BATCH_SIZE}</button>")
        return page(f"{source}: review batches", f"""
<p>{st['approved']} approved{'; stopped' if st['stopped'] else ''}.</p>
<ul>{done}</ul>{('<ul>' + g + '</ul>') if g else ''}<p class=row>{draw} {stop}</p>""")
    b = state.read_json(state.path("batches", f"{open_[0]['name']}.json"))
    cards = []
    for n, it in enumerate(b["items"], 1):
        r = it["item"]
        ctx = "".join(
            f"<div class=meta>{html.escape(c.get('author') or '')} · {html.escape(c.get('ts') or '')}</div>"
            f"<pre>{highlighted(c['text'], c.get('replacements'))}</pre>" for c in it["context"])
        sf = r.get("source_fields") or {}
        extra = ""
        for k in ("title", "conversation_name", "project", "preceding_reply"):
            if isinstance(sf.get(k), str) and sf[k]:
                extra += f"<div class=meta>{k}</div><pre>{html.escape(sf[k][:1500])}</pre>"
        cards.append(
            f"<div class=card><div class=meta>{n}. {html.escape(r.get('author') or '')} · "
            f"{html.escape(r.get('audience') or 'no audience')} · {html.escape(r.get('ts') or '')} · "
            f"{', '.join(sorted(flags(r)))}</div>"
            f"<pre>{highlighted(r['text'], r.get('replacements'))}</pre>{extra}"
            f"{('<details><summary>Context (' + str(len(it['context'])) + ')</summary>' + ctx + '</details>') if ctx else ''}</div>")
    name = b["name"]
    return page(f"{name}: {len(b['items'])} anonymised items", f"""
<p>Highlighted text is what replaced a name, email, phone number, client or product.
Read for anything still identifying. Approving the first batch lets {source} be sent.</p>
{''.join(cards)}
<h2>Decision</h2><textarea id=note rows=3 placeholder='What was wrong, if rejecting'></textarea>
<p class=row><button onclick="post('/api/decide',{{name:'{name}',status:'approved',note:document.getElementById('note').value}}).then(()=>location.reload())">Approve {name}</button>
<button onclick="post('/api/decide',{{name:'{name}',status:'rejected',note:document.getElementById('note').value}}).then(()=>location.reload())">Reject {name}</button></p>""")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, fmt, *args):
        print("  http  " + fmt % args, flush=True)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/":
                return self._send(200, home())
            if u.path == "/mining":
                return self._send(200, mining())
            if u.path == "/batch":
                return self._send(200, batch_page((q.get("source") or [""])[0]))
            return self._send(404, page("Not found", ""))
        except SystemExit as e:
            return self._send(400, page("Error", f"<p class=err>{html.escape(str(e))}</p>"))

    def do_POST(self):
        if self.headers.get("Origin") not in (None, f"http://{self.headers.get('Host')}"):
            return self._send(403, "cross-origin request refused", "text/plain")
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            p = urlparse(self.path).path
            if p == "/api/mining":
                dec = state.read_json(state.path("mining-decisions.json"), {}) or {}
                for term, d in body.items():
                    if d not in ("keep", "strike"):
                        raise ValueError(d)
                    dec[term] = {"decision": d}
                state.write_json(state.path("mining-decisions.json"), dec)
            elif p == "/api/draw":
                batches.draw(body["source"])
            elif p == "/api/decide":
                batches.decide(body["name"], body["status"], body.get("note", ""))
            elif p == "/api/stop":
                batches.stop(body["source"])
            else:
                return self._send(404, "no such endpoint", "text/plain")
            return self._send(200, "ok", "text/plain")
        except SystemExit as e:
            return self._send(409, str(e), "text/plain")
        except (ValueError, KeyError) as e:
            return self._send(400, f"bad request: {e}", "text/plain")


def serve(port=8765, open_browser=True):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"  ok    review page at {url} (Ctrl-C to stop)", flush=True)
    if open_browser and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
