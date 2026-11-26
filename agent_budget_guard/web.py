"""Local aggregate usage dashboard backed by the Codex usage ledger."""

from datetime import datetime, timezone
from html import escape
from pathlib import Path
import sqlite3

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from agent_budget_guard.budget import (
    DEFAULT_CONFIG_FILE,
    calculate_token_budget_status,
    load_monthly_budget,
    monthly_token_usage,
)
from agent_budget_guard.codex_reader import (
    DEFAULT_CODEX_SESSIONS,
    DEFAULT_IMPORT_DB,
    import_codex_usage,
    load_codex_usage_daily,
    load_codex_usage_totals,
)
from agent_budget_guard.dashboard import total_tokens


def _dashboard_data(database: Path, config_file: Path) -> dict:
    totals, event_count = load_codex_usage_totals(database)
    input_total, cached_total, output_total = total_tokens(totals)
    today = datetime.now(timezone.utc).date()
    daily = load_codex_usage_daily(database, limit=7, end_date=today)
    if not event_count:
        daily = [] if daily is not None else None
    elif daily is not None:
        daily = list(reversed(daily))
    budget = load_monthly_budget(config_file)
    budget_data = None
    if budget is not None:
        budget_data = calculate_token_budget_status(monthly_token_usage(database), budget)
    return {
        "refreshed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "records": event_count,
        "tokens": {"input": input_total, "cached_input": cached_total, "output": output_total},
        "budget": budget_data,
        "daily": [
            {"date": day, "input": inputs, "cached_input": cached, "output": outputs, "records": count}
            for day, inputs, cached, outputs, count in (daily or [])
        ],
        "daily_available": daily is not None,
    }


