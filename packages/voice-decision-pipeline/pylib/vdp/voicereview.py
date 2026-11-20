"""The voice build's review pages, on the same local review server as the
Stage 1 pages (PLAN §3.4, §3.7).

  /voice              where the voice build stands, and the rules file
  /voice/labels       the owner's label-check sample: right or wrong, corrected
  /voice/disagree     the sample of second-model disagreements, graded
  /voice/pairs        the blind pairs: pick, then grade the draft 1 to 5
  /voice/judge        the judge's worst 20 and 10 random drafts, graded
  /voice/report       the validation counts, spotting rate and pass

Every answer is written to the state as it is given. Text shown is the
anonymised copy, the same text that was sent.
"""

import hashlib
import html
import json
import re

from . import guide, labels, state, validate, voice, voicebuild

E = html.escape

JS = """
function vpost(url,body){return post(url,body)}
function lc(id,verdict){const tr=document.getElementById('i-'+id);
const ps=[...tr.querySelectorAll('input[type=checkbox]:checked')].map(x=>x.value);
vpost('/api/voice/label-check',{id,verdict,purposes:verdict==='wrong'?ps:[]}).then(()=>{
tr.dataset.v=verdict;for(const b of tr.querySelectorAll('button.v'))b.setAttribute('aria-pressed',b.dataset.v===verdict?'true':'false')})}
function dg(id,pick){const tr=document.getElementById('i-'+id);
const ps=[...tr.querySelectorAll('input[type=checkbox]:checked')].map(x=>x.value);
vpost('/api/voice/disagree',{id,pick,purposes:pick==='neither'?ps:[]}).then(()=>{
for(const b of tr.querySelectorAll('button.v'))b.setAttribute('aria-pressed',b.dataset.v===pick?'true':'false')})}
function vdone(c){const have=(c.dataset.have||'').split(' ');return (c.dataset.need||'').split(' ').every(k=>!k||have.includes(k))}
function vhave(c,k){const h=new Set((c.dataset.have||'').split(' ').filter(Boolean));h.add(k);c.dataset.have=[...h].join(' ');vcount()}
let VT='';
function vcards(){return [...document.querySelectorAll('.card[data-aud]')]}
function vcount(){const cs=vcards();for(const el of document.querySelectorAll('[data-left]')){const a=el.dataset.left;
el.textContent=cs.filter(c=>(!a||c.dataset.aud===a)&&!vdone(c)).length}}
function vtab(a){VT=a;for(const c of vcards())c.hidden=!!a&&c.dataset.aud!==a;
for(const b of document.querySelectorAll('.tab[data-tab]'))b.classList.toggle('on',b.dataset.tab===a);
history.replaceState(null,'','#'+(a||'all'));window.scrollTo(0,0);vcount()}
function vnext(){const cs=vcards().filter(c=>!c.hidden&&!vdone(c));if(!cs.length)return;
const below=cs.find(c=>c.getBoundingClientRect().top>80);(below||cs[0]).scrollIntoView({behavior:'smooth',block:'start'})}
window.addEventListener('DOMContentLoaded',()=>{if(!vcards().length)return;const h=location.hash.slice(1);vtab(h&&h!=='all'?h:'')});
function pick(pair,p){vpost('/api/voice/pair',{pair,pick:p}).then(t=>{const c=document.getElementById('c-'+pair);vhave(c,'pick');
const r=JSON.parse(t);c.querySelector('.reveal').textContent=r.real==='A'?'A was yours; B is the draft.':'B was yours; A is the draft.';
c.querySelector('.grade').hidden=false;for(const b of c.querySelectorAll('button.p'))b.setAttribute('aria-pressed',b.dataset.p===p?'true':'false')})}
function grade(kind,ref,g){vpost('/api/voice/'+kind,{ref,grade:g}).then(()=>{const c=document.getElementById('c-'+ref);vhave(c,'grade');
for(const b of c.querySelectorAll('button.g'))b.setAttribute('aria-pressed',b.dataset.g==String(g)?'true':'false')})}
"""


TIP_CSS = "<style>.pl{text-decoration:underline dotted;text-underline-offset:2px;cursor:help}</style>"


def _page(title, body):
    from .review import page
    return page(title, f"{TIP_CSS}<script>{JS}</script><p class=meta><a href='/voice'>Voice build</a></p>" + body)


shown = voice.shown


def grade_text(n):
    """A grade's meaning on the judge's scale, worded for the owner."""
    return validate.GRADES[n].replace("self-01's", "your").replace("self-01", "you")


