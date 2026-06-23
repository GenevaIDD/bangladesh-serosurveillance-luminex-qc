"""Background-well QC.

Background wells are the plate blanks (sample name ``Background0`` —
4 wells on the Bangladesh pilots). For each antigen we summarise the
signal across those wells. Reported metrics, per antigen:

- ``n_wells``       — number of Background wells contributing
- ``mean_mfi``      — mean MFI across Background wells (for the cross-plate plot/history)
- ``sd_mfi``        — sample SD (ddof=1) across Background wells
- ``cv``            — sd / mean (fraction, not %)
- ``max_mfi``       — max MFI across Background wells (kept for history; not shown in the table)
- ``mfis``          — sorted list of the individual Background-well MFIs
- ``iqr_lo`` / ``iqr_hi`` — Q1 / Q3 of this plate's Background-well MFIs
- ``cv_flag`` / ``max_flag`` — reference flags vs the thresholds (display
                    deferred — formal Background flagging rules are still
                    being finalized)
- ``excluded``      — True when the analyte is on the soft-flag list

NOTE: Background QC flagging rules are intentionally **not finalized**
(see BANGLADESH_TODO Section 4). ``cv_flag`` / ``max_flag`` are computed
for reference/history only and are not surfaced as pass/fail in the report.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def qc_background_levels(
    df: pd.DataFrame,
    cv_threshold: float = 0.25,
    max_mfi_threshold: float = 300.0,
    excluded_analytes: list[str] | None = None,
) -> pd.DataFrame:
    """Per-antigen Background QC table.

    Args:
        df: long-format data with [well, sample_name, analyte, mfi,
            well_type] (well_type == "background").
        cv_threshold: %CV reference cutoff (as a fraction; 0.25 = 25%).
        max_mfi_threshold: max-MFI reference cutoff in raw MFI units.
        excluded_analytes: analyte names to soft-flag in the output.

    Returns DataFrame keyed on ``analyte``; empty if the plate has no
    Background wells.
    """
    cols = [
        "analyte", "n_wells", "mean_mfi", "sd_mfi", "cv", "max_mfi",
        "mfis", "well_mfis", "iqr_lo", "iqr_hi", "cv_flag", "max_flag", "excluded",
    ]
    if df is None or df.empty or "well_type" not in df.columns:
        return pd.DataFrame(columns=cols)
    bg = df[df["well_type"] == "background"]
    if bg.empty:
        return pd.DataFrame(columns=cols)

    excluded = set(excluded_analytes or [])

    rows = []
    for analyte, g in bg.groupby("analyte", sort=False):
        vals = g["mfi"].dropna().astype(float)
        n = int(vals.count())
        arr = np.sort(vals.values)
        mean_mfi = float(arr.mean()) if n else float("nan")
        sd_mfi = float(vals.std(ddof=1)) if n > 1 else float("nan")
        max_mfi = float(arr.max()) if n else float("nan")
        cv = (sd_mfi / mean_mfi) if (n and mean_mfi > 0 and not np.isnan(sd_mfi)) else float("nan")
        if n >= 1:
            iqr_lo = float(np.percentile(arr, 25))
            iqr_hi = float(np.percentile(arr, 75))
        else:
            iqr_lo = iqr_hi = float("nan")
        well_mfis = {str(w): round(float(m), 1)
                     for w, m in zip(g["well"], g["mfi"]) if pd.notna(m)}
        rows.append({
            "analyte": analyte,
            "n_wells": n,
            "mean_mfi": mean_mfi,
            "sd_mfi": sd_mfi,
            "cv": cv,
            "max_mfi": max_mfi,
            "mfis": [round(float(v), 1) for v in arr],
            "well_mfis": well_mfis,
            "iqr_lo": iqr_lo,
            "iqr_hi": iqr_hi,
            "cv_flag": bool((cv if not np.isnan(cv) else 0) > cv_threshold),
            "max_flag": bool((max_mfi if not np.isnan(max_mfi) else 0) > max_mfi_threshold),
            "excluded": analyte in excluded,
        })
    return pd.DataFrame(rows, columns=cols)
