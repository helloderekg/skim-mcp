"""skim live token meter - a real-time window showing what skim is saving you.

Run it alongside a Claude session that has skim mounted:

    uv run skim-meter                 # opens http://127.0.0.1:17321
    uv run skim-meter --once          # print a one-shot text snapshot (no server)
    uv run skim-meter --port 12345 --log /path/to/skim_calls.jsonl

It tails the same `skim_calls.jsonl` the MCP server appends to on every call and shows, updating
each second:
  * tokens IN  - what reading those files / running those commands in FULL would have cost
  * tokens OUT - what skim actually put into the model's context (skeletons + every expand/search)
  * % saved    - 1 - out/in, the honest net (expands eat into it; if you expand everything it shrinks)

Pure stdlib (http.server + json). No network, no external deps. Binds to localhost only.
"""
from __future__ import annotations
import argparse
import datetime
import json
import os
import shutil
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Port chosen via secrets.randbelow in the safe 10001-29999 band (avoids service defaults + OS
# reserved/ephemeral ranges); override with --port or SKIM_METER_PORT.
_DEFAULT_PORT = int(os.environ.get("SKIM_METER_PORT") or 17321)

# Calls that represent a real "full read" baseline (they log full_tokens = what you'd have paid).
_BASELINE_CALLS = {"skim_open", "skim_run", "skim_repo"}


def _default_log() -> str:
    # Same resolution as the server (shared logpath module), so the pair always agree.
    from .logpath import default_log_path
    return default_log_path()


def _short(s: str, n: int = 44) -> str:
    s = str(s or "")
    return s if len(s) <= n else s[: n - 1] + "…"


def _pct(saved: int, tin: int) -> float:
    return round(100.0 * saved / tin, 1) if tin > 0 else 0.0


def _ago(ts, now=None):
    """Human 'last active' — relative so it's unambiguous across days (unlike a bare clock time)."""
    if not ts:
        return "--"
    s = max(0.0, (now or time.time()) - ts)
    if s < 60:
        return f"{int(s)}s ago"
    if s < 3600:
        return f"{int(s // 60)}m ago"
    if s < 86400:
        return f"{int(s // 3600)}h ago"
    return datetime.datetime.fromtimestamp(ts).strftime("%b %d")


def compute(log_path: str) -> dict:
    """Read the whole log; return overall totals, a per-SESSION breakdown, and a recent feed.

    Each skim server process stamps a `session` id on every call (Claude Code spawns one process per
    session), so we bucket by it. Legacy lines without a session id fall under "unlabeled". Never raises.
    """
    sessions: dict[str, dict] = {}
    recent: list[dict] = []
    exists = os.path.isfile(log_path)
    cleared = _cleared_since(log_path)          # events before the last Clear are hidden

    def bucket(sid: str) -> dict:
        b = sessions.get(sid)
        if b is None:
            b = sessions[sid] = {"id": sid, "named": False, "first_target": None, "cwd": None,
                                 "started": None, "last_active": None, "tokens_in": 0,
                                 "tokens_out": 0, "calls": 0, "by_tool": {}}
        return b

    def touch(b, ts):
        if ts:
            b["last_active"] = max(b["last_active"] or 0, ts)

    if exists:
        try:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        e = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    call = e.get("call")
                    if not call:
                        continue
                    if (e.get("t") or e.get("started") or 0) < cleared:
                        continue                    # predates the last Clear -> hidden from the meter
                    b = bucket(e.get("session") or "unlabeled")
                    if call == "_session_start":          # metadata line, not a tool call
                        b["named"] = e.get("named", b["named"])
                        b["cwd"] = e.get("cwd") or b["cwd"]
                        b["started"] = e.get("started") or b["started"]
                        touch(b, e.get("started") or e.get("t"))
                        continue
                    if "error" in e:
                        continue
                    out = int(e.get("result_tokens", 0) or 0)
                    base = int(e.get("full_tokens", 0) or 0) if call in _BASELINE_CALLS else 0
                    b["tokens_out"] += out
                    b["tokens_in"] += base
                    b["calls"] += 1
                    b["by_tool"][call] = b["by_tool"].get(call, 0) + 1
                    if b["started"] is None:
                        b["started"] = e.get("t")
                    touch(b, e.get("t"))
                    if call == "skim_open":
                        tgt = os.path.basename(e.get("path", "") or "")
                    elif call == "skim_run":
                        tgt = e.get("command", "")
                    elif call == "skim_repo":
                        tgt = os.path.basename((e.get("root", "") or "").rstrip("/\\")) + "/"
                    else:  # expand / search
                        tgt = e.get("handle", "")
                    if b["first_target"] is None and call in _BASELINE_CALLS:
                        b["first_target"] = _short(tgt, 28)      # what this session first worked on
                    recent.append({"session": b["id"], "call": call, "target": _short(tgt),
                                   "in": base, "out": out})
        except OSError:
            exists = False

    # EVERY started session is listed (even before it calls skim, so a fresh session shows up right
    # away), each with a `last_active` timestamp for sorting/telling them apart.
    allsess = []
    for b in sessions.values():
        saved = b["tokens_in"] - b["tokens_out"]
        # sensible differentiator: your SKIM_SESSION_LABEL if set, else the first file/repo it
        # touched, else None (the UI shows "idle"). The short id + start time disambiguate further.
        label = b["id"] if b["named"] else b["first_target"]
        allsess.append({"id": b["id"], "label": label, "named": b["named"],
                        "first_target": b["first_target"],
                        "started": b["started"], "last_active": b["last_active"] or b["started"],
                        "tokens_in": b["tokens_in"], "tokens_out": b["tokens_out"],
                        "saved": saved, "saved_pct": _pct(saved, b["tokens_in"]),
                        "calls": b["calls"], "by_tool": b["by_tool"]})

    tokens_in = sum(s["tokens_in"] for s in allsess)
    tokens_out = sum(s["tokens_out"] for s in allsess)
    calls = sum(s["calls"] for s in allsess)
    by_tool: dict[str, int] = {}
    for s in allsess:
        for k, v in s["by_tool"].items():
            by_tool[k] = by_tool.get(k, 0) + v

    allsess.sort(key=lambda s: (s["last_active"] or 0, s["calls"]), reverse=True)   # most recent first
    saved = tokens_in - tokens_out
    return {
        "log": log_path,
        "log_exists": exists,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "saved": saved,
        "saved_pct": _pct(saved, tokens_in),
        "calls": calls,
        "by_tool": by_tool,
        "session_count": len(allsess),
        "sessions": allsess[:30],          # cap the display; sorted by last activity, newest first
        "recent": recent[-14:][::-1],      # newest first
    }


def _with_price(d: dict, price_per_mtok: float) -> dict:
    """Opt-in dollars: no default price is shipped (prices go stale); the user supplies theirs."""
    if price_per_mtok and price_per_mtok > 0:
        d["price_per_mtok"] = price_per_mtok
        d["saved_usd"] = round(d["saved"] * price_per_mtok / 1_000_000, 2)
    return d


def _watermark(log_path: str) -> str:
    return log_path + ".cleared"


def _cleared_since(log_path: str) -> float:
    """The timestamp of the last Clear (0 if never). compute() hides events older than this."""
    try:
        with open(_watermark(log_path), encoding="utf-8") as f:
            return float(f.read().strip())
    except Exception:
        return 0.0


def clear_log(log_path: str):
    """Archive to a timestamped 'ghost' and reset the meter WITHOUT touching the live log.

    Copies the log to the ghost (a *read* of the live file -- safe under concurrency) and records a
    'cleared at NOW' watermark; compute() then ignores everything before it. The active log is never
    renamed or truncated, so this can't fail on a Windows sharing violation while a skim server -- or
    the meter's own 1s poll -- has the file open. The ghost keeps every prior line for reference.
    Returns the ghost path (or None if there's no log yet).
    """
    if not os.path.isfile(log_path):
        return None
    root, ext = os.path.splitext(log_path)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    ghost = f"{root}.{ts}{ext or '.jsonl'}"
    shutil.copyfile(log_path, ghost)                      # read-only wrt the live log -> never locks it
    with open(_watermark(log_path), "w", encoding="utf-8") as f:
        f.write(str(round(time.time(), 3)))
    return ghost


def snapshot_text(d: dict) -> str:
    if not d["log_exists"]:
        return (f"skim meter: no log yet at {d['log']}\n"
                "Mount skim (claude mcp add skim ...), use skim_open/skim_run/skim_repo on real "
                "files, then re-run.")
    lines = [
        "skim - live token savings",
        f"  log:         {d['log']}",
        f"  tokens IN:   {d['tokens_in']:>12,}   (full reads: open/run/repo baselines)",
        f"  tokens OUT:  {d['tokens_out']:>12,}   (skeletons + every expand/search delivered)",
        f"  net saved:   {d['saved']:>12,}   ({d['saved_pct']}% )",
        f"  calls:       {d['calls']:>12,}   {d['by_tool']}",
    ]
    if "saved_usd" in d:
        lines.insert(5, f"  ~ saved:     {'$' + format(d['saved_usd'], ',.2f'):>12}   "
                        f"(at your ${d['price_per_mtok']}/Mtok)")
    if d["sessions"]:
        lines.append(f"  by session (most recent first, {d.get('session_count', len(d['sessions']))} total):")
        now = time.time()
        for s in d["sessions"][:10]:
            la = _ago(s.get("last_active"), now)
            name = (s.get("label") or "idle")
            body = (f"{s['saved_pct']:>6}%  {s['tokens_in']:>8,} -> {s['tokens_out']:>8,}"
                    if s["calls"] else "        (no skim use yet)")
            lines.append(f"    {name[:18]:<18} {la:>9}  {s['calls']:>2} calls  {body}")
    if d["recent"]:
        lines.append("  recent:")
        for r in d["recent"][:8]:
            flow = f"{r['in']:,} -> {r['out']:,}" if r["in"] else f"+{r['out']:,}"
            lines.append(f"    {r['call']:<12} {r['target']:<46} {flow}")
    return "\n".join(lines)


# ---- web dashboard (single self-contained page; polls /data every second) ----
_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>skim - live token savings</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font:16px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
         background:#0b0f14; color:#f0f6fc; -webkit-font-smoothing:antialiased; padding:24px; }
  .wrap { max-width:860px; margin:0 auto; }
  header { display:flex; align-items:baseline; gap:12px; flex-wrap:wrap; margin-bottom:20px; }
  h1 { font-size:20px; margin:0; letter-spacing:.2px; }
  .dot { width:10px; height:10px; border-radius:50%; background:#3fb950; display:inline-block;
         box-shadow:0 0 0 0 rgba(63,185,80,.6); animation:pulse 2s infinite; }
  @keyframes pulse { 0%{box-shadow:0 0 0 0 rgba(63,185,80,.5)} 70%{box-shadow:0 0 0 8px rgba(63,185,80,0)} 100%{box-shadow:0 0 0 0 rgba(63,185,80,0)} }
  .log { color:#c9d1d9; font-size:12px; font-family:ui-monospace,SFMono-Regular,Consolas,monospace; word-break:break-all; }
  .hero { background:#11161d; border-top:4px solid #3fb950; border-radius:12px; padding:28px 24px; margin-bottom:16px; }
  .hero .big { font-size:64px; font-weight:800; line-height:1; color:#3fb950; letter-spacing:-1px; }
  .hero .sub { color:#c9d1d9; margin-top:6px; font-size:14px; }
  .bar { height:16px; border-radius:8px; background:#1f6feb33; overflow:hidden; margin-top:18px; display:flex; }
  .bar .paid { background:#58a6ff; height:100%; }
  .bar .kept { background:#3fb950; height:100%; }
  .barlbl { display:flex; justify-content:space-between; font-size:12px; color:#c9d1d9; margin-top:6px; }
  .cards { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-bottom:16px; }
  .card { background:#11161d; border-radius:12px; padding:16px 18px; }
  .card .k { color:#c9d1d9; font-size:12px; text-transform:uppercase; letter-spacing:.6px; }
  .card .v { font-size:30px; font-weight:700; margin-top:4px; }
  .card.in .v { color:#58a6ff; } .card.out .v { color:#f0f6fc; } .card.net .v { color:#3fb950; }
  .feed { background:#11161d; border-radius:12px; padding:8px 4px; }
  .feed h2 { font-size:12px; text-transform:uppercase; letter-spacing:.6px; color:#c9d1d9; margin:10px 14px; }
  .note { text-transform:none; letter-spacing:0; color:#8b949e; font-weight:400; }
  .sid { color:#8b949e; font-size:11px; font-family:ui-monospace,Consolas,monospace; }
  .clear { margin-left:auto; align-self:center; background:#21262d; color:#f0f6fc; border:2px solid #3fb950;
           border-radius:8px; padding:6px 14px; font-size:13px; font-weight:600; cursor:pointer; }
  .clear:hover { background:#2d333b; } .clear:active { background:#1c2128; }
  .clear:focus-visible { outline:2px solid #58a6ff; outline-offset:2px; }
  .toast { position:fixed; bottom:22px; left:50%; transform:translateX(-50%); background:#11161d;
           border:2px solid #3fb950; color:#f0f6fc; padding:10px 18px; border-radius:10px; font-size:14px;
           opacity:0; transition:opacity .25s; pointer-events:none; max-width:90%; }
  .toast.show { opacity:1; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  td { padding:7px 14px; }
  tr + tr td { border-top:2px solid #222a35; }
  .tool { font-family:ui-monospace,Consolas,monospace; color:#79c0ff; white-space:nowrap; }
  .tgt { color:#e6edf3; font-family:ui-monospace,Consolas,monospace; }
  .flow { text-align:right; white-space:nowrap; color:#c9d1d9; }
  .flow b { color:#3fb950; } .empty { color:#c9d1d9; padding:20px 14px; }
  @media (max-width:560px){ .cards{grid-template-columns:1fr} .hero .big{font-size:48px} }
</style></head><body><div class="wrap">
  <header><h1>skim &mdash; live token savings</h1><span class="dot" id="dot"></span>
    <span class="log" id="log"></span>
    <button class="clear" id="clearbtn" title="Archive the log to a timestamped ghost file, then reset the meter">Clear</button></header>
  <div class="hero"><div class="big" id="pct">0%</div>
    <div class="sub">of what a full read/run would have cost, saved &middot; <span id="saved">0</span> tokens net<span id="usd"></span></div>
    <div class="bar"><div class="paid" id="paid" style="width:0"></div><div class="kept" id="kept" style="width:100%"></div></div>
    <div class="barlbl"><span>paid (out)</span><span>saved</span></div>
  </div>
  <div class="cards">
    <div class="card in"><div class="k">Tokens in (full)</div><div class="v" id="tin">0</div></div>
    <div class="card out"><div class="k">Tokens out (skim)</div><div class="v" id="tout">0</div></div>
    <div class="card net"><div class="k">Net saved</div><div class="v" id="net">0</div></div>
  </div>
  <div class="feed" id="sesswrap" style="margin-bottom:16px; display:none">
    <h2>By session <span class="note" id="sesscount">&mdash; sorted by last activity, newest first</span></h2>
    <table><tbody id="srows"></tbody></table>
  </div>
  <div class="feed"><h2 id="callhdr">Recent calls</h2>
    <table id="tbl"><tbody id="rows"></tbody></table>
    <div class="empty" id="empty">No skim calls logged yet. Use skim_open / skim_run / skim_repo on real files.</div>
  </div>
  <div class="toast" id="toast" role="status" aria-live="polite"></div>
</div>
<script>
const fmt = n => (n||0).toLocaleString();
// Escape EVERYTHING data-derived before innerHTML: targets are file paths / shell commands /
// session labels, and a hostile command string must render as text, never as markup.
const esc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function ago(ts){
  if(!ts) return '--';
  const s = Math.max(0, Date.now()/1000 - ts);
  if(s < 60) return Math.floor(s)+'s ago';
  if(s < 3600) return Math.floor(s/60)+'m ago';
  if(s < 86400) return Math.floor(s/3600)+'h ago';
  return new Date(ts*1000).toLocaleDateString([], {month:'short', day:'numeric'});
}
function stamp(ts){
  if(!ts) return '';
  const d = new Date(ts*1000), now = new Date();
  const t = d.toLocaleTimeString([], {hour:'numeric', minute:'2-digit'});
  return d.toDateString()===now.toDateString() ? t
       : d.toLocaleDateString([], {month:'short', day:'numeric'})+' '+t;
}
async function tick(){
  try{
    const d = await (await fetch('/data',{cache:'no-store'})).json();
    document.getElementById('log').textContent = d.log_exists ? d.log : ('waiting for log: '+d.log);
    document.getElementById('dot').style.background = d.log_exists ? '#3fb950' : '#d29922';
    document.getElementById('pct').textContent = (d.saved_pct||0) + '%';
    document.getElementById('saved').textContent = fmt(d.saved);
    document.getElementById('usd').textContent = (d.saved_usd !== undefined)
        ? (' · ≈ $' + d.saved_usd.toLocaleString(undefined, {minimumFractionDigits: 2})
           + ' at your $' + d.price_per_mtok + '/Mtok')
        : '';
    document.getElementById('tin').textContent = fmt(d.tokens_in);
    document.getElementById('tout').textContent = fmt(d.tokens_out);
    document.getElementById('net').textContent = fmt(d.saved);
    const paid = d.tokens_in>0 ? Math.max(0,Math.min(100, 100*d.tokens_out/d.tokens_in)) : 0;
    document.getElementById('paid').style.width = paid+'%';
    document.getElementById('kept').style.width = (100-paid)+'%';
    const tools = Object.entries(d.by_tool||{}).map(([k,v])=>k+' '+v).join('  ·  ');
    document.getElementById('callhdr').textContent = 'Recent calls  —  '+fmt(d.calls)+' total'+(tools?('  ('+tools+')'):'');
    const rows = d.recent||[];
    document.getElementById('empty').style.display = rows.length ? 'none':'block';
    document.getElementById('rows').innerHTML = rows.map(r=>{
      const flow = r.in ? (fmt(r.in)+' &rarr; <b>'+fmt(r.out)+'</b>') : ('+'+fmt(r.out));
      return '<tr><td class="tool">'+esc(r.call)+'</td><td class="tgt">'+esc(r.target||'')+
             '</td><td class="flow">'+flow+'</td></tr>';
    }).join('');
    const S = d.sessions||[];
    document.getElementById('sesswrap').style.display = S.length ? 'block':'none';
    const sc = d.session_count||S.length;
    document.getElementById('sesscount').textContent = (S.length < sc)
        ? ('- showing '+S.length+' of '+sc+' sessions, by last activity')
        : '- '+sc+' session'+(sc==1?'':'s')+', sorted by last activity';
    document.getElementById('srows').innerHTML = S.map(s=>{
      const nm = s.label || 'idle';
      const st = s.started ? ('started '+stamp(s.started)+' &middot; ') : '';
      const ttl = s.started ? ('started '+new Date(s.started*1000).toLocaleString()) : '';
      const idle = !s.calls;
      const flow = idle ? '<span class="note">no skim use yet</span>'
                        : fmt(s.tokens_in)+' &rarr; '+fmt(s.tokens_out)+'  <b>'+s.saved_pct+'%</b>';
      return '<tr title="'+esc(ttl)+'"><td class="tool">'+esc(nm)+' <span class="sid">'+esc(s.id)+'</span></td>'+
             '<td class="tgt note">'+st+ago(s.last_active)+' &middot; '+s.calls+' call'+(s.calls==1?'':'s')+'</td>'+
             '<td class="flow">'+flow+'</td></tr>';
    }).join('');
  }catch(e){ document.getElementById('dot').style.background='#f85149'; }
}
function toast(msg){
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'), 4500);
}
document.getElementById('clearbtn').addEventListener('click', async ()=>{
  if(!confirm('Archive the current log to a ghost file and reset the meter to zero?')) return;
  try{
    const r = await (await fetch('/clear', {method:'POST'})).json();
    toast(r.ok ? ('Cleared. History archived to '+(r.ghost||'a ghost file')+'.')
               : ('Could not clear: '+(r.error||'a session is writing, try again')));
  }catch(e){ toast('Could not reach the meter to clear.'); }
  tick();
});
tick(); setInterval(tick, 1000);
</script></body></html>"""


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def _make_handler(log_path: str, price_per_mtok: float = 0.0):
    class H(BaseHTTPRequestHandler):
        def _host_allowed(self) -> bool:
            # DNS-rebinding guard: a hostile page can point its own domain at 127.0.0.1 and then
            # read /data (paths, commands) same-origin. The tell is the Host header carrying the
            # attacker's hostname, so when we're bound to loopback we only answer loopback Hosts.
            bound = self.server.server_address[0]
            if bound not in ("127.0.0.1", "::1", "localhost"):
                return True                      # user explicitly exposed it via --host; their call
            host = self.headers.get("Host")
            if not host:
                return True                      # HTTP/1.0-style local tools
            name = host[: host.index("]") + 1] if host.startswith("[") else host.rsplit(":", 1)[0]
            return name.lower() in _LOOPBACK_HOSTS

        def _send(self, body: bytes, ctype: str):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self._host_allowed():
                self.send_error(403, "forbidden host")
                return
            if self.path.startswith("/data"):
                self._send(json.dumps(_with_price(compute(log_path), price_per_mtok)).encode("utf-8"),
                           "application/json")
            elif self.path in ("/", "/index.html"):
                self._send(_PAGE.encode("utf-8"), "text/html; charset=utf-8")
            else:
                self.send_error(404)

        def do_POST(self):
            if not self._host_allowed():
                self.send_error(403, "forbidden host")
                return
            if self.path.startswith("/clear"):
                try:
                    ghost = clear_log(log_path)
                    body = {"ok": True, "ghost": os.path.basename(ghost) if ghost else None}
                except OSError as ex:
                    body = {"ok": False, "error": str(ex)}
                self._send(json.dumps(body).encode("utf-8"), "application/json")
            else:
                self.send_error(404)

        def log_message(self, *args):
            pass  # quiet; this is a dashboard, not a request logger
    return H


def main() -> None:
    ap = argparse.ArgumentParser(description="Live token-savings meter for skim.")
    ap.add_argument("--log", default=_default_log(), help="path to skim_calls.jsonl")
    ap.add_argument("--port", type=int, default=_DEFAULT_PORT, help="localhost port for the dashboard")
    ap.add_argument("--host", default="127.0.0.1", help="bind host (localhost by default)")
    ap.add_argument("--once", action="store_true", help="print a one-shot text snapshot and exit")
    ap.add_argument("--clear", action="store_true",
                    help="archive the log to a timestamped ghost file and reset, then exit")
    ap.add_argument("--price-per-mtok", type=float,
                    default=float(os.environ.get("SKIM_PRICE_PER_MTOK") or 0),
                    help="optional $ per million tokens; when set, the meter also shows dollars saved")
    args = ap.parse_args()

    if args.clear:
        ghost = clear_log(args.log)
        print(f"cleared -> archived to {ghost}" if ghost else f"nothing to clear (no log at {args.log})")
        return
    if args.once:
        print(snapshot_text(_with_price(compute(args.log), args.price_per_mtok)))
        return

    httpd = ThreadingHTTPServer((args.host, args.port), _make_handler(args.log, args.price_per_mtok))
    url = f"http://{args.host}:{args.port}"
    print(f"skim meter -> {url}   (reading {args.log})")
    print("Leave this open next to your Claude session; it updates every second. Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