def scale():
    """The 1-5 scale the judge uses, for the owner's grades to mean the same."""
    return "<ul class=meta>" + "".join(f"<li><b>{n}</b>: {E(grade_text(n))}</li>" for n in (5, 4, 3, 2, 1)) + "</ul>"


def grade_title(n):
    return E(f"{n}: {grade_text(n)}", quote=True)


def reveal(real):
    """Which side was the owner's, shown once they have picked (as the pick's own
    reply shows it), so a reload keeps it."""
    return "A was yours; B is the draft." if real == "A" else "B was yours; A is the draft." if real == "B" else ""


def voice_nav(items):
    """Tabs for All and each audience, each with how many are left, and a
    button to the next one not yet answered: the Mining page's pattern."""
    auds = [a for a in voice.CORPUS_AUDIENCES if any(x == a for x in items)]
    tabs = [("", "All")] + [(a, a) for a in auds]
    return ("<nav class=tabs>" + "".join(
        f"<button class=tab data-tab='{a}' onclick=\"vtab('{a}')\">{E(label)} <span class=n data-left='{a}'></span></button>"
        for a, label in tabs) + "<button onclick=\"vnext()\">Next unanswered ↓</button></nav>")


def plabels(ps):
    """Purpose names, comma-separated, each showing its definition on hover."""
    return ", ".join(f"<span class=pl title='{E(labels.purpose_tip(p), quote=True)}'>{E(p)}</span>"
                     if p in voice.PURPOSES else E(p) for p in ps)


def boxes(chosen):
    return "".join(f"<label class=meta><input type=checkbox value={p}{' checked' if p in chosen else ''}> {p}</label> "
                   for p in voice.PURPOSES)


def ctx_block(it):
    before = voice.render_context(it["before"], 2500)
    after = voice.render_context(it["after"], 800, keep="start")
    return ((f"<details><summary class=meta>before</summary><pre>{E(before)}</pre></details>" if before else "")
            + f"<pre><b>{E(it['text'])}</b></pre>"
            + (f"<details><summary class=meta>after</summary><pre>{E(after)}</pre></details>" if after else ""))


def home_section():
    s = labels.summary()
    c = s["check"]
    r = validate.report()
    gates = voicebuild.gates()
    return (f"<h2>Voice model</h2><p><a href='/voice'>{s['labelled']} items labelled, "
            f"{s['second']} by the second model</a>; label check "
            + ("not drawn" if not c.get("drawn") else f"{c['answered']}/{c['size']}, {c['wrong']} wrong")
            + f"; validation {r.get('answered', 0)}/{r.get('pairs', 0)} pairs answered. "
            + ("Ready to publish." if not gates else "Publish waits on: " + E("; ".join(gates)) + ".")
            + "</p>")


def overview():
    s = labels.summary()
    c = s["check"]
    g = labels.disagree_result()
    rates = s["rates"]
    rrows = "".join(f"<tr><td>{plabels([p])}</td><td>{v['either']}</td><td>{v['differ']}</td><td>{int(v['rate'] * 100)}%</td></tr>"
                    for p, v in sorted(rates.items(), key=lambda x: -x[1]["rate"]))
    mine, jira = guide.own_rules()
    bt, _ = voicebuild.newest()
    return _page("Voice build", f"""
<h2>Labels</h2><p>{s['labelled']} labelled by the labeller, {s['second']} by the second model,
{s['disagreements']} disagreements. Prompt {labels.prompt_version()}.</p>
<p><a href='/voice/labels'>Label check</a>: """ + (
        "not drawn yet: it is drawn after the first labelling pass." if not c.get("drawn") else
        f"round {c['round']}, {c['answered']} of {c['size']} answered, {c['wrong']} wrong "
        f"({'passed' if c['passed'] else 'over 6 wrong fails' if c['done'] else 'in progress'}).") + f"""</p>
<p><a href='/voice/disagree'>Disagreements</a>: """ + (
        f"round {g['round']}, {g['answered']} of {g['size']} graded." if g.get("drawn") else
        "not drawn yet: it is drawn once both passes have labelled.") + f"""</p>
<table><tr><th>Purpose</th><th>Either model</th><th>Only one</th><th>Rate</th></tr>{rrows}</table>
<h2>Your rules</h2><p>{len(mine)} rules and {len(jira)} Jira rules in <code>{E(guide.rules_file())}</code>,
copied word for word as the guide's first section at each build.</p>
<h2>Validation</h2><p>Best exemplar count so far: {validate.best_count() or '—'}.
<a href='/voice/pairs'>Blind pairs</a> · <a href='/voice/judge'>Judge review</a> ·
<a href='/voice/report'>Report</a></p>
<h2>Build</h2><p>Newest build: {bt or 'none'}. Publish waits on:
{E('; '.join(voicebuild.gates())) or 'nothing'}.</p>""")


