"""``animatica log <project>``: a static, self-contained HTML page of the production log.

Shows every step in order — agent, kind, message — with batch details, critic verdicts and their
preview renders, plus the final video and contact sheet. Open it straight from disk.
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path

from ..core.log import read_log

CSS = """
:root{--bg:#faf8f5;--fg:#1f1d1a;--mut:#6b665e;--card:#fff;--line:#e6e1d8;--ok:#2e7d32;--bad:#c62828;--acc:#d9822b}
@media (prefers-color-scheme:dark){:root{--bg:#141311;--fg:#ece7df;--mut:#a39d93;--card:#1d1b18;--line:#2f2c27;--ok:#66bb6a;--bad:#ef5350}}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--fg)}
main{max-width:1100px;margin:0 auto;padding:24px 16px 80px}h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 8px}
.sub{color:var(--mut);margin:0 0 20px}.hero{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:16px}
@media (max-width:760px){.hero{grid-template-columns:1fr}}video,img{max-width:100%;border-radius:8px;display:block}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.ev{display:grid;grid-template-columns:64px 92px 1fr;gap:10px;padding:8px 0;border-bottom:1px solid var(--line);align-items:start}
.t{color:var(--mut);font-variant-numeric:tabular-nums}.ag{font-weight:600}.k{font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
.pass{color:var(--ok);font-weight:600}.fail{color:var(--bad);font-weight:600}.pv{max-width:360px;margin-top:6px}
details{margin-top:4px}summary{cursor:pointer;color:var(--mut);font-size:13px}pre{white-space:pre-wrap;font-size:12px;overflow:auto;max-height:300px}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;font-size:14px}
"""


def _rel(path: str | None, root: Path) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_absolute():
        p = Path.cwd() / p
    try:
        return os.path.relpath(p, root / "log")
    except ValueError:
        return str(p)


def write_log_html(project: str | Path) -> Path:
    root = Path(project)
    events = read_log(root)
    state = json.loads((root / "project.json").read_text()) if (root / "project.json").exists() else {}
    plan = state.get("plan") or {}
    arts = state.get("artifacts") or {}
    e = html.escape
    parts = [f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>{e(plan.get('title', 'Animatica'))} — production log</title><style>{CSS}</style></head><body><main>"]
    parts.append(f"<h1>{e(plan.get('title', root.name))}</h1><p class='sub'>{e(state.get('prompt', ''))}</p>")
    vid = _rel(arts.get("final"), root)
    sheet = _rel(arts.get("contact_sheet"), root)
    parts.append("<div class='hero'>")
    parts.append(f"<div>{f'<video controls src={chr(39)}{e(vid)}{chr(39)}></video>' if vid else '<div class=card>Not rendered yet.</div>'}</div>")
    usage = arts.get("llm_usage", {})
    rows = [("Provider", usage.get("provider", state.get("provider"))), ("LLM calls / tokens", f"{usage.get('calls', 0)} / {usage.get('tokens', 0)}"),
            ("Shots", len(plan.get("shots", []))), ("Duration", f"{sum(s.get('duration', 0) for s in plan.get('shots', [])):.1f}s"),
            ("Render", f"{arts.get('quality', '-')} in {arts.get('render_seconds', 0):.0f}s"),
            ("Critic iterations", len(arts.get("critic_history", [])))]
    parts.append("<div class='card'><table>" + "".join(f"<tr><th>{e(str(k))}</th><td>{e(str(v))}</td></tr>" for k, v in rows) + "</table></div></div>")
    if sheet and (root / "log" / Path(sheet).name).exists():
        parts.append(f"<h2>Contact sheet</h2><img src='{e(sheet)}' alt='contact sheet'>")
    if plan.get("shots"):
        parts.append("<h2>Shot list</h2><div class='card'><table><tr><th>Shot</th><th>Type</th><th>Beat</th><th>Camera</th><th>Duration</th><th>Description</th></tr>")
        for s in plan["shots"]:
            parts.append(f"<tr><td>{e(s['id'])}</td><td>{e(s['type'])}</td><td>{e(s['beat'])}</td><td>{e(s['camera_move'])}</td>"
                         f"<td>{s['duration']:.1f}s</td><td>{e(s.get('description', ''))}</td></tr>")
        parts.append("</table></div>")
    parts.append("<h2>Production log</h2><div class='card'>")
    for ev in events:
        msg = e(ev.get("message", ""))
        if ev.get("kind") == "critique" and ev.get("verdict"):
            cls = "pass" if ev["verdict"] == "PASS" else "fail"
            msg = msg.replace(ev["verdict"], f"<span class='{cls}'>{ev['verdict']}</span>", 1)
        extra = ""
        pv = _rel(ev.get("preview"), root)
        if pv:
            extra += f"<img class='pv' loading='lazy' src='{e(pv)}' alt='preview'>"
        details = {k: v for k, v in ev.items() if k not in ("t", "ts", "kind", "agent", "message", "preview")}
        if details:
            extra += f"<details><summary>details</summary><pre>{e(json.dumps(details, indent=1, default=str)[:6000])}</pre></details>"
        parts.append(f"<div class='ev'><div class='t'>{ev.get('t', 0):.1f}s</div><div><div class='ag'>{e(ev.get('agent', ''))}</div>"
                     f"<div class='k'>{e(ev.get('kind', ''))}</div></div><div>{msg}{extra}</div></div>")
    parts.append("</div></main></body></html>")
    out = root / "log" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(parts))
    return out
