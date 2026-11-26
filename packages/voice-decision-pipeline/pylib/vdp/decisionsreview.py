"""Decision extraction's review pages (PLAN §4.9), on the same local review
server as the Stage 1 and voice pages, under /decisions:

  /decisions           where extraction stands: passes, samples, catch rate
  /decisions/prompt    the prompt both passes read, with its approval
  /decisions/disagree  the sample of the passes' disagreements, graded
  /decisions/check     the case check: right or wrong

Every answer is written to the state as it is given. Text shown is the
anonymised copy, the same text that was sent.
"""

import hashlib
import html

from . import decisions, state
from .voicereview import JS

E = html.escape


def _page(title, body):
    from .review import page
    return page(title, f"<script>{JS}</script><p class=meta><a href='/decisions'>Decision extraction</a></p>" + body)


def home_section():
    st = decisions.status()
    c = st["check"]
    return (f"<h2>Decision model</h2><p><a href='/decisions'>Decision extraction</a>: "
            f"<a href='/decisions/prompt'>prompt</a> {st['prompt']} "
            + ("approved" if st["approved"] else "<b>not approved</b>")
            + f"; read by the first pass {st['first']} units, by the second {st['second']}; case check "
            + ("not drawn" if not c.get("drawn") else f"{c['answered']}/{c['size']}, {c['wrong']} wrong")
            + ".</p>")


def decisions_prompt_page():
    p = decisions.shown_prompt()
    ok = decisions.approved()
    kinds = "".join(f"<tr><td><b>{E(k)}</b></td><td>{E(v)}</td></tr>" for k, v in p["kinds"].items())
    return _page("Decision extraction prompt", f"""
<p>Prompt {p['version']}: <b>{'approved' if ok else 'not approved'}</b>. Nothing is sent for decision
extraction until it is approved. Any change to it, its kinds, its fields or the two models
(settings.json's <code>decisions</code> section and the <code>extract_first</code> and
<code>extract_second</code> models) makes a new version that needs approving again.</p>
<h2>The kinds</h2><table>{kinds}</table>
<h2>The prompt both passes read</h2><pre>{E(p['system'])}</pre>
<h2>Each stretch</h2><pre>{E(p['unit'])}</pre><h2>After the stretches</h2><pre>{E(p['end'])}</pre>
<h2>The fixed answers</h2><p>ending: {E(', '.join(p['endings']))}<br>origin: {E(', '.join(p['origins']))}<br>
decided_by: {E(', '.join(p['decided_by']))}<br>outcome: {E(', '.join(p['outcomes']))}</p>
<p>{'' if ok else "<button onclick=" + chr(34) + "if(confirm('Approve this prompt for decision extraction?'))vpost('/api/decisions/approve',{version:'" + p['version'] + "'}).then(()=>location.reload())" + chr(34) + ">Approve this prompt</button>"}</p>""")


def source_nav():
    """Tabs for All and each source, with how many are left: voice_nav's
    pattern, by source instead of audience."""
    tabs = [("", "All")] + [(x, x) for x in ("slack", "bitbucket", "transcripts", "gsd")]
    return ("<nav class=tabs>" + "".join(
        f"<button class=tab data-tab='{a}' onclick=\"vtab('{a}')\">{E(label)} <span class=n data-left='{a}'></span></button>"
        for a, label in tabs) + "<button onclick=\"vnext()\">Next unanswered ↓</button></nav>")


def case_block(c):
    rows = [("question", c["question"]), ("options offered", "; ".join(c["options_offered"])),
            ("options added", "; ".join(c["options_added"])), ("Claude recommended first", c["recommended_first"]),
            ("Claude recommended last", c["recommended_last"]), ("ending", c["ending"]), ("choice", c["choice"]),
            ("origin", c["origin"]), ("decided by", c["decided_by"] + (f" ({c['from']})" if c["from"] else "")),
            ("reason", c["reason"] + (" (inferred)" if c["reason_inferred"] else "")), ("kind", c["kind"]),
            ("outcome", c["outcome"] + (f": {c['outcome_ref']}" if c["outcome_ref"] else "")), ("quote", c["quote"])]
    return "<table>" + "".join(f"<tr><td class=meta>{E(k)}</td><td>{E(v)}</td></tr>" for k, v in rows if v) + "</table>"


def unit_block(u):
    if not u:
        return "<p class=meta>(the unit isn't in the saved units; run decisions extract again)</p>"
    return (f"<details><summary class=meta>{E(u['source'])}{', ' + E(u['project']) if u['project'] else ''}: "
            f"what the passes read</summary><pre>{E(u['text'])}</pre></details>")


def decisions_page():
    st = decisions.status()
    c = st["check"]
    k = st["catch"] or {}
    return _page("Decision extraction", f"""
<p><a href='/decisions/prompt'>Prompt</a> {st['prompt']}: {'approved' if st['approved'] else '<b>not approved</b>'}.</p>
<p>Read by the first pass: {st['first']} units; by the second: {st['second']}.
Disagreements: {st['disagreements'] if st['disagreements'] is not None else '—'}.</p>
<p><a href='/decisions/disagree'>Disagreements to grade</a> ·
<a href='/decisions/check'>Case check</a>: """ + (
        "not drawn yet: it is drawn once both passes have read every unit." if not c.get("drawn") else
        f"round {c['round']}, {c['answered']} of {c['size']} answered, {c['wrong']} wrong "
        f"({'passed' if c['passed'] else f'over {decisions.CHECK_MAX_WRONG} wrong fails' if c['failed'] else 'in progress'}).")
        + f"""</p><p>Catch rate: {E(k.get('state', 'not measured'))}""" + (
        f": about {int(k['estimate'] * 100)}% of decisions caught; {int(k['sure_at_least'] * 100)}% sure it is at "
        f"least {int(decisions.CATCH_BAR * 100)}% ({k['missed']} decisions in {k['read']} sampled units, step "
        f"{k['step']})" if "estimate" in k else "") + ".</p>")