def labels_page():
    d = labels.draw_sample()
    items = {it["id"]: it for it in voice.load()}
    lab = labels.read("labeller")
    rows = []
    for i in d["ids"]:
        it = items.get(i)
        if not it:
            continue
        a = d["answers"].get(i, {})
        got = lab.get(i, {}).get("purposes", [])
        v = a.get("verdict", "")
        rows.append(f"<tr id='i-{i}'><td><div class=meta>{E(it['audience'])}</div>{ctx_block(it)}"
                    f"<div>labels: <b>{plabels(got)}</b></div>"
                    f"<details><summary class=meta>correct it</summary>{boxes(a.get('purposes') or got)}</details></td>"
                    f"<td class=act><button class='v keep' data-v=right aria-pressed={'true' if v == 'right' else 'false'} "
                    f"onclick=\"lc('{i}','right')\">Right</button><button class='v strike' data-v=wrong "
                    f"aria-pressed={'true' if v == 'wrong' else 'false'} onclick=\"lc('{i}','wrong')\">Wrong</button></td></tr>")
    c = labels.check_result()
    return _page("Label check", f"""<p>Round {d['round']}: {c['answered']} of {c['size']} answered,
{c['wrong']} wrong. More than 6 wrong of 120 fails: the labelling prompt is changed and the pass rerun,
then a fresh sample is drawn. Mark a label set wrong if any purpose is missing, extra or out of
order; tick the right ones under "correct it" first, and the correction is used in place of the
labeller's. Each click is saved.</p><table>{''.join(rows)}</table>""")


def sides(i):
    """(model on A, model on B) for a disagreement: a coin toss seeded by the
    item's id. An item keeps its sides across loads; across the sample each
    model lands on A about half the time. Grades are saved by
    model name, so the sides never reach the answers."""
    swap = hashlib.sha1(f"disagree-sides:{i}".encode()).digest()[0] & 1
    return ("second", "labeller") if swap else ("labeller", "second")


def disagree_page():
    labels.write_disagreements()
    g = state.read_json(labels.disagree_grades_file(), {}) or {}
    ds = {x["id"]: x for x in state.read_jsonl(state.path("labels", "disagreements.jsonl"))}
    items = {it["id"]: it for it in voice.load()}
    rows = []
    for i in g.get("ids", []):
        it, x = items.get(i), ds.get(i)
        if not it or not x:
            continue
        a = g["answers"].get(i, {})
        pk = a.get("pick", "")
        btn = lambda v, label: (f"<button class=v data-v={v} aria-pressed={'true' if pk == v else 'false'} "
                                f"onclick=\"dg('{i}','{v}')\">{label}</button>")
        sa, sb = sides(i)
        rows.append(f"<tr id='i-{i}'><td><div class=meta>{E(it['audience'])}</div>{ctx_block(it)}"
                    f"<div>A: <b>{plabels(x[sa])}</b> · B: <b>{plabels(x[sb])}</b></div>"
                    f"<details><summary class=meta>neither: the right labels</summary>{boxes(a.get('purposes') or [])}</details></td>"
                    f"<td class=act>{btn(sa, 'A right')}{btn(sb, 'B right')}{btn('neither', 'Neither')}</td></tr>")
    return _page("Second-model disagreements", f"""<p>Round {g.get('round', 1)}: a sample of {len(g.get('ids', []))} items
where the two models' labels differ. Each item puts the models on A and B by a coin toss.
<code>voice label --new-sample</code> draws a fresh sample from the current disagreements.
Every disagreement is in
<code>labels/disagreements.jsonl</code>.</p>
<table>{''.join(rows)}</table>""")


