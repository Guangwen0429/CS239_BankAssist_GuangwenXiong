"""Build a single self-contained HTML page that shows every trace as a swim-lane timeline.

Called by run_scenarios; writes traces/viewer.html.  Open it in any browser
(no server needed) to step through a scenario during a demo.
"""

from __future__ import annotations

import json

LANES = ["User", "ConciergeAgent", "AuthAgent", "RiskAgent", "AccountAgent"]

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BankAssist Traces</title>
<style>
:root{--bg:#fafaf9;--fg:#1c1917;--mut:#78716c;--line:#e7e5e4;--card:#fff;
--user:#0f766e;--concierge:#4338ca;--auth:#b45309;--risk:#be123c;--account:#15803d;--bad:#dc2626;--ok:#16a34a}
@media (prefers-color-scheme:dark){:root{--bg:#1c1917;--fg:#f5f5f4;--mut:#a8a29e;--line:#44403c;--card:#292524;
--user:#2dd4bf;--concierge:#a5b4fc;--auth:#fbbf24;--risk:#fb7185;--account:#4ade80}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
header{padding:16px 20px;border-bottom:1px solid var(--line)}h1{font-size:18px;margin:0 0 4px}
.sub{color:var(--mut)}nav{display:flex;flex-wrap:wrap;gap:6px;padding:12px 20px}
nav button{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:6px;padding:6px 10px;cursor:pointer;font:inherit}
nav button.on{outline:2px solid var(--concierge)}nav .bad{color:var(--bad)}nav .ok{color:var(--ok)}
main{padding:0 20px 40px}.meta{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin-bottom:12px}
.controls{display:flex;gap:8px;align-items:center;margin:8px 0 12px}.controls button{font:inherit;padding:4px 10px}
.grid{display:grid;grid-template-columns:repeat(5,minmax(150px,1fr));gap:0;overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--card)}
.head{position:sticky;top:0;background:var(--card);font-weight:600;padding:8px;border-bottom:1px solid var(--line);font-size:13px}
.cell{padding:4px 6px;border-top:1px dashed var(--line);min-height:8px}
.ev{border-left:3px solid currentColor;padding:4px 6px;border-radius:4px;background:color-mix(in srgb,currentColor 8%,transparent);font-size:12.5px;word-break:break-word}
.ev .k{font-weight:600;text-transform:uppercase;font-size:10.5px;letter-spacing:.04em;opacity:.85}
.ev code{font-size:11.5px;color:var(--fg)}.ev .t{color:var(--fg)}
.hidden{display:none}.User{color:var(--user)}.ConciergeAgent{color:var(--concierge)}.AuthAgent{color:var(--auth)}
.RiskAgent{color:var(--risk)}.AccountAgent{color:var(--account)}
@media (max-width:700px){header,nav,main{padding-left:16px;padding-right:16px}}
</style></head><body>
<header><h1>BankAssist: Phase 1 traces</h1>
<div class="sub">Each row is one trace event. Columns are agents. Arrows mark inter-agent messages. PINs are masked.</div></header>
<nav id="nav"></nav><main id="main"></main>
<script>
const LANES=__LANES__;const TRACES=__TRACES__;
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const j=o=>esc(JSON.stringify(o));
function body(e){switch(e.kind){
 case'user_input':return `<span class="t">“${esc(e.content)}”</span>`;
 case'thought':return `<i class="t">${esc(e.content)}</i>`;
 case'action':return `<code>${esc(e.tool)}(${j(e.args)})</code>`;
 case'observation':return `<code>${esc(e.tool)} → ${j(e.result)}</code>`;
 case'message':return `→ <b>${esc(e.to)}</b> [${esc(e.performative)}]<br><code>${j(e.payload)}</code>`;
 case'response':return `<span class="t">“${esc(e.content)}”</span>`;}return j(e)}
let cur=0,shown=0;
function render(i){cur=i;const t=TRACES[i];document.querySelectorAll('nav button').forEach((b,k)=>b.classList.toggle('on',k===i));
 const m=t.meta||{};let h=`<div class="meta"><b>${esc(t.title)}</b><br>${esc(t.description)}<br><span class="sub">Policies: ${esc(m.policies||'')} · Concierge mode: ${esc(m.concierge_mode||'')}</span><br><b>Expected:</b> ${esc(m.expected||'')}<br><b>Phase 1 result:</b> ${esc(m.phase1_result||'')}</div>`;
 h+=`<div class="controls"><button id="step">Next step ▸</button><button id="all">Show all</button><span class="sub" id="cnt"></span></div><div class="grid">`;
 h+=LANES.map(l=>`<div class="head ${l}">${l}</div>`).join('');
 t.events.forEach((e,n)=>{const col=LANES.indexOf(e.agent);LANES.forEach((l,c)=>{h+=`<div class="cell r${n}">${c===col?`<div class="ev ${l}"><div class="k">${e.step}. ${e.kind}</div>${body(e)}</div>`:''}</div>`})});
 h+='</div>';document.getElementById('main').innerHTML=h;shown=t.events.length;upd();
 document.getElementById('step').onclick=()=>{if(shown>=t.events.length)shown=0;shown++;upd()};
 document.getElementById('all').onclick=()=>{shown=t.events.length;upd()}}
function upd(){const t=TRACES[cur];t.events.forEach((e,n)=>document.querySelectorAll('.r'+n).forEach(c=>c.classList.toggle('hidden',n>=shown)));
 document.getElementById('cnt').textContent=`${shown} / ${t.events.length} events`}
document.getElementById('nav').innerHTML=TRACES.map((t,i)=>`<button class="${/VIOLATION/.test((t.meta||{}).phase1_result||'')?'bad':'ok'}">${i+1}. ${esc(t.scenario_id)}</button>`).join('');
document.querySelectorAll('nav button').forEach((b,i)=>b.onclick=()=>render(i));render(0);
</script></body></html>
"""


def build_viewer(traces: list[dict]) -> str:
    data = json.dumps(traces, ensure_ascii=False).replace("</", "<\\/")
    return _PAGE.replace("__LANES__", json.dumps(LANES)).replace("__TRACES__", data)

