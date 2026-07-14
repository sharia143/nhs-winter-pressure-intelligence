"""Pipeline CLI.

Usage:
    python scripts/run_pipeline.py <stage> [--force] [--only SOURCE]

Stages: download | ingest | warehouse | analyse | forecast | export | fusion | all

Every stage is idempotent: it skips work whose outputs are already current and
records its result in data/state/stage_status.json, which re-renders
PROGRESS.md (the resume tracker).
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from nhswp import progress  # noqa: E402


def stage_download(args) -> str:
    from nhswp import download
    summary = download.run()
    note = (
        f"A&E {len(summary['ae_months'])} months, RTT {len(summary['rtt_months'])} months, "
        f"{summary['files']} files in manifest"
    )
    if summary["warnings"]:
        note += f"; {len(summary['warnings'])} warnings"
    return note


def stage_ingest(args) -> str:
    from nhswp.ingest import runner
    return runner.run(force=args.force, only=args.only)


def stage_warehouse(args) -> str:
    from nhswp.warehouse import build
    return build.run()


def stage_analyse(args) -> str:
    from nhswp.analysis import kpis
    return kpis.run()


def stage_forecast(args) -> str:
    from nhswp.forecast import runner
    return runner.run()


def stage_export(args) -> str:
    from nhswp.export import powerbi
    return powerbi.run()


def stage_fusion(args) -> str:
    from nhswp.analysis import fusion
    return fusion.run()


STAGES = {
    "download": stage_download,
    "ingest": stage_ingest,
    "warehouse": stage_warehouse,
    "analyse": stage_analyse,
    "forecast": stage_forecast,
    "export": stage_export,
    "fusion": stage_fusion,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=[*STAGES, "all"])
    parser.add_argument("--force", action="store_true", help="ignore skip logic")
    parser.add_argument("--only", default=None, help="restrict ingest to one source")
    args = parser.parse_args()

    to_run = list(STAGES) if args.stage == "all" else [args.stage]
    failed = False
    for name in to_run:
        print(f"=== stage: {name} ===")
        try:
            note = STAGES[name](args)
            progress.record_stage(name, "ok", note or "")
            print(f"=== {name}: ok — {note} ===")
        except Exception as exc:
            traceback.print_exc()
            progress.record_stage(name, "FAILED", f"{type(exc).__name__}: {exc}")
            print(f"=== {name}: FAILED — {exc} ===")
            failed = True
            break  # later stages depend on earlier ones
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