def pairs_page():
    pr = state.read_json(validate.pairs_file(), None)
    if not pr:
        return _page("Blind pairs", "<p>No pairs yet: run <code>voice-decision-pipeline voice pairs</code> after "
                                    "<code>voice validate</code>.</p>")
    ans = validate.answers(pr["run"])
    key = state.read_json(validate.key_file(), {}) or {}
    cards = []
    for p in validate.active(pr):
        a = ans.get(p["pair"], {})
        pk, gr = a.get("pick", ""), a.get("grade")
        pb = lambda v, label: (f"<button class=p data-p={v} aria-pressed={'true' if pk == v else 'false'} "
                               f"onclick=\"pick('{p['pair']}','{v}')\">{label}</button>")
        gb = "".join(f"<button class=g data-g={n} aria-pressed={'true' if gr == n else 'false'} "
                     f"title='{grade_title(n)}' onclick=\"grade('pair-grade','{p['pair']}',{n})\">{n}</button>" for n in range(1, 6))
        have = " ".join(k for k, v in (("pick", pk), ("grade", gr)) if v)
        cards.append(f"<div class=card id='c-{p['pair']}' data-aud='{E(p['audience'])}' data-need='pick grade' "
                     f"data-have='{have}'><div class=meta>{p['pair']} · {E(p['audience'])} · "
                     f"{plabels(p['purposes'])}</div>"
                     f"<details><summary class=meta>conversation before</summary><pre>{E(p['context'])}</pre></details>"
                     f"<p><b>A</b></p><pre>{E(shown(p['a']))}</pre><p><b>B</b></p><pre>{E(shown(p['b']))}</pre>"
                     f"<p class=row>{pb('A', 'A is mine')}{pb('B', 'B is mine')}{pb('cant', 'Can’t tell')}</p>"
                     f"<p class=meta><span class=reveal>{reveal(key.get(p['pair'])) if pk else ''}</span></p>"
                     f"<p class='row grade'{'' if pk else ' hidden'}>Would you send the draft as is? {gb}</p></div>")
    return _page("Blind pairs", f"""<p>Run {pr['run']}, {len(validate.active(pr))} pairs, drafts made with
{pr['k']} exemplars. In each, one message is yours and one a draft. Pick yours, or "can't tell";
then grade the draft 1 to 5, on the scale the judge uses (each button shows its meaning on hover):</p>
{scale()}<p>Every answer is saved as you give it, so you can stop and come back; a new grade
replaces the old one. The number on each tab is how many are left there.</p>
{voice_nav([p['audience'] for p in validate.active(pr)])}{''.join(cards)}""")


def judge_page():
    jr = validate.judge_review()
    ans = validate.answers(jr["run"], kind="judge-review")
    cards = []
    for x in jr["items"]:
        gr = ans.get(x["id"], {}).get("grade")
        gb = "".join(f"<button class=g data-g={n} aria-pressed={'true' if gr == n else 'false'} "
                     f"title='{grade_title(n)}' onclick=\"grade('judge-review','{x['id']}',{n})\">{n}</button>" for n in range(1, 6))
        cards.append(f"<div class=card id='c-{x['id']}' data-aud='{E(x['audience'])}' data-need='grade' "
                     f"data-have='{'grade' if gr else ''}'><div class=meta>{x['why']} · {E(x['audience'])} · "
                     f"judge {x['score']}: {E(x['reason'])}</div>"
                     f"<details><summary class=meta>conversation before</summary><pre>{E(x['context'])}</pre></details>"
                     f"<p><b>Yours</b></p><pre>{E(shown(x['real']))}</pre><p><b>Draft</b></p><pre>{E(shown(x['draft']))}</pre>"
                     f"<p class=row>Your grade for the draft: {gb}</p></div>")
    return _page("Judge review", f"""<p>The judge's {validate.WORST} worst-scored drafts and
{validate.RANDOM} random others from run {jr['run']}, each beside your real message. Your grade
shows where the judge and you differ, on the judge's own scale (each button shows its meaning on
hover):</p>{scale()}{voice_nav([x['audience'] for x in jr['items']])}{''.join(cards)}""")


