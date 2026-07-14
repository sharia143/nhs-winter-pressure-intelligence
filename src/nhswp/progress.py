"""PROGRESS.md maintenance.

Machine state lives in data/state/stage_status.json; PROGRESS.md is re-rendered
from it after every stage so a fresh session (human or agent) can resume from
exactly where the last one stopped.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from . import config

STAGES = ["download", "ingest", "warehouse", "analyse", "forecast", "export", "fusion"]


def _load_state() -> dict:
    if config.STAGE_STATUS_PATH.exists():
        return json.loads(config.STAGE_STATUS_PATH.read_text(encoding="utf-8"))
    return {"stages": {}, "log": []}


def _save_state(state: dict) -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    config.STAGE_STATUS_PATH.write_text(
        json.dumps(state, indent=2), encoding="utf-8"
    )


def record_stage(stage: str, status: str, note: str = "", rows: int | None = None) -> None:
    """Record a stage result and re-render PROGRESS.md."""
    state = _load_state()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = state["stages"].get(stage, {})
    entry.update({"status": status, "when": now, "note": note})
    if rows is not None:
        entry["rows"] = rows
    state["stages"][stage] = entry
    state["log"].append({"when": now, "stage": stage, "status": status, "note": note})
    _save_state(state)
    render_progress_md(state)


def render_progress_md(state: dict | None = None) -> None:
    if state is None:
        state = _load_state()
    lines = [
        "# PROGRESS — NHS Winter Pressure Intelligence",
        "",
        "Resume tracker. Machine state: `data/state/stage_status.json`. "
        "Re-run any stage with `python scripts/run_pipeline.py <stage>`; every "
        "stage is idempotent and self-skips when its outputs are current.",
        "",
        f"_Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        "## Stage status",
        "",
        "| Stage | Status | Last run | Rows | Note |",
        "|---|---|---|---|---|",
    ]
    for stage in STAGES:
        e = state["stages"].get(stage, {})
        lines.append(
            f"| {stage} | {e.get('status', 'not started')} | {e.get('when', '—')} "
            f"| {e.get('rows', '—')} | {e.get('note', '')} |"
        )
    lines += [
        "",
        "## How to resume",
        "",
        "1. `python scripts/run_pipeline.py all` — runs every stage; completed stages skip themselves.",
        "2. Check the table above for the first stage that is not `ok`, and re-run just that stage.",
        "3. Manual/user steps live in `docs/MANUAL_STEPS.docx` (and `powerbi/BUILD_GUIDE.md`).",
        "",
        "## Run log (most recent last)",
        "",
    ]
    for item in state["log"][-40:]:
        lines.append(f"- {item['when']} — **{item['stage']}** → {item['status']}"
                     + (f" — {item['note']}" if item.get("note") else ""))
    config.PROGRESS_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
