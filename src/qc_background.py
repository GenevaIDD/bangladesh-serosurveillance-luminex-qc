"""Background-well QC.

Background wells are the plate blanks in Row A (A11 / A12 on the
pilot).  When the plate has no named NC sample, the legacy MPOX NC
checks are applied here instead.  Reported metrics, per antigen:

- ``n_wells``       — number of Background wells contributing
- ``mean_mfi``      — mean MFI across Background wells
- ``sd_mfi``        — sample SD (ddof=1) across Background wells
- ``cv``            — sd / mean (fraction, not %)
- ``max_mfi``       — max MFI across Background wells
- ``cv_flag``       — True when ``cv`` exceeds the threshold
- ``max_flag``      — True when ``max_mfi`` exceeds the threshold
- ``excluded``      — True when the analyte is on the soft-flag list
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def qc_background_levels(
    df: pd.DataFrame,
    cv_threshold: float = 0.25,
    max_mfi_threshold: float = 100.0,
    excluded_analytes: list[str] | None = None,
) -> pd.DataFrame:
    """Per-antigen Background QC table.

    Args:
        df: long-format data with [well, sample_name, analyte, mfi,
            well_type] (well_type == "background").
        cv_threshold: %CV cutoff (as a fraction; 0.25 = 25%).
        max_mfi_threshold: max-MFI cutoff in raw MFI units.
        excluded_analytes: analyte names to soft-flag in the output.

    Returns DataFrame keyed on ``analyte``; empty if the plate has no
    Background wells.
    """
    cols = [
        "analyte", "n_wells", "mean_mfi", "sd_mfi", "cv", "max_mfi",
        "cv_flag", "max_flag", "excluded",
    ]
    if df is None or df.empty or "well_type" not in df.columns:
        return pd.DataFrame(columns=cols)
    bg = df[df["well_type"] == "background"]
    if bg.empty:
        return pd.DataFrame(columns=cols)

    excluded = set(excluded_analytes or [])
    grouped = bg.groupby("analyte", sort=False)["mfi"]
    summary = grouped.agg(
        n_wells="count",
        mean_mfi="mean",
        sd_mfi=lambda s: float(s.std(ddof=1)) if s.count() > 1 else float("nan"),
        max_mfi="max",
    ).reset_index()
    summary["cv"] = np.where(
        summary["mean_mfi"] > 0,
        summary["sd_mfi"] / summary["mean_mfi"],
        np.nan,
    )
    summary["cv_flag"] = summary["cv"].fillna(0) > cv_threshold
    summary["max_flag"] = summary["max_mfi"].fillna(0) > max_mfi_threshold
    summary["excluded"] = summary["analyte"].isin(excluded)
    return summary[cols]