def report_page():
    r = validate.report()
    if not r.get("pairs"):
        return _page("Validation report", "<p>No pairs yet.</p>")
    rows = "".join(f"<tr><td>{E(k)}</td><td>{v.get('right', 0)}</td><td>{v.get('wrong', 0)}</td>"
                   f"<td>{v.get('cant', 0)}</td></tr>" for k, v in sorted(r["counts"].items()))
    sp = r["spotting"]
    pr = state.read_json(validate.pairs_file(), {}) or {}
    byp = {p["pair"]: p for p in pr.get("pairs", [])}
    key = state.read_json(validate.key_file(), {}) or {}
    right = "".join(
        f"<div class=card><div class=meta>{pid} · {E(byp[pid]['audience'])}</div><div class=row>"
        f"<pre style='flex:1'>{E(byp[pid]['a'])}</pre><pre style='flex:1'>{E(byp[pid]['b'])}</pre></div>"
        f"<div class=meta>yours: {key.get(pid)}</div></div>" for pid in r["right_pairs"] if pid in byp)
    more = ", ".join(r["more_pairs_for"])
    return _page("Validation report", f"""
<p>Run {r['run']}: {r['answered']} of {r['pairs']} pairs answered, {r['graded']} graded.
{'<b>Passed.</b>' if r['passed'] else '<b>Not passed yet.</b>'}
Blind test {'within' if r['blind_ok'] else 'over'} the bar (right minus wrong at most 10% of pairs);
grades {'meet' if r['grades_ok'] else 'miss'} the bar (80% at 4 or higher, none at 1).
{f'More pairs needed for {E(more)}: run <code>voice pairs --more &lt;audience&gt;</code>.' if more else ''}</p>
<p>You spot drafts in {sp['estimate'] if sp['estimate'] is not None else '—'} of pairs beyond chance
(95% range {sp['low']} to {sp['high']}); confidence the pass holds on a fresh test:
{int(r['confidence_pass_holds'] * 100)}%, worked out from your answers alone.</p>
<p>Grades: {E(json.dumps(r['grades']))}</p>
<table><tr><th>Group</th><th>Right</th><th>Wrong</th><th>Can't tell</th></tr>{rows}</table>
<h2>Pairs you got right</h2>{right or '<p class=meta>none</p>'}""")


def get(path):
    pages = {"/voice": overview, "/voice/labels": labels_page, "/voice/disagree": disagree_page,
             "/voice/pairs": pairs_page, "/voice/judge": judge_page, "/voice/report": report_page}
    f = pages.get(path)
    return f() if f else None


def post(path, body):
    """The response text for a voice POST, or None if the path isn't one."""
    if path == "/api/voice/label-check":
        d = labels.draw_sample()
        i = body["id"]
        if i not in d["ids"] or body["verdict"] not in ("right", "wrong"):
            raise ValueError("not in the sample")
        ps = [p for p in body.get("purposes") or [] if p in voice.PURPOSES]
        d["answers"][i] = {"verdict": body["verdict"], "purposes": ps if body["verdict"] == "wrong" else []}
        state.write_json(labels.check_file(), d)
        return "ok"
    if path == "/api/voice/disagree":
        g = state.read_json(labels.disagree_grades_file(), {}) or {}
        i = body["id"]
        if i not in g.get("ids", []) or body["pick"] not in ("labeller", "second", "neither"):
            raise ValueError("not in the sample")
        ps = [p for p in body.get("purposes") or [] if p in voice.PURPOSES]
        if body["pick"] != "neither":
            x = {r["id"]: r for r in state.read_jsonl(state.path("labels", "disagreements.jsonl"))}.get(i, {})
            ps = x.get(body["pick"], [])
        g["answers"][i] = {"pick": body["pick"], "purposes": ps}
        state.write_json(labels.disagree_grades_file(), g)
        return "ok"
    if path == "/api/voice/pair":
        pr = state.read_json(validate.pairs_file(), {}) or {}
        p = {x["pair"]: x for x in pr.get("pairs", [])}.get(body["pair"])
        if not p or body["pick"] not in ("A", "B", "cant"):
            raise ValueError("unknown pair or pick")
        validate.answer("pair", p["pair"], pick=body["pick"], audience=p["audience"], purposes=p["purposes"])
        return json.dumps({"real": (state.read_json(validate.key_file(), {}) or {}).get(p["pair"])})
    if path in ("/api/voice/pair-grade", "/api/voice/judge-review"):
        g = int(body["grade"])
        if not 1 <= g <= 5:
            raise ValueError("grade 1 to 5")
        kind = "pair" if path.endswith("pair-grade") else "judge-review"
        if kind == "pair":
            pr = state.read_json(validate.pairs_file(), {}) or {}
            p = {x["pair"]: x for x in pr.get("pairs", [])}.get(body["ref"])
            if not p or "pick" not in validate.answers().get(p["pair"], {}):
                raise ValueError("pick first, then grade")
            validate.answer("pair", p["pair"], grade=g, audience=p["audience"], purposes=p["purposes"])
        else:
            validate.answer("judge-review", body["ref"], grade=g)
        return "ok"
    return None