def create_app(
    database: Path = DEFAULT_IMPORT_DB,
    config_file: Path = DEFAULT_CONFIG_FILE,
    sessions_dir: Path = DEFAULT_CODEX_SESSIONS,
) -> FastAPI:
    """Create a local dashboard app with explicit data paths."""
    app = FastAPI(title="Agent Budget Guard", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> HTMLResponse:
        return HTMLResponse(_PAGE)

    @app.get("/api/dashboard")
    def dashboard_data() -> JSONResponse:
        """Return safe aggregate data only; never expose ledger rows."""
        return JSONResponse(_dashboard_data(database, config_file))

    @app.post("/api/sync")
    def sync_codex_usage() -> JSONResponse:
        """Run the existing deduplicating importer on explicit user request."""
        try:
            _totals, record_count, imported = import_codex_usage(sessions_dir, database)
            return JSONResponse({
                "ok": True,
                "imported": imported,
                "records": record_count,
                "dashboard": _dashboard_data(database, config_file),
            })
        except (OSError, ValueError, sqlite3.Error) as error:
            return JSONResponse({"ok": False, "message": str(error)}, status_code=500)

    return app


_PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark"><title>Agent Budget Guard</title><style>
:root{color-scheme:dark;--bg:#08111f;--panel:#101d30;--panel2:#13243a;--line:#22344d;--text:#e8f0fb;--muted:#8fa3bd;--blue:#5b9cff;--teal:#42d6bd;--yellow:#f5bd54;--red:#ff737f}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(ellipse at 12% -10%,#16345a 0,transparent 38%),var(--bg);color:var(--text);font:15px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
.shell{max-width:1160px;margin:auto;padding:38px 28px 56px}.top{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:28px}.brand{display:flex;align-items:center;gap:15px}.mark{width:48px;height:48px;border-radius:15px;display:grid;place-items:center;background:linear-gradient(145deg,#2870d5,#23b9b1);box-shadow:0 8px 30px #1673bd44;font-size:21px;font-weight:800}.eyebrow,.hint,.sub{color:var(--muted)}.eyebrow{text-transform:uppercase;letter-spacing:.13em;font-weight:700;font-size:11px}.title{font-size:clamp(24px,4vw,32px);letter-spacing:-.04em;margin:1px 0 0}.actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.local{display:flex;align-items:center;gap:8px;border:1px solid var(--line);border-radius:999px;padding:8px 12px;color:#b9c9dc;font-size:13px}.dot{width:7px;height:7px;border-radius:50%;background:var(--teal);box-shadow:0 0 12px #42d6bd99}.button{border:1px solid #315071;background:#142944;color:var(--text);padding:10px 14px;border-radius:11px;font:600 13px inherit;cursor:pointer;transition:transform .18s,border-color .18s,background .18s}.button:hover{transform:translateY(-1px);border-color:#5b9cff;background:#193454}.button.primary{background:#2665ba;border-color:#347cdd}.button:disabled{opacity:.55;cursor:wait;transform:none}.statusline{min-height:26px;color:var(--muted);font-size:12px;margin:-14px 0 18px;text-align:right}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.card{background:linear-gradient(155deg,#122138,#0e1a2b);border:1px solid var(--line);border-radius:17px;padding:21px;box-shadow:0 12px 32px #0002;transition:transform .2s,border-color .2s}.card:hover{transform:translateY(-2px);border-color:#365477}.metric-card{min-height:144px;position:relative;overflow:hidden}.metric-card:after{content:"";position:absolute;width:100px;height:100px;border-radius:50%;right:-42px;top:-48px;background:var(--glow);filter:blur(3px);opacity:.15}.label{color:#a9bad0;font-size:13px;font-weight:600}.metric{font-size:clamp(27px,4vw,36px);font-weight:750;letter-spacing:-.045em;margin-top:12px;font-variant-numeric:tabular-nums}.metric-note{color:var(--muted);font-size:12px;margin-top:3px}.accent-blue{--glow:var(--blue)}.accent-teal{--glow:var(--teal)}.accent-violet{--glow:#9b8cff}
.section{margin-top:18px}.section-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:19px}.section h2{font-size:16px;margin:0 0 3px;letter-spacing:-.01em}.hint{font-size:12px}.budget-top{display:flex;justify-content:space-between;gap:16px;align-items:flex-end;margin:15px 0 12px}.budget-main{font-size:22px;font-weight:720;font-variant-numeric:tabular-nums}.budget-pct{font-size:14px;font-weight:700}.track{height:11px;background:#091321;border:1px solid #263950;border-radius:20px;overflow:hidden}.fill{height:100%;width:0;border-radius:inherit;background:linear-gradient(90deg,#388cf3,#48d1bc);transition:width .55s ease}.budget.warning .fill{background:linear-gradient(90deg,#f5bd54,#f49d4a)}.budget.exceeded .fill{background:linear-gradient(90deg,#ff737f,#e9516b)}.budget.warning .budget-pct{color:var(--yellow)}.budget.exceeded .budget-pct{color:var(--red)}.budget-foot{display:flex;justify-content:space-between;margin-top:10px;color:var(--muted);font-size:12px}.badge{border-radius:999px;padding:5px 9px;font-size:11px;font-weight:700;background:#12372f;color:var(--teal)}.warning .badge{background:#403119;color:var(--yellow)}.exceeded .badge{background:#421e2b;color:var(--red)}
.chart{padding-bottom:18px}.legend{display:flex;gap:16px;color:#b3c2d5;font-size:12px}.legend span{display:flex;align-items:center;gap:7px}.swatch{width:8px;height:8px;border-radius:50%;background:var(--blue)}.swatch.out{background:var(--teal)}.days{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:10px;margin-top:20px}.day{min-width:0;background:#0a1626;border:1px solid #1c3047;border-radius:12px;padding:12px 10px;transition:border-color .18s}.day:hover{border-color:#426488}.day-date{font-size:11px;color:#aabbd0;font-weight:650;white-space:nowrap}.bars{height:132px;display:flex;align-items:flex-end;justify-content:center;gap:7px;padding:12px 0 9px;border-bottom:1px solid #25374e}.bar{width:min(22px,34%);height:var(--h);min-height:0;border-radius:5px 5px 2px 2px;transition:height .45s ease,filter .18s}.bar:hover{filter:brightness(1.35)}.bar.input{background:linear-gradient(180deg,#68acff,#3579d6)}.bar.output{background:linear-gradient(180deg,#5ee2ca,#1d9c91)}.day-values{display:grid;gap:3px;margin-top:8px;font-size:10px;color:#91a5be;font-variant-numeric:tabular-nums}.day-values b{color:#d9e5f4;font-weight:650}.empty{grid-column:1/-1;padding:32px 12px;text-align:center;color:var(--muted);border:1px dashed #2a405b;border-radius:12px}.notice{padding:14px 16px;border-radius:12px;background:#17253a;color:#bdcbe0;border:1px solid var(--line)}.notice strong{color:var(--text)}.error{color:#ff929a}
@media(max-width:760px){.shell{padding:27px 18px 40px}.top{align-items:flex-start}.grid{gap:11px}.card{padding:18px}.days{gap:7px}.day{padding:10px 6px}.bars{height:116px;gap:5px}}
@media(max-width:560px){.shell{padding:20px 14px 32px}.top{display:block}.brand{margin-bottom:16px}.actions{justify-content:flex-start}.statusline{text-align:left;margin:6px 0 12px}.grid{grid-template-columns:1fr 1fr}.metric-card{min-height:126px;padding:15px}.metric-card:last-child{grid-column:1/-1;min-height:110px}.metric{font-size:27px;margin-top:8px}.section{margin-top:13px}.budget-top{align-items:flex-start;flex-direction:column;gap:4px}.days{grid-template-columns:repeat(7,minmax(67px,1fr));overflow-x:auto;padding-bottom:5px}.day-date{font-size:10px}.bars{height:98px}.chart{overflow:hidden}.legend{font-size:11px}.budget-foot{gap:10px}.budget-foot span:last-child{text-align:right}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;transition:none!important}}
</style></head><body><main class="shell">
<header class="top"><div class="brand"><div class="mark" aria-hidden="true">A</div><div><div class="eyebrow">Usage dashboard</div><h1 class="title">Agent Budget Guard</h1></div></div><div class="actions"><span class="local"><i class="dot"></i>Local usage</span><button class="button" id="refresh">↻ &nbsp;Refresh</button><button class="button primary" id="sync">Sync Codex usage</button></div></header>
<div class="statusline" id="updated" aria-live="polite">Loading usage…</div><div id="app" aria-live="polite"></div>
</main><script>
const app=document.getElementById('app'), updated=document.getElementById('updated'), refresh=document.getElementById('refresh'), sync=document.getElementById('sync');
const fmt=n=>Number(n||0).toLocaleString();
function render(d){const t=d.tokens||{}, b=d.budget;let out=`<div class="grid"><section class="card metric-card accent-blue"><div class="label">Input tokens</div><div class="metric">${fmt(t.input)}</div><div class="metric-note">Across ${fmt(d.records)} recorded events</div></section><section class="card metric-card accent-teal"><div class="label">Cached input tokens</div><div class="metric">${fmt(t.cached_input)}</div><div class="metric-note">Included in input usage</div></section><section class="card metric-card accent-violet"><div class="label">Output tokens</div><div class="metric">${fmt(t.output)}</div><div class="metric-note">Generated by Codex</div></section></div>`;
if(b){const state=b.exceeded?'exceeded':b.warning?'warning':'normal', label=b.exceeded?'Budget exceeded':b.warning?'Approaching budget':'Within budget', width=Math.max(0,Math.min(100,b.percentage));out+=`<section class="card section budget ${state}"><div class="section-head"><div><h2>Monthly token budget</h2><div class="hint">Current UTC month · input + output tokens</div></div><span class="badge">${label}</span></div><div class="budget-top"><div class="budget-main">${fmt(b.used)} <span class="hint">/ ${fmt(b.budget)} tokens</span></div><div class="budget-pct">${Number(b.percentage).toFixed(1)}%</div></div><div class="track" role="progressbar" aria-label="Monthly token budget" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.min(100,b.percentage)}"><div class="fill" style="width:${width}%"></div></div><div class="budget-foot"><span>${fmt(b.remaining)} tokens remaining</span><span>${label}</span></div></section>`}else{out+=`<section class="card section"><div class="section-head"><div><h2>Monthly token budget</h2><div class="hint">Set a local token budget to track this month’s usage.</div></div></div></section>`}
out+=`<section class="card section chart"><div class="section-head"><div><h2>Daily usage</h2><div class="hint">Last 7 UTC dates · each series scaled independently</div></div><div class="legend"><span><i class="swatch"></i>Input</span><span><i class="swatch out"></i>Output</span></div></div>`;
if(!d.records)out+=`<div class="empty">No usage recorded yet. Use <strong>Sync Codex usage</strong> to import local usage.</div>`;else if(!d.daily_available)out+=`<div class="empty">Daily breakdown is unavailable because this ledger has no event timestamps.</div>`;else if(!d.daily?.length||!d.daily.some(x=>x.input||x.output))out+=`<div class="empty">No usage in the last 7 UTC dates.</div>`;else{const mi=Math.max(1,...d.daily.map(x=>x.input)),mo=Math.max(1,...d.daily.map(x=>x.output));out+='<div class="days">'+d.daily.map(x=>{const ih=x.input?Math.max(7,x.input/mi*100):0,oh=x.output?Math.max(7,x.output/mo*100):0;return `<div class="day"><div class="day-date">${x.date.slice(5)}</div><div class="bars" aria-label="${x.date}: ${fmt(x.input)} input, ${fmt(x.output)} output"><div class="bar input" style="--h:${ih}%" title="${fmt(x.input)} input tokens"></div><div class="bar output" style="--h:${oh}%" title="${fmt(x.output)} output tokens"></div></div><div class="day-values"><span>In <b>${fmt(x.input)}</b></span><span>Out <b>${fmt(x.output)}</b></span></div></div>`}).join('')+'</div>'}out+='</section>';if(!d.records)out=`<div class="notice" style="margin-top:16px">No usage recorded yet. Sync Codex usage to read your local session usage.</div>`+out;app.innerHTML=out;updated.textContent='Last refreshed '+new Date(d.refreshed_at).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'})+' · local ledger'}
async function load(){refresh.disabled=true;try{const r=await fetch('/api/dashboard',{cache:'no-store'});if(!r.ok)throw Error('Could not refresh dashboard data.');render(await r.json())}catch(e){updated.innerHTML='<span class="error">'+e.message+'</span>'}finally{refresh.disabled=false}}
refresh.addEventListener('click',load);sync.addEventListener('click',async()=>{sync.disabled=true;sync.textContent='Syncing…';updated.textContent='Reading local Codex sessions…';try{const r=await fetch('/api/sync',{method:'POST'}),data=await r.json();if(!r.ok||!data.ok)throw Error(data.message||'Codex usage sync failed.');render(data.dashboard);updated.textContent=`Sync complete · ${fmt(data.imported)} new record${data.imported===1?'':'s'} · last refreshed `+new Date(data.dashboard.refreshed_at).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'})}catch(e){updated.innerHTML='<span class="error">'+e.message+'</span>'}finally{sync.disabled=false;sync.textContent='Sync Codex usage'}});load();
</script></body></html>'''
