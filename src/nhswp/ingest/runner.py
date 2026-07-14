"""Ingest orchestration: raw files -> typed staging parquet.

Skip logic: a source is re-parsed only when its PARSER_VERSION or its set of
raw inputs (from the manifest) changes. Metadata lives in
data/staging/_meta.json.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pandas as pd

from .. import config
from . import ae, ambsys, context, ods, rtt

META_PATH = config.STAGING_DIR / "_meta.json"


def _load_meta() -> dict:
    if META_PATH.exists():
        return json.loads(META_PATH.read_text(encoding="utf-8"))
    return {}


def _save_meta(meta: dict) -> None:
    config.STAGING_DIR.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _inputs_fingerprint(prefixes: list[str]) -> str:
    manifest = json.loads(config.MANIFEST_PATH.read_text(encoding="utf-8"))
    relevant = {k: v["sha256"] for k, v in sorted(manifest.items())
                if any(k.startswith(p) for p in prefixes)}
    return hashlib.sha256(json.dumps(relevant).encode()).hexdigest()


def _write(name: str, df: pd.DataFrame) -> int:
    config.STAGING_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(config.STAGING_DIR / f"{name}.parquet", index=False)
    return len(df)


SOURCES = {
    # source key -> (parser version key, manifest prefixes, builder)
    "ods": ("ods", ["ods/"], lambda: ods.run_all()),
    "ae": ("ae", ["ae/"], lambda: dict(zip(["ae", "_ae_validations"], ae.parse_all()))),
    "rtt": ("rtt", ["rtt/"], lambda: dict(zip(["rtt_summary", "rtt_bands"], rtt.parse_all()))),
    "ambsys": ("ambsys", ["ambulance/"], lambda: {"ambulance": ambsys.parse_ambsys()}),
    "imd": ("imd", ["imd/"], lambda: {"imd": context.parse_imd()}),
    "catchment": ("catchment", ["catchment/"], lambda: {"catchment": context.parse_catchment()}),
    "weather": ("weather", ["weather/"], lambda: {"weather": context.parse_weather()}),
    "vacancy": ("vacancy", ["vacancy/"], lambda: {"vacancy": context.parse_vacancy()}),
}


def run(force: bool = False, only: str | None = None) -> str:
    meta = _load_meta()
    notes = []
    for source, (version_key, prefixes, builder) in SOURCES.items():
        if only and source != only:
            continue
        version = config.PARSER_VERSIONS[version_key]
        fingerprint = _inputs_fingerprint(prefixes)
        prior = meta.get(source, {})
        if not force and prior.get("parser_version") == version and prior.get("inputs") == fingerprint:
            notes.append(f"{source}: current (skipped)")
            continue
        print(f"ingesting {source}…")
        tables = builder()
        rows = {}
        for name, obj in tables.items():
            if name.startswith("_"):  # validation side-outputs -> state dir
                config.STATE_DIR.mkdir(parents=True, exist_ok=True)
                (config.STATE_DIR / f"{name[1:]}.json").write_text(
                    json.dumps(obj, indent=2, default=str), encoding="utf-8"
                )
                continue
            rows[name] = _write(name, obj)
        meta[source] = {
            "parser_version": version,
            "inputs": fingerprint,
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "rows": rows,
        }
        _save_meta(meta)
        notes.append(f"{source}: {sum(rows.values())} rows across {len(rows)} tables")
    return "; ".join(notes)
