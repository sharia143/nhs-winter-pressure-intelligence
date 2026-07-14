"""Download stage.

NHS England file URLs embed random hash suffixes and upload dates, so they are
scraped from the stable yearly archive pages at run time. Every fetched file is
recorded in data/raw/manifest.json (url, sha256, size, retrieved_at) under a
normalised local name so the hash suffixes never leak downstream. Re-runs skip
files already present whose manifest entry matches; a changed upstream hash is
surfaced as a revision warning, not silently overwritten.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import config

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

MONTHS = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]
MON3 = {m[:3]: i + 1 for i, m in enumerate(MONTHS)}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def _get(session: requests.Session, url: str, tries: int = 4) -> requests.Response:
    last = None
    for attempt in range(tries):
        try:
            r = session.get(url, timeout=120)
            if r.status_code == 200:
                return r
            last = RuntimeError(f"HTTP {r.status_code} for {url}")
        except requests.RequestException as exc:  # transient network errors
            last = exc
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed after {tries} tries: {url}") from last


def _hrefs(html: str) -> list[str]:
    return re.findall(r'href="([^"]+)"', html)


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def _load_manifest() -> dict:
    if config.MANIFEST_PATH.exists():
        return json.loads(config.MANIFEST_PATH.read_text(encoding="utf-8"))
    return {}


def _save_manifest(manifest: dict) -> None:
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    config.MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )


def _fetch_file(
    session: requests.Session,
    manifest: dict,
    key: str,
    url: str,
    local_rel: str,
    warnings: list[str],
) -> bool:
    """Download url -> data/raw/<local_rel> unless already current. Returns True if fetched."""
    local = config.RAW_DIR / local_rel
    entry = manifest.get(key)
    if entry and local.exists() and local.stat().st_size == entry.get("size"):
        return False  # already have it
    local.parent.mkdir(parents=True, exist_ok=True)
    r = _get(session, url)
    content = r.content
    sha = hashlib.sha256(content).hexdigest()
    if entry and entry.get("sha256") not in (None, sha):
        warnings.append(
            f"REVISED UPSTREAM: {key} content hash changed "
            f"({entry['sha256'][:10]}… → {sha[:10]}…) — source file re-issued by publisher"
        )
    local.write_bytes(content)
    manifest[key] = {
        "url": url,
        "local": local_rel,
        "sha256": sha,
        "size": len(content),
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return True


# ---------------------------------------------------------------------------
# A&E: one CSV per month, scraped per financial-year archive page
# ---------------------------------------------------------------------------

def _ae_candidates(hrefs: list[str]) -> dict[str, list[str]]:
    """Map 'YYYY-MM' -> candidate CSV urls found on an archive page."""
    out: dict[str, list[str]] = {}
    for href in hrefs:
        if not href.lower().endswith(".csv"):
            continue
        name = href.rsplit("/", 1)[-1].lower()
        if "time-series" in name or "timeseries" in name:
            continue
        m = re.search(
            r"(january|february|march|april|may|june|july|august|september|october|november|december)"
            r"[-_ ]?(\d{4})",
            name,
        )
        if m:
            month = MONTHS.index(m.group(1)) + 1
            year = int(m.group(2))
        else:
            # Short form, e.g. "Monthly-AE-Nov-25-CSV-revised.csv"
            m = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[-_ ](\d{2})(?!\d)", name)
            if not m:
                continue
            month = MON3[m.group(1)]
            year = 2000 + int(m.group(2))
        if not 2015 <= year <= 2035:
            continue
        out.setdefault(f"{year:04d}-{month:02d}", []).append(href)
    return out


def _pick_ae(candidates: list[str]) -> str:
    """Prefer revised files, then higher revision numbers."""
    def score(u: str) -> tuple:
        n = u.lower()
        rev = 1 if "revised" in n else 0
        rev2 = 1 if re.search(r"revised[-_]?2", n) else 0
        return (rev, rev2, len(n))
    return sorted(candidates, key=score)[-1]


def download_ae(session, manifest, warnings, log) -> list[str]:
    months_found = []
    for fy, page_url in config.AE_ARCHIVE_PAGES.items():
        try:
            page = _get(session, page_url).text
        except RuntimeError as exc:
            warnings.append(f"A&E archive page unreachable ({fy}): {exc}")
            continue
        by_month = _ae_candidates(_hrefs(page))
        for month, cands in sorted(by_month.items()):
            if month < config.WINDOW_START:
                continue
            url = _pick_ae(cands)
            if _fetch_file(session, manifest, f"ae/{month}", url, f"ae/{month}.csv", warnings):
                log(f"  A&E {month} ← {url.rsplit('/', 1)[-1]}")
            months_found.append(month)
    return sorted(set(months_found))


# ---------------------------------------------------------------------------
# RTT: one "Full CSV data file" zip per month
# ---------------------------------------------------------------------------

def _rtt_candidates(hrefs: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for href in hrefs:
        name = href.rsplit("/", 1)[-1]
        # Word order varies across years: "...-Apr26-ZIP-3M-X7gGnn.zip" vs
        # "...-Apr22-revised-ZIP-4253.zip" — only anchor on the month token.
        m = re.match(r"(?i)Full-CSV-data-file-([A-Za-z]{3})(\d{2})[-_].*\.zip$", name)
        if not m:
            continue
        mon = MON3.get(m.group(1).lower())
        if mon is None:
            continue
        year = 2000 + int(m.group(2))
        out.setdefault(f"{year:04d}-{mon:02d}", []).append(href)
    return out


def download_rtt(session, manifest, warnings, log) -> list[str]:
    months_found = []
    for fy, page_url in config.RTT_ARCHIVE_PAGES.items():
        try:
            page = _get(session, page_url).text
        except RuntimeError as exc:
            warnings.append(f"RTT archive page unreachable ({fy}): {exc}")
            continue
        by_month = _rtt_candidates(_hrefs(page))
        for month, cands in sorted(by_month.items()):
            if month < config.WINDOW_START:
                continue
            url = _pick_ae(cands)  # same revised-preference logic
            if _fetch_file(session, manifest, f"rtt/{month}", url, f"rtt/{month}.zip", warnings):
                log(f"  RTT {month} ← {url.rsplit('/', 1)[-1]}")
            months_found.append(month)
    return sorted(set(months_found))


# ---------------------------------------------------------------------------
# Ambulance: single consolidated AmbSYS CSV from the AQI landing page
# ---------------------------------------------------------------------------

def download_ambulance(session, manifest, warnings, log) -> None:
    page = _get(session, config.AMBULANCE_LANDING).text
    cands = [
        h for h in _hrefs(page)
        if re.search(r"(?i)AmbSYS[-_]to[-_].*\.csv$", h.rsplit("/", 1)[-1])
    ]
    if not cands:
        raise RuntimeError("no AmbSYS consolidated CSV link found on AQI landing page")
    url = sorted(cands)[-1]
    if _fetch_file(session, manifest, "ambulance/ambsys", url, "ambulance/ambsys.csv", warnings):
        log(f"  AmbSYS ← {url.rsplit('/', 1)[-1]}")


# ---------------------------------------------------------------------------
# Vacancy statistics: series page -> latest edition -> tables xlsx
# ---------------------------------------------------------------------------

def download_vacancy(session, manifest, warnings, log) -> None:
    page = _get(session, config.VACANCY_SERIES_PAGE).text
    editions = [
        h for h in _hrefs(page)
        if "/nhs-vacancies-survey/" in h and re.search(r"(?i)(experimental|statistics)", h)
    ]
    if not editions:
        raise RuntimeError("no vacancy edition pages found")
    # Edition slugs sort chronologically enough to pick the latest by page order;
    # take the first edition link in document order (NHS lists newest first).
    edition_url = editions[0]
    if edition_url.startswith("/"):
        edition_url = "https://digital.nhs.uk" + edition_url
    epage = _get(session, edition_url).text
    files = [
        h for h in _hrefs(epage)
        if "files.digital.nhs.uk" in h and h.lower().endswith(".xlsx") and "tables" in h.lower()
    ]
    if not files:
        raise RuntimeError(f"no tables xlsx found on vacancy edition page {edition_url}")
    if _fetch_file(session, manifest, "vacancy/tables", files[0], "vacancy/vacancy_tables.xlsx", warnings):
        log(f"  Vacancies ← {files[0].rsplit('/', 1)[-1]} (edition: {edition_url})")


# ---------------------------------------------------------------------------
# Stable direct downloads
# ---------------------------------------------------------------------------

def download_stable(session, manifest, warnings, log) -> None:
    targets = [
        ("ods/etr", config.ODS_REPORTS["etr"], "ods/etr.csv"),
        ("ods/ect", config.ODS_REPORTS["ect"], "ods/ect.csv"),
        ("ods/succ", config.ODS_REPORTS["succ"], "ods/succ.csv"),
        ("ods/eother", config.ODS_REPORTS["eother"], "ods/eother.csv"),
        ("ods/trust_icb_attribution", config.TRUST_ICB_ATTRIBUTION_URL, "ods/trust_icb_attribution.xls"),
        ("ods/system_mapping", config.SYSTEM_MAPPING_URL, "ods/system_mapping.xls"),
        ("ods/acute_trust_attribution", config.ACUTE_TRUST_ATTRIBUTION_URL, "ods/acute_trust_attribution.xls"),
        ("imd/file7", config.IMD_FILE7_URL, "imd/imd2025_file7.csv"),
        ("catchment/ohid", config.CATCHMENT_ODS_URL, "catchment/trust_catchment_2026.ods"),
        ("weather/haduk_england_tmean", config.HADUK_ENGLAND_TMEAN_URL, "weather/haduk_england_tmean.txt"),
        ("weather/hadcet_monthly", config.HADCET_MONTHLY_MEAN_URL, "weather/hadcet_monthly.txt"),
    ]
    for key, url, rel in targets:
        try:
            if _fetch_file(session, manifest, key, url, rel, warnings):
                log(f"  {key} ← {url}")
        except RuntimeError as exc:
            warnings.append(f"stable download failed: {key}: {exc}")


# ---------------------------------------------------------------------------
# ICB list via ORD API (paginated JSON)
# ---------------------------------------------------------------------------

def download_icbs(session, manifest, warnings, log) -> None:
    orgs, offset = [], 0
    while True:
        url = f"{config.ORD_API_BASE}?NonPrimaryRoleId=RO318&Limit=1000&Offset={offset}&_format=json"
        r = _get(session, url)
        batch = r.json().get("Organisations", [])
        orgs.extend(batch)
        if len(batch) < 1000:
            break
        offset += 1000
    local = config.RAW_DIR / "ods/icbs_ord.json"
    local.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(orgs, indent=1).encode()
    local.write_bytes(content)
    manifest["ods/icbs_ord"] = {
        "url": f"{config.ORD_API_BASE}?NonPrimaryRoleId=RO318 (paginated)",
        "local": "ods/icbs_ord.json",
        "sha256": hashlib.sha256(content).hexdigest(),
        "size": len(content),
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    log(f"  ICBs via ORD API: {len(orgs)} orgs (incl. history)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(log=print) -> dict:
    session = _session()
    manifest = _load_manifest()
    warnings: list[str] = []

    log("Downloading stable reference files (ODS, IMD, catchment, weather)…")
    download_stable(session, manifest, warnings, log)
    _save_manifest(manifest)

    log("Fetching ICB register from ORD API…")
    try:
        download_icbs(session, manifest, warnings, log)
    except Exception as exc:
        warnings.append(f"ICB ORD fetch failed: {exc}")
    _save_manifest(manifest)

    log("Scraping A&E archive pages and downloading monthly CSVs…")
    ae_months = download_ae(session, manifest, warnings, log)
    _save_manifest(manifest)

    log("Scraping RTT archive pages and downloading Full CSV zips…")
    rtt_months = download_rtt(session, manifest, warnings, log)
    _save_manifest(manifest)

    log("Fetching AmbSYS consolidated CSV…")
    download_ambulance(session, manifest, warnings, log)
    _save_manifest(manifest)

    log("Fetching NHS vacancy statistics…")
    try:
        download_vacancy(session, manifest, warnings, log)
    except Exception as exc:
        warnings.append(f"vacancy fetch failed: {exc}")
    _save_manifest(manifest)

    # Coverage report
    def gaps(months: list[str]) -> list[str]:
        if not months:
            return ["<none downloaded>"]
        out = []
        y, m = map(int, config.WINDOW_START.split("-"))
        last = months[-1]
        while f"{y:04d}-{m:02d}" <= last:
            key = f"{y:04d}-{m:02d}"
            if key not in months:
                out.append(key)
            m += 1
            if m == 13:
                y, m = y + 1, 1
        return out

    summary = {
        "ae_months": ae_months,
        "ae_gaps": gaps(ae_months),
        "rtt_months": rtt_months,
        "rtt_gaps": gaps(rtt_months),
        "warnings": warnings,
        "files": len(manifest),
    }
    log(f"A&E months: {len(ae_months)} ({ae_months[0] if ae_months else '—'} → "
        f"{ae_months[-1] if ae_months else '—'}), gaps: {summary['ae_gaps'] or 'none'}")
    log(f"RTT months: {len(rtt_months)} ({rtt_months[0] if rtt_months else '—'} → "
        f"{rtt_months[-1] if rtt_months else '—'}), gaps: {summary['rtt_gaps'] or 'none'}")
    for w in warnings:
        log(f"WARNING: {w}")
    return summary
