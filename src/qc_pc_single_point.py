"""Single-point positive-control QC (Cholera High / Low).

Some positive controls are **single-point** controls — loaded at one nominal
level rather than a serial-dilution series, so they cannot be fit to a 4PL
curve. On the Bangladesh plates these are the Cholera High / Low controls
(``classify.py`` flags them with ``pc_single_point=True``). Each control is
run in **duplicate wells** per plate.

This module extracts, per (control × antigen), the duplicate-well MFIs on the
current plate. The report tracks each control's MFI across plates (like the
Background QC overview) so inter-plate assay drift can be spotted. The two
controls are kept separate.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd


def control_label(raw: str) -> str:
    """Tidy a raw single-point pool label into a display name.

    'Cholera high/ low: High' -> 'Cholera High'
    'Cholera high/ low: Low'  -> 'Cholera Low'
    Anything without a recognisable level is returned cleaned-up as-is.
    """
    s = (raw or "").strip()
    if not s:
        return "Single-point control"
    if ":" in s:
        family, level = s.rsplit(":", 1)
        level = level.strip()
    else:
        family, level = s, ""
    # Drop the noisy "high/ low" descriptor from the family part.
    family = re.sub(r"high\s*/?\s*low", "", family, flags=re.IGNORECASE)
    family = family.strip(" :/-").strip()
    label = f"{family} {level}".strip()
    return label or s


def qc_pc_single_point(df: pd.DataFrame) -> dict:
    """Per (control × antigen) single-point PC MFIs for the current plate.

    Args:
        df: long-format data with [well, sample_name, analyte, mfi, well_type]
            and the ``pc_pool`` / ``pc_single_point`` columns from
            ``classify.classify_wells``.

    Returns dict:
        points:   DataFrame, one row per (control × antigen × well) —
                  columns [control, control_label, analyte, well, mfi].
        summary:  DataFrame, one row per (control × antigen) — columns
                  [control, control_label, analyte, n_wells, mean_mfi,
                  sd_mfi, cv].
        controls: ordered list of distinct raw control labels on the plate.
    """
    empty_pts = pd.DataFrame(
        columns=["control", "control_label", "analyte", "well", "mfi"])
    empty_sum = pd.DataFrame(
        columns=["control", "control_label", "analyte", "n_wells",
                 "mean_mfi", "sd_mfi", "cv"])
    if df is None or df.empty or "well_type" not in df.columns:
        return {"points": empty_pts, "summary": empty_sum, "controls": []}
    if "pc_single_point" not in df.columns:
        return {"points": empty_pts, "summary": empty_sum, "controls": []}

    sp = df[(df["well_type"] == "pc") & df["pc_single_point"].fillna(False)]
    if sp.empty:
        return {"points": empty_pts, "summary": empty_sum, "controls": []}

    rows = []
    for r in sp.itertuples(index=False):
        rows.append({
            "control": r.pc_pool,
            "control_label": control_label(r.pc_pool),
            "analyte": r.analyte,
            "well": r.well,
            "mfi": float(r.mfi) if pd.notna(r.mfi) else np.nan,
        })
    points = pd.DataFrame(rows, columns=["control", "control_label",
                                         "analyte", "well", "mfi"])

    summ = []
    for (ctrl, an), g in points.groupby(["control", "analyte"], sort=False):
        vals = g["mfi"].dropna().astype(float)
        n = int(vals.count())
        mean = float(vals.mean()) if n else float("nan")
        sd = float(vals.std(ddof=1)) if n > 1 else float("nan")
        cv = (sd / mean) if (n and mean > 0 and not np.isnan(sd)) else float("nan")
        summ.append({
            "control": ctrl,
            "control_label": g["control_label"].iloc[0],
            "analyte": an,
            "n_wells": n,
            "mean_mfi": mean,
            "sd_mfi": sd,
            "cv": cv,
        })
    summary = pd.DataFrame(summ, columns=["control", "control_label", "analyte",
                                          "n_wells", "mean_mfi", "sd_mfi", "cv"])
    controls = list(points["control"].dropna().drop_duplicates())
    return {"points": points, "summary": summary, "controls": controls}
