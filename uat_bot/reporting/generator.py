from __future__ import annotations

import html
import json
from pathlib import Path


class ReportGenerator:
    async def generate(self, run_id: str, run_dir: Path) -> Path:
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

        html = self._render(run_id=run_id, rows=rows, screenshot_paths=screenshot_rel_paths, events=events)
        report_path = run_dir / "report.html"
        report_path.write_text(html, encoding="utf-8")
        return report_path

    @staticmethod
    def _esc(value: object) -> str:
        return html.escape(str(value or ""))

    def _render(
        self,
        run_id: str,
        rows: list[dict],
        screenshot_paths: list[str],
        events: list[dict],
    ) -> str:
        error_count = sum(1 for row in rows if row.get("status") == "error")
        ok_count = sum(1 for row in rows if row.get("status") == "ok")

        screenshot_items = "\n".join(
            (
                "<div class='shot'>"
                f"<a href='/runs/{run_id}/artifacts/{path}' target='_blank'>"
                f"<img src='/runs/{run_id}/artifacts/{path}' alt='{path}'/></a>"
                f"<p>{self._esc(path)}</p></div>"
            )
            for path in screenshot_paths
        )
        table_rows = "\n".join(
            "<tr>"
            f"<td>{self._esc(row.get('ts', ''))}</td>"
            f"<td>{self._esc(row.get('worker_id', ''))}</td>"
            f"<td>{self._esc(row.get('action', ''))}</td>"
            f"<td>{self._esc(row.get('status', ''))}</td>"
            f"<td>{self._esc(row.get('duration_ms', ''))}</td>"
            f"<td>{self._esc(row.get('detail', ''))}</td>"
            "</tr>"
            for row in rows
        )
        event_rows = "\n".join(
            "<tr>"
            f"<td>{self._esc(event.get('ts', ''))}</td>"
            f"<td>{self._esc(event.get('type', ''))}</td>"
            f"<td><code>{self._esc(json.dumps(event.get('payload', {}), ensure_ascii=True))}</code></td>"
            "</tr>"
            for event in events
        )

        return f"""<!doctype html>
<html>
<head>
  <meta charset='utf-8' />
  <title>UAT Bot Report {run_id}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 24px; }}
    .stats {{ display: flex; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }}
    .stats div {{ padding: 12px; background: #f5f7fa; border-radius: 8px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }}
    .shot {{ border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; background: #fff; }}
    .shot img {{ width: 100%; display: block; }}
    .shot p {{ margin: 8px; font-size: 12px; word-break: break-all; }}
    .section {{ margin-top: 24px; }}
    code {{ white-space: pre-wrap; overflow-wrap: anywhere; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 24px; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 8px; font-size: 13px; text-align: left; }}
    th {{ background: #f8fafc; }}
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

  <h2 class='section'>Screenshots</h2>
  <div class='grid'>
    {screenshot_items}
  </div>

  <h2 class='section'>Metrics</h2>
  <table>
    <thead>
      <tr>
        <th>Timestamp</th><th>Worker</th><th>Action</th><th>Status</th><th>Duration (ms)</th><th>Detail</th>
      </tr>
    </thead>
    <tbody>
      {table_rows}
    </tbody>
  </table>

  <h2 class='section'>Run/Event Logs</h2>
  <table>
    <thead>
      <tr>
        <th>Timestamp</th><th>Type</th><th>Payload</th>
      </tr>
    </thead>
    <tbody>
      {event_rows}
    </tbody>
  </table>
</body>
</html>"""
