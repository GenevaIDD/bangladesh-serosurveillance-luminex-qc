"""PC (standard) replicate variability QC.

Each standard dilution point is run in duplicate (two wells). This module
measures the %CV between those replicate wells at every (pool × antigen ×
dilution) point, so noisy standards can be caught before the curve fit
averages the duplicates away.

Returns a tidy per-point table plus a per-(pool × antigen) summary.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def qc_pc_replicates(
    df: pd.DataFrame,
    cv_threshold: float = 0.20,
) -> dict:
    """Replicate-CV QC for the PC standard wells.

    Args:
        df: long-format data with [well, analyte, mfi, well_type] and the
            ``pc_pool`` / ``dilution`` / ``pc_single_point`` columns added by
            ``classify.classify_wells``.
        cv_threshold: flag a point when its replicate %CV (fraction) exceeds
            this.

    Returns dict:
        points:  DataFrame, one row per (pool × antigen × dilution) with
                 n_reps, mean_mfi, sd_mfi, cv, flag.
        summary: DataFrame, one row per (pool × antigen) with n_points,
                 n_flagged, max_cv, median_cv.
        n_flagged_points: scalar count of flagged points.
        n_points: total points with ≥ 2 replicates.
        threshold: the fraction used.
    """
    empty = {
        "points": pd.DataFrame(), "summary": pd.DataFrame(),
        "n_flagged_points": 0, "n_points": 0, "threshold": cv_threshold,
    }
    if df is None or df.empty or "well_type" not in df.columns:
        return empty
    pc = df[df["well_type"] == "pc"].copy()
    if "pc_single_point" in pc.columns:
        pc = pc[~pc["pc_single_point"].fillna(False)]
    if "pc_pool" not in pc.columns:
        pc["pc_pool"] = "PC"
    pc = pc.dropna(subset=["dilution"])
    if pc.empty:
        return empty

    rows = []
    for (pool, analyte, dil), g in pc.groupby(["pc_pool", "analyte", "dilution"], sort=False):
        vals = g["mfi"].dropna().astype(float)
        n = int(vals.count())
        if n < 2:
            continue  # need ≥2 replicate wells to assess variability
        mean = float(vals.mean())
        sd = float(vals.std(ddof=1))
        cv = (sd / mean) if mean > 0 else float("nan")
        rows.append({
            "pool": pool, "analyte": analyte, "dilution": float(dil),
            "n_reps": n, "mean_mfi": mean, "sd_mfi": sd, "cv": cv,
            "flag": bool(cv == cv and cv > cv_threshold),  # cv==cv guards NaN
        })
    points = pd.DataFrame(rows)
    if points.empty:
        return empty

    summary = (
        points.groupby(["pool", "analyte"], sort=False)
        .agg(
            n_points=("cv", "size"),
            n_flagged=("flag", "sum"),
            max_cv=("cv", "max"),
            median_cv=("cv", "median"),
        )
        .reset_index()
    )
    summary["n_flagged"] = summary["n_flagged"].astype(int)

    return {
        "points": points,
        "summary": summary,
        "n_flagged_points": int(points["flag"].sum()),
        "n_points": int(len(points)),
        "threshold": cv_threshold,
    }
