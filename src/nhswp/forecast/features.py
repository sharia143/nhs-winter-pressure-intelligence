"""Trust clustering on seasonal shape + volume.

k-means over 13 z-scored features: the 12-dimensional month-of-year profile
(each trust's mean deviation from its own level, on the transformed scale)
plus log mean Type-1 attendances. k chosen from 3-6 by silhouette score.
Clustering is on seasonal *shape* — deprivation and performance level belong
in the equity analysis, not here (they would contaminate the pooling
rationale the clusters exist for).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

RANDOM_STATE = 42


def seasonal_profile(series: pd.Series) -> np.ndarray | None:
    """12-vector of mean deviation from trust level by calendar month.

    series: indexed by month_key (yyyymm int), transformed scale, may contain NaN.
    """
    if series.dropna().shape[0] < 24:
        return None
    df = series.dropna().rename("x").reset_index()
    df["moy"] = df["month_key"] % 100
    # Deviation from a 12-month centred moving level; fall back to overall mean
    level = series.rolling(12, center=True, min_periods=8).mean()
    dev = (series - level).rename("dev").reset_index()
    dev["moy"] = dev["month_key"] % 100
    prof = dev.groupby("moy")["dev"].mean()
    if prof.isna().any():
        overall = df.groupby("moy")["x"].mean() - df["x"].mean()
        prof = prof.fillna(overall)
    return prof.reindex(range(1, 13)).to_numpy()


def cluster_trusts(
    profiles: dict[str, np.ndarray], volumes: dict[str, float]
) -> tuple[pd.DataFrame, int]:
    """Return (org_code -> cluster_id table, chosen k)."""
    orgs = [o for o, p in profiles.items() if p is not None and not np.isnan(p).any()]
    X = np.array([np.append(profiles[o], np.log(max(volumes[o], 1.0))) for o in orgs])
    X = StandardScaler().fit_transform(X)

    best_k, best_score, best_labels = None, -np.inf, None
    for k in range(3, 7):
        if len(orgs) <= k + 1:
            break
        km = KMeans(n_clusters=k, n_init=10, random_state=RANDOM_STATE).fit(X)
        score = silhouette_score(X, km.labels_)
        if score > best_score:
            best_k, best_score, best_labels = k, score, km.labels_
    out = pd.DataFrame({"org_code": orgs, "cluster_id": best_labels})
    return out, int(best_k)


def pooled_seasonal_index(
    series_by_org: dict[str, pd.Series], clusters: pd.DataFrame
) -> dict[int, pd.Series]:
    """Cluster-level seasonal index: median monthly deviation across member
    trusts, normalised to mean zero (transformed/additive scale)."""
    cluster_of = dict(zip(clusters["org_code"], clusters["cluster_id"]))
    rows = []
    for org, series in series_by_org.items():
        if org not in cluster_of:
            continue
        level = series.rolling(12, center=True, min_periods=8).mean()
        dev = series - level
        for mk, v in dev.dropna().items():
            rows.append({"cluster_id": cluster_of[org], "moy": mk % 100, "dev": v})
    df = pd.DataFrame(rows)
    out = {}
    for cid, grp in df.groupby("cluster_id"):
        idx = grp.groupby("moy")["dev"].median().reindex(range(1, 13)).fillna(0.0)
        out[int(cid)] = idx - idx.mean()
    return out
