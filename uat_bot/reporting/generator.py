from __future__ import annotations

import html as html_mod
import json
from pathlib import Path

from uat_bot.reporting.analyzer import AnalysisReport


class ReportGenerator:
    async def generate(
        self,
        run_id: str,
        run_dir: Path,
        ai_analysis: AnalysisReport | None = None,
        auto_refresh_seconds: int = 0,
    ) -> Path:
        metrics_path = run_dir / "metrics.jsonl"
        rows: list[dict] = []
        events_path = run_dir / "events.jsonl"
        events: list[dict] = []

        if metrics_path.exists():
            for line in metrics_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        if events_path.exists():
            for line in events_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    events.append(payload)

        screenshot_rel_paths: list[str] = []
        shots_dir = run_dir / "screenshots"
        if shots_dir.exists():
            for path in sorted(shots_dir.rglob("*.png")) + sorted(shots_dir.rglob("*.jpg")):
                screenshot_rel_paths.append(path.relative_to(run_dir).as_posix())

        report_html = self._render(
            run_id=run_id,
            rows=rows,
            screenshot_paths=screenshot_rel_paths,
            events=events,
            ai_analysis=ai_analysis,
            auto_refresh_seconds=max(0, int(auto_refresh_seconds or 0)),
        )
        report_path = run_dir / "report.html"
        report_path.write_text(report_html, encoding="utf-8")

        # Also persist analysis JSON for programmatic access
        if ai_analysis and not ai_analysis.error:
            analysis_path = run_dir / "ai_analysis.json"
            analysis_path.write_text(
                json.dumps(
                    {
                        "overall_verdict": ai_analysis.overall_verdict,
                        "executive_summary": ai_analysis.executive_summary,
                        "pass_count": ai_analysis.pass_count,
                        "fail_count": ai_analysis.fail_count,
                        "warn_count": ai_analysis.warn_count,
                        "steps": [
                            {
                                "screenshot": v.screenshot,
                                "verdict": v.verdict,
                                "summary": v.summary,
                                "issues": v.issues,
                            }
                            for v in ai_analysis.step_verdicts
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

        return report_path

    @staticmethod
    def _esc(value: object) -> str:
        return html_mod.escape(str(value or ""))

    def _render_ai_analysis(self, ai_analysis: AnalysisReport | None, run_id: str) -> str:
        if not ai_analysis:
            return ""

        verdict_color = {
            "pass": "#117f2d",
            "fail": "#b42318",
            "warn": "#b35a00",
        }.get(ai_analysis.overall_verdict, "#6b7280")
        verdict_bg = {
            "pass": "#ecfdf5",
            "fail": "#fef2f2",
            "warn": "#fffbeb",
        }.get(ai_analysis.overall_verdict, "#f5f7fa")
        verdict_label = ai_analysis.overall_verdict.upper()

        # Build step verdicts as JSON for client-side rendering
        step_data = json.dumps(
            [
                {
                    "screenshot": v.screenshot,
                    "verdict": v.verdict,
                    "summary": v.summary,
                    "issues": v.issues,
                }
                for v in ai_analysis.step_verdicts
            ],
            ensure_ascii=True,
        )

        error_note = ""
        if ai_analysis.error:
            error_note = (
                f"<p style='color:#b42318;font-size:13px;'>"
                f"Note: Analysis encountered an error: {self._esc(ai_analysis.error)}</p>"
            )

        return f"""
  <h2 class='section'>AI Analysis</h2>
  <div style='border:2px solid {verdict_color};border-radius:12px;padding:20px;
              background:{verdict_bg};margin-bottom:16px;'>
    <div style='display:flex;align-items:center;gap:12px;margin-bottom:12px;'>
      <span style='font-size:28px;font-weight:700;color:{verdict_color};'>{verdict_label}</span>
      <span style='font-size:14px;color:#6b7280;'>
        {ai_analysis.pass_count} passed &middot;
        {ai_analysis.fail_count} failed &middot;
        {ai_analysis.warn_count} warnings
      </span>
    </div>
    <p style='font-size:14px;line-height:1.6;margin:0;'>{self._esc(ai_analysis.executive_summary)}</p>
    {error_note}
  </div>

  <h3>Step-by-Step Verdicts</h3>
  <div class="filter-bar">
    <label>Verdict: <select id="ai-verdict-filter">
      <option value="">All</option>
      <option value="pass">Pass</option>
      <option value="fail">Fail</option>
      <option value="warn">Warn</option>
    </select></label>
  </div>
  <div class="pager" id="ai-pager"></div>
  <table>
    <thead>
      <tr>
        <th style='width:60px;'>Verdict</th>
        <th>Screenshot</th>
        <th>Summary</th>
        <th>Issues</th>
      </tr>
    </thead>
    <tbody id="ai-tbody"></tbody>
  </table>

  <script>
  const AI_STEPS = {step_data};
  const AI_RUN_ID = {json.dumps(run_id)};
  let aiPage = 1, aiSize = 50, aiFilter = "";

  function filteredAI() {{
    return AI_STEPS.filter(function(s) {{
      return !aiFilter || s.verdict === aiFilter;
    }});
  }}

  function renderAI() {{
    const filtered = filteredAI();
    const pager = makePager(document.getElementById("ai-pager"), filtered.length, aiSize, aiPage, function(p, s) {{
      aiPage = p; aiSize = s; renderAI();
    }});
    aiPage = pager.page;
    const start = (aiPage - 1) * aiSize;
    const slice = filtered.slice(start, start + aiSize);
    const tbody = document.getElementById("ai-tbody");
    if (slice.length === 0) {{
      tbody.innerHTML = "<tr><td colspan='4'>No steps match filter.</td></tr>";
      return;
    }}
    tbody.innerHTML = slice.map(function(s) {{
      const vc = s.verdict === "fail" ? "status-error" : s.verdict === "pass" ? "status-ok" : "status-warn";
      const badge = s.verdict.toUpperCase();
      const imgLink = "<a href='/runs/" + AI_RUN_ID + "/artifacts/" + s.screenshot + "' target='_blank'>" + esc(s.screenshot.split("/").pop()) + "</a>";
      const issues = (s.issues || []).map(function(i) {{ return "<li>" + esc(i) + "</li>"; }}).join("");
      const issueList = issues ? "<ul style='margin:0;padding-left:16px;'>" + issues + "</ul>" : "&mdash;";
      return "<tr><td class='" + vc + "' style='font-weight:600;text-align:center;'>" + badge + "</td>"
        + "<td>" + imgLink + "</td>"
        + "<td>" + esc(s.summary) + "</td>"
        + "<td>" + issueList + "</td></tr>";
    }}).join("");
  }}

  document.getElementById("ai-verdict-filter").addEventListener("change", function(e) {{
    aiFilter = e.target.value; aiPage = 1; renderAI();
  }});
  renderAI();
  </script>
"""

    def _render(
        self,
        run_id: str,
        rows: list[dict],
        screenshot_paths: list[str],
        events: list[dict],
        ai_analysis: AnalysisReport | None = None,
        auto_refresh_seconds: int = 0,
    ) -> str:
        error_count = sum(1 for row in rows if row.get("status") == "error")
        ok_count = sum(1 for row in rows if row.get("status") == "ok")

        # Serialize data as JSON for client-side pagination
        screenshots_json = json.dumps(screenshot_paths, ensure_ascii=True)
        metrics_json = json.dumps(rows, ensure_ascii=True)
        events_json = json.dumps(events, ensure_ascii=True)

        ai_section = self._render_ai_analysis(ai_analysis, run_id)
        auto_refresh_notice = ""
        if auto_refresh_seconds > 0:
            auto_refresh_notice = (
                "<p style='margin:0 0 12px;color:#0f766e;font-size:13px;'>"
                f"Run is active. This report auto-refreshes every {auto_refresh_seconds}s."
                "</p>"
            )

        return f"""<!doctype html>
<html>
<head>
  <meta charset='utf-8' />
  <title>UAT Bot Report {run_id}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 24px; color: #1a1a1a; }}
    .stats {{ display: flex; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }}
    .stats div {{ padding: 12px; background: #f5f7fa; border-radius: 8px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }}
    .shot {{ border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; background: #fff; cursor: pointer; transition: transform 0.15s, box-shadow 0.15s; }}
    .shot:hover {{ transform: translateY(-2px); box-shadow: 0 6px 16px rgba(0,0,0,0.12); }}
    .shot img {{ width: 100%; display: block; }}
    .shot p {{ margin: 8px; font-size: 12px; word-break: break-all; }}
    .lb {{ display:none; position:fixed; inset:0; z-index:9999; background:rgba(0,0,0,0.88); align-items:center; justify-content:center; flex-direction:column; }}
    .lb.open {{ display:flex; }}
    .lb img {{ max-width:92vw; max-height:80vh; border-radius:8px; box-shadow:0 8px 40px rgba(0,0,0,0.5); }}
    .lb .cap {{ color:#ccc; font-size:13px; margin-top:10px; text-align:center; }}
    .lb .cnt {{ color:#888; font-size:12px; margin-top:4px; }}
    .lb .nav {{ position:absolute; top:50%; transform:translateY(-50%); background:rgba(255,255,255,0.15); border:none; color:#fff; font-size:32px; width:48px; height:48px; border-radius:50%; cursor:pointer; display:flex; align-items:center; justify-content:center; }}
    .lb .nav:hover {{ background:rgba(255,255,255,0.3); }}
    .lb .prv {{ left:16px; }}
    .lb .nxt {{ right:16px; }}
    .lb .cls {{ position:absolute; top:16px; right:16px; background:rgba(255,255,255,0.15); border:none; color:#fff; font-size:24px; width:40px; height:40px; border-radius:50%; cursor:pointer; display:flex; align-items:center; justify-content:center; }}
    .lb .cls:hover {{ background:rgba(255,255,255,0.3); }}
    .section {{ margin-top: 24px; }}
    code {{ white-space: pre-wrap; overflow-wrap: anywhere; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 8px; font-size: 13px; text-align: left; }}
    th {{ background: #f8fafc; }}
    .pager {{ display: flex; align-items: center; gap: 10px; margin: 12px 0; flex-wrap: wrap; }}
    .pager button {{
      border: 1px solid #d1d5db; border-radius: 6px; padding: 6px 14px;
      background: #fff; cursor: pointer; font-size: 13px;
    }}
    .pager button:disabled {{ opacity: 0.4; cursor: default; }}
    .pager button:hover:not(:disabled) {{ background: #f3f4f6; }}
    .pager .info {{ font-size: 13px; color: #6b7280; }}
    .pager select {{ border: 1px solid #d1d5db; border-radius: 6px; padding: 4px 8px; font-size: 13px; }}
    .filter-bar {{ display: flex; gap: 8px; align-items: center; margin: 8px 0; flex-wrap: wrap; }}
    .filter-bar select, .filter-bar input {{
      border: 1px solid #d1d5db; border-radius: 6px; padding: 4px 8px; font-size: 13px;
    }}
    .status-error {{ color: #b42318; font-weight: 600; }}
    .status-ok {{ color: #117f2d; }}
    .status-warn {{ color: #b35a00; }}
  </style>
</head>
<body>
  <h1>UAT Bot Run Report</h1>
  <p><strong>Run ID:</strong> {run_id}</p>

  <div class='stats'>
    <div><strong>Actions OK:</strong> {ok_count}</div>
    <div><strong>Actions Error:</strong> {error_count}</div>
    <div><strong>Screenshots:</strong> {len(screenshot_paths)}</div>
    <div><strong>Events Logged:</strong> {len(events)}</div>
  </div>
  {auto_refresh_notice}

  {ai_section}

  <h2 class='section'>Screenshots</h2>
  <div class="pager" id="shots-pager"></div>
  <div class='grid' id="shots-grid"></div>

  <div class="lb" id="lb">
    <button class="cls" id="lb-cls" onclick="closeLb()">&times;</button>
    <button class="nav prv" id="lb-prv" onclick="lbNav(-1)">&#8249;</button>
    <button class="nav nxt" id="lb-nxt" onclick="lbNav(1)">&#8250;</button>
    <img id="lb-img" src="" alt="Screenshot" />
    <div class="cap" id="lb-cap"></div>
    <div class="cnt" id="lb-cnt"></div>
  </div>

  <h2 class='section'>Metrics</h2>
  <div class="filter-bar">
    <label>Status: <select id="metrics-status-filter">
      <option value="">All</option>
      <option value="ok">OK</option>
      <option value="error">Error</option>
      <option value="warn">Warn</option>
    </select></label>
    <label>Action: <select id="metrics-action-filter"><option value="">All</option></select></label>
  </div>
  <div class="pager" id="metrics-pager"></div>
  <table>
    <thead>
      <tr>
        <th>Timestamp</th><th>Worker</th><th>Action</th><th>Status</th><th>Duration (ms)</th><th>Detail</th>
      </tr>
    </thead>
    <tbody id="metrics-tbody"></tbody>
  </table>

  <h2 class='section'>Run/Event Logs</h2>
  <div class="pager" id="events-pager"></div>
  <table>
    <thead>
      <tr>
        <th>Timestamp</th><th>Type</th><th>Payload</th>
      </tr>
    </thead>
    <tbody id="events-tbody"></tbody>
  </table>

<script>
const RUN_ID = {json.dumps(run_id)};
const AUTO_REFRESH_SECONDS = {int(auto_refresh_seconds)};
const SNAPSHOT_URL = "/runs/" + RUN_ID + "/snapshot";
let ALL_SHOTS = {screenshots_json};
let ALL_METRICS = {metrics_json};
let ALL_EVENTS = {events_json};

function esc(v) {{
  return String(v || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}}

function statusClass(s) {{
  if (s === "error") return "status-error";
  if (s === "ok") return "status-ok";
  if (s === "warn") return "status-warn";
  return "";
}}

/* ---- Paginator ---- */
function makePager(containerEl, total, pageSize, currentPage, onPageChange) {{
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const p = Math.min(Math.max(1, currentPage), pages);

  let html = '<button data-p="1">&laquo;</button>';
  html += '<button data-p="' + (p - 1) + '">&lsaquo; Prev</button>';
  html += '<span class="info">Page ' + p + ' / ' + pages + ' (' + total + ' items)</span>';
  html += '<button data-p="' + (p + 1) + '">Next &rsaquo;</button>';
  html += '<button data-p="' + pages + '">&raquo;</button>';
  html += ' <select data-role="pagesize">';
  [20, 50, 100, 200].forEach(function(s) {{
    html += '<option value="' + s + '"' + (s === pageSize ? ' selected' : '') + '>' + s + '/page</option>';
  }});
  html += '</select>';

  containerEl.innerHTML = html;

  containerEl.querySelectorAll("button[data-p]").forEach(function(btn) {{
    const target = parseInt(btn.getAttribute("data-p"));
    btn.disabled = target < 1 || target > pages || target === p;
    btn.addEventListener("click", function() {{ onPageChange(target, pageSize); }});
  }});
  containerEl.querySelector("select[data-role=pagesize]").addEventListener("change", function(e) {{
    onPageChange(1, parseInt(e.target.value));
  }});

  return {{ page: p, pages: pages }};
}}

/* ---- Screenshots ---- */
let shotPage = 1, shotSize = 20;
let lbIdx = 0, lbUrls = [];

function renderShots() {{
  const pager = makePager(document.getElementById("shots-pager"), ALL_SHOTS.length, shotSize, shotPage, function(p, s) {{
    shotPage = p; shotSize = s; renderShots();
  }});
  shotPage = pager.page;

  const start = (shotPage - 1) * shotSize;
  const slice = ALL_SHOTS.slice(start, start + shotSize);
  const grid = document.getElementById("shots-grid");

  // Build full URL list for gallery navigation
  lbUrls = ALL_SHOTS.map(function(p) {{ return {{ url: "/runs/" + RUN_ID + "/artifacts/" + p, path: p }}; }});

  if (slice.length === 0) {{
    grid.innerHTML = "<p>No screenshots.</p>";
    return;
  }}
  grid.innerHTML = slice.map(function(path, i) {{
    const globalIdx = start + i;
    const url = "/runs/" + RUN_ID + "/artifacts/" + path;
    return "<div class='shot' onclick='openLb(" + globalIdx + ")'><img loading='lazy' src='" + url + "' alt='" + esc(path) + "'/><p>" + esc(path) + "</p></div>";
  }}).join("");
}}

function openLb(idx) {{
  lbIdx = idx;
  updateLb();
  document.getElementById("lb").classList.add("open");
}}
function closeLb() {{
  document.getElementById("lb").classList.remove("open");
}}
function lbNav(dir) {{
  lbIdx = Math.max(0, Math.min(lbUrls.length - 1, lbIdx + dir));
  updateLb();
}}
function updateLb() {{
  var item = lbUrls[lbIdx];
  if (!item) return;
  document.getElementById("lb-img").src = item.url;
  document.getElementById("lb-cap").textContent = item.path;
  document.getElementById("lb-cnt").textContent = (lbIdx + 1) + " / " + lbUrls.length;
}}
document.getElementById("lb").addEventListener("click", function(e) {{
  if (e.target === document.getElementById("lb")) closeLb();
}});
document.addEventListener("keydown", function(e) {{
  if (!document.getElementById("lb").classList.contains("open")) return;
  if (e.key === "Escape") closeLb();
  if (e.key === "ArrowLeft") lbNav(-1);
  if (e.key === "ArrowRight") lbNav(1);
}});

/* ---- Metrics ---- */
let metricPage = 1, metricSize = 50;
let metricStatusFilter = "", metricActionFilter = "";

function filteredMetrics() {{
  return ALL_METRICS.filter(function(r) {{
    if (metricStatusFilter && r.status !== metricStatusFilter) return false;
    if (metricActionFilter && r.action !== metricActionFilter) return false;
    return true;
  }});
}}

function renderMetrics() {{
  const filtered = filteredMetrics();
  const pager = makePager(document.getElementById("metrics-pager"), filtered.length, metricSize, metricPage, function(p, s) {{
    metricPage = p; metricSize = s; renderMetrics();
  }});
  metricPage = pager.page;

  const start = (metricPage - 1) * metricSize;
  const slice = filtered.slice(start, start + metricSize);
  const tbody = document.getElementById("metrics-tbody");

  if (slice.length === 0) {{
    tbody.innerHTML = "<tr><td colspan='6'>No metrics match the filter.</td></tr>";
    return;
  }}
  tbody.innerHTML = slice.map(function(r) {{
    return "<tr>"
      + "<td>" + esc(r.ts) + "</td>"
      + "<td>" + esc(r.worker_id) + "</td>"
      + "<td>" + esc(r.action) + "</td>"
      + "<td class='" + statusClass(r.status) + "'>" + esc(r.status) + "</td>"
      + "<td>" + esc(r.duration_ms) + "</td>"
      + "<td>" + esc(r.detail) + "</td>"
      + "</tr>";
  }}).join("");
}}

function initMetricFilters() {{
  const actionSel = document.getElementById("metrics-action-filter");
  syncMetricActionOptions(actionSel);

  document.getElementById("metrics-status-filter").addEventListener("change", function(e) {{
    metricStatusFilter = e.target.value; metricPage = 1; renderMetrics();
  }});
  actionSel.addEventListener("change", function(e) {{
    metricActionFilter = e.target.value; metricPage = 1; renderMetrics();
  }});
}}

function syncMetricActionOptions(actionSel) {{
  const currentValue = actionSel.value || "";
  const actions = new Set();
  ALL_METRICS.forEach(function(r) {{ if (r.action) actions.add(r.action); }});
  actionSel.innerHTML = '<option value="">All</option>';
  Array.from(actions).sort().forEach(function(a) {{
    const opt = document.createElement("option");
    opt.value = a;
    opt.textContent = a;
    actionSel.appendChild(opt);
  }});
  if (currentValue && Array.from(actions).includes(currentValue)) {{
    actionSel.value = currentValue;
  }} else {{
    actionSel.value = "";
    metricActionFilter = "";
  }}
}}

/* ---- Events ---- */
let eventPage = 1, eventSize = 50;

function renderEvents() {{
  const pager = makePager(document.getElementById("events-pager"), ALL_EVENTS.length, eventSize, eventPage, function(p, s) {{
    eventPage = p; eventSize = s; renderEvents();
  }});
  eventPage = pager.page;

  const start = (eventPage - 1) * eventSize;
  const slice = ALL_EVENTS.slice(start, start + eventSize);
  const tbody = document.getElementById("events-tbody");

  if (slice.length === 0) {{
    tbody.innerHTML = "<tr><td colspan='3'>No events.</td></tr>";
    return;
  }}
  tbody.innerHTML = slice.map(function(evt) {{
    return "<tr>"
      + "<td>" + esc(evt.ts) + "</td>"
      + "<td>" + esc(evt.type) + "</td>"
      + "<td><code>" + esc(JSON.stringify(evt.payload || {{}})) + "</code></td>"
      + "</tr>";
  }}).join("");
}}

function samePaths(a, b) {{
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {{
    if (a[i] !== b[i]) return false;
  }}
  return true;
}}

function hasSnapshotChanged(next) {{
  if (!next) return false;
  if (!samePaths(ALL_SHOTS, next.screenshots || [])) return true;
  const nextMetrics = next.metrics || [];
  const nextEvents = next.events || [];
  if (ALL_METRICS.length !== nextMetrics.length || ALL_EVENTS.length !== nextEvents.length) {{
    return true;
  }}
  const lastMetric = ALL_METRICS[ALL_METRICS.length - 1];
  const nextLastMetric = nextMetrics[nextMetrics.length - 1];
  const lastEvent = ALL_EVENTS[ALL_EVENTS.length - 1];
  const nextLastEvent = nextEvents[nextEvents.length - 1];
  return JSON.stringify(lastMetric || null) !== JSON.stringify(nextLastMetric || null)
    || JSON.stringify(lastEvent || null) !== JSON.stringify(nextLastEvent || null);
}}

let snapshotBusy = false;

async function pollSnapshot() {{
  if (snapshotBusy) return;
  snapshotBusy = true;
  try {{
    const res = await fetch(SNAPSHOT_URL, {{ cache: "no-store" }});
    if (!res.ok) return;
    const next = await res.json();
    if (!hasSnapshotChanged(next)) return;
    ALL_SHOTS = Array.isArray(next.screenshots) ? next.screenshots : [];
    ALL_METRICS = Array.isArray(next.metrics) ? next.metrics : [];
    ALL_EVENTS = Array.isArray(next.events) ? next.events : [];
    syncMetricActionOptions(document.getElementById("metrics-action-filter"));
    renderShots();
    renderMetrics();
    renderEvents();
  }} catch (_err) {{
    // ignore transient poll failures
  }} finally {{
    snapshotBusy = false;
  }}
}}

/* ---- Boot ---- */
renderShots();
initMetricFilters();
renderMetrics();
renderEvents();
if (AUTO_REFRESH_SECONDS > 0) {{
  window.setInterval(function() {{
    pollSnapshot();
  }}, AUTO_REFRESH_SECONDS * 1000);
}}
</script>
</body>
</html>"""
