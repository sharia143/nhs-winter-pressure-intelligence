"""Single source of truth for paths, URLs, era boundaries and schema contracts.

Every other module reads from here. NHS England file URLs carry random hash
suffixes and are NOT stable; only the yearly archive *pages* are stable, so
the download stage scrapes those pages for hrefs at run time. The handful of
URLs that ARE stable (ODS getReport endpoints, gov.uk assets, Met Office
datasets) are pinned directly.
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
STAGING_DIR = DATA_DIR / "staging"
STATE_DIR = DATA_DIR / "state"
WAREHOUSE_DIR = REPO_ROOT / "warehouse"
WAREHOUSE_DB = WAREHOUSE_DIR / "nhswp.duckdb"
OUTPUTS_DIR = REPO_ROOT / "outputs"
FIGURES_DIR = OUTPUTS_DIR / "figures"
POWERBI_DATA_DIR = REPO_ROOT / "powerbi" / "data"
REPORTS_DIR = REPO_ROOT / "reports"
DOCS_DIR = REPO_ROOT / "docs"
MANIFEST_PATH = RAW_DIR / "manifest.json"
STAGE_STATUS_PATH = STATE_DIR / "stage_status.json"
PROGRESS_MD = REPO_ROOT / "PROGRESS.md"

# ---------------------------------------------------------------------------
# Analysis window
# ---------------------------------------------------------------------------
WINDOW_START = "2021-04"           # first month ingested
# End is discovered dynamically from what the publications actually offer.

# Winters held out of training for the forecast backtest.
HOLDOUT_WINTERS = ["2024-25", "2025-26"]

# ---------------------------------------------------------------------------
# Era boundaries / known discontinuities
# ---------------------------------------------------------------------------
# NHS England moved the monthly A&E publication onto ECDS-derived methodology
# from November 2025 ("ECDS Publication Changes November 2025" note).
ECDS_BREAK_MONTH = "2025-11"

# The whole 2021-22 A&E year was re-issued on 12 May 2022 (revised files).
AE_2021_REVISION_NOTE = "2021-22 files revised 12/05/2022; revised versions used"

# ICB reorganisation: April 2026 mergers closed 12 ICB codes and created 6.
ICB_MERGER_MONTH = "2026-04"

# ---------------------------------------------------------------------------
# Parser versions — bump to force re-ingest of a source
# ---------------------------------------------------------------------------
PARSER_VERSIONS = {
    "ae": 1,
    "rtt": 2,   # v2: band-sum fallback for blank Total column; C_999 rollup excluded from bands
    "ambsys": 2,  # v2: metric columns forced to float64
    "ods": 1,
    "imd": 1,
    "catchment": 1,
    "weather": 1,
    "vacancy": 1,
}

# ---------------------------------------------------------------------------
# Scrape targets: stable landing/archive pages
# ---------------------------------------------------------------------------
NHSE_STATS = "https://www.england.nhs.uk/statistics/statistical-work-areas"

# One archive page per financial year; scraped for monthly CSV hrefs.
AE_ARCHIVE_PAGES = {
    fy: f"{NHSE_STATS}/ae-waiting-times-and-activity/ae-attendances-and-emergency-admissions-{fy}/"
    for fy in ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26", "2026-27"]
}

RTT_ARCHIVE_PAGES = {
    fy: f"{NHSE_STATS}/rtt-waiting-times/rtt-data-{fy}/"
    for fy in ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26", "2026-27"]
}

AMBULANCE_LANDING = f"{NHSE_STATS}/ambulance-quality-indicators/"

VACANCY_SERIES_PAGE = (
    "https://digital.nhs.uk/data-and-information/publications/statistical/nhs-vacancies-survey"
)

# ---------------------------------------------------------------------------
# Stable direct downloads
# ---------------------------------------------------------------------------
ODS_REPORTS = {
    # NHS Trusts (headerless 27-col CSV, PrimaryRole RO197)
    "etr": "https://www.odsdatasearchandexport.nhs.uk/api/getReport?report=etr",
    # Care Trusts
    "ect": "https://www.odsdatasearchandexport.nhs.uk/api/getReport?report=ect",
    # Successor organisation mappings (mergers)
    "succ": "https://www.odsdatasearchandexport.nhs.uk/api/getReport?report=succ",
    # Strategic partnerships file: ICBs live inside this one
    "eother": "https://www.odsdatasearchandexport.nhs.uk/api/getReport?report=eother",
}
ORD_API_BASE = "https://directory.spineservices.nhs.uk/ORD/2-0-0/organisations"

TRUST_ICB_ATTRIBUTION_URL = (
    "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2023/02/"
    "Trust-ICB-Attribution-File.xls"
)
# Published alongside the 2025-26 A&E statistics (April 2026 uploads):
# provider → system/ICB mapping on post-April-2026 ICB footprints.
SYSTEM_MAPPING_URL = (
    "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2026/04/System-Mapping.xls"
)
ACUTE_TRUST_ATTRIBUTION_URL = (
    "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2026/04/"
    "Acute-Trust-Attribution-File.xls"
)

IMD_FILE7_URL = (
    "https://assets.publishing.service.gov.uk/media/691ded56d140bbbaa59a2a7d/"
    "File_7_IoD2025_All_Ranks_Scores_Deciles_Population_Denominators.csv"
)

CATCHMENT_ODS_URL = (
    "https://assets.publishing.service.gov.uk/media/6a199144050971fbebf3bc3f/"
    "nhs-acute-hospital-trust-catchment-populations-data_tables-april-2026.ods"
)

HADUK_ENGLAND_TMEAN_URL = (
    "https://www.metoffice.gov.uk/pub/data/weather/uk/climate/datasets/Tmean/date/England.txt"
)
HADCET_MONTHLY_MEAN_URL = (
    "https://www.metoffice.gov.uk/hadobs/hadcet/data/meantemp_monthly_totals.txt"
)

# ---------------------------------------------------------------------------
# Performance standards
# ---------------------------------------------------------------------------
FOUR_HOUR_CONSTITUTIONAL_STANDARD = 0.95
# 2025/26 NHS planning guidance interim ambition for A&E 4-hour performance.
FOUR_HOUR_INTERIM_THRESHOLD = 0.78
RTT_18WK_STANDARD = 0.92

# AmbSYS metric codes (from the 30 Jan 2026 AmbSYS specification)
AMBSYS_METRICS = {
    "A25": "cat1_mean_sec",
    "A26": "cat1_90th_sec",
    "A31": "cat2_mean_sec",
    "A32": "cat2_90th_sec",
    "A34": "cat3_mean_sec",
    "A35": "cat3_90th_sec",
    "A37": "cat4_mean_sec",
    "A38": "cat4_90th_sec",
    "A8": "cat1_incidents",
    "A10": "cat2_incidents",
    "A11": "cat3_incidents",
    "A12": "cat4_incidents",
    "A114": "call_answer_90th_sec",
}

# ---------------------------------------------------------------------------
# Schema contracts (normalised column name -> dtype kind)
# 'i' int64 (nullable Int64), 'f' float64, 's' string, 'b' boolean
# ---------------------------------------------------------------------------
SCHEMA_AE = {
    "month_key": "i",
    "org_code_published": "s",
    "org_name": "s",
    "parent_org": "s",
    "att_type1": "i",
    "att_type2": "i",
    "att_other": "i",
    "att_booked_type1": "i",
    "att_booked_type2": "i",
    "att_booked_other": "i",
    "over4hr_type1": "i",
    "over4hr_type2": "i",
    "over4hr_other": "i",
    "over4hr_booked_type1": "i",
    "over4hr_booked_type2": "i",
    "over4hr_booked_other": "i",
    "dta_4to12hr": "i",
    "dta_12hr_plus": "i",
    "emadm_type1": "i",
    "emadm_type2": "i",
    "emadm_other": "i",
    "emadm_not_ae": "i",
}

SCHEMA_RTT_BANDS = {
    "month_key": "i",
    "org_code_published": "s",
    "org_name": "s",
    "treatment_function_code": "s",
    "treatment_function": "s",
    "band_weeks_low": "i",
    "band_weeks_high": "i",   # nullable: open-ended top band
    "pathway_count": "f",
}

SCHEMA_AMBSYS = {
    "month_key": "i",
    "org_code_published": "s",
    "org_name": "s",
    "region": "s",
}


def month_key(year: int, month: int) -> int:
    """yyyymm integer key used across the warehouse."""
    return year * 100 + month