def decisions_check_page():
    d = state.read_json(decisions.check_file(), None) or {}
    if not d.get("ids"):
        return _page("Case check", "<p>Not drawn yet: it is drawn once both passes have read every unit.</p>")
    us = decisions.saved_units()
    cards = []
    for ref in d["ids"]:
        cs = decisions.case(ref)
        u = us.get(ref.rsplit("#", 1)[0])
        v = d["answers"].get(ref)
        cards.append(f"<div class=card data-aud='{E((u or {}).get('source', ''))}' data-need='v' data-have='{'v' if v else ''}'>"
                     f"{case_block(cs) if cs else '<p class=meta>(gone)</p>'}{unit_block(u)}<div class=row>"
                     + "".join(f"<button class=v data-v={x} aria-pressed={'true' if v == x else 'false'} "
                               f"onclick=\"dck(this,'{ref}','{x}')\">{lab}</button>"
                               for x, lab in (("right", "Holds the decision as made"), ("wrong", "Wrong")))
                     + "</div></div>")
    r = decisions.check_result()
    return _page("Case check", f"""<script>function dck(el,ref,v){{vpost('/api/decisions/check',{{ref,verdict:v}}).then(()=>{{
const c=el.closest('.card');for(const b of c.querySelectorAll('button.v'))b.setAttribute('aria-pressed',b.dataset.v===v?'true':'false');vhave(c,'v')}})}}</script>
<p>Round {r['round']}: {r['answered']} of {r['size']} answered, {r['wrong']} wrong; more than
{decisions.CHECK_MAX_WRONG} wrong fails, and then the prompt is changed and both passes read again.
Mark each case right if it holds the decision as it was made: the question, the options, the choice,
whose it was, the kind and the outcome. Open "what the passes read" to see the stretch.</p>
{source_nav()}
{''.join(cards)}""")


def decisions_disagree_page():
    d = state.read_json(decisions.grades_file(), None) or {}
    if not d.get("ids"):
        return _page("Disagreements", "<p>Not drawn yet: it is drawn once both passes have read every unit.</p>")
    f, s = decisions.read_pass("first"), decisions.read_pass("second")
    us = decisions.saved_units()
    by = {x["unit"]: x for x in decisions.disagreements()}
    cards = []
    for u in d["ids"]:
        pick = (d["answers"].get(u) or {}).get("pick")
        sides = {"A": "first", "B": "second"} if int(hashlib.sha1(u.encode()).hexdigest(), 16) % 2 else {"A": "second", "B": "first"}
        cols = "".join(f"<div style='flex:1'><div class=meta>{side}</div>"
                       + ("".join(case_block(c) for c in (f if p == "first" else s).get(u, {}).get("decisions", []))
                          or "<p class=meta>no decision</p>") + "</div>" for side, p in sides.items())
        cards.append(f"<div class=card data-aud='{E((us.get(u) or {}).get('source', ''))}' data-need='v' data-have='{'v' if pick else ''}'>"
                     f"<div class=meta>they differ on: {E(', '.join((by.get(u) or {}).get('fields', [])))}</div>"
                     f"{unit_block(us.get(u))}<div class=row>{cols}</div><div class=row>"
                     + "".join(f"<button class=v data-v={p} aria-pressed={'true' if pick == p else 'false'} "
                               f"onclick=\"ddg(this,'{u}','{p}')\">{lab}</button>"
                               for p, lab in ((sides["A"], "A is right"), (sides["B"], "B is right"), ("neither", "Neither")))
                     + "</div></div>")
    return _page("Disagreements", f"""<script>function ddg(el,unit,p){{vpost('/api/decisions/disagree',{{unit,pick:p}}).then(()=>{{
const c=el.closest('.card');for(const b of c.querySelectorAll('button.v'))b.setAttribute('aria-pressed',b.dataset.v===p?'true':'false');vhave(c,'v')}})}}</script>
<p>Round {d['round']}: {sum(1 for x in d['ids'] if x in d['answers'])} of {len(d['ids'])} graded. The two passes
read the same stretch and gave different short answers. Pick the side that holds the decisions as made,
or Neither: a unit graded Neither is left out until it is read again. Which model is which side is
drawn per unit.</p>
{source_nav()}
{''.join(cards)}""")


def get(path):
    pages = {"/decisions": decisions_page, "/decisions/prompt": decisions_prompt_page,
             "/decisions/check": decisions_check_page, "/decisions/disagree": decisions_disagree_page}
    f = pages.get(path)
    return f() if f else None


def post(path, body):
    """The response text for a decisions POST, or None if the path isn't one."""
    if path == "/api/decisions/check":
        d = state.read_json(decisions.check_file(), None) or {}
        if body.get("ref") not in d.get("ids", []) or body.get("verdict") not in ("right", "wrong"):
            raise ValueError("not in the case check")
        d["answers"][body["ref"]] = body["verdict"]
        state.write_json(decisions.check_file(), d)
        return "ok"
    if path == "/api/decisions/disagree":
        d = state.read_json(decisions.grades_file(), None) or {}
        if body.get("unit") not in d.get("ids", []) or body.get("pick") not in ("first", "second", "neither"):
            raise ValueError("not in the disagreement sample")
        d["answers"][body["unit"]] = {"pick": body["pick"]}
        state.write_json(decisions.grades_file(), d)
        return "ok"
    if path == "/api/decisions/approve":
        if body.get("version") != decisions.prompt_version():
            raise ValueError("the prompt changed since the page was drawn; reload it")
        decisions.approve()
        return "ok"
    return None
