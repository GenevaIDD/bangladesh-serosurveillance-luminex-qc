"""Negative-control well monitoring.

NC wells are an optional sample type — a known seronegative pool, named
``NC*`` or ``Negative*`` on the plate.  Background wells (``^Background``)
are a separate concept and are not included here.

The pilot plate has no NC wells, so this module returns an empty frame.
When a future plate adds an NC sample, ``qc_nc_levels`` extracts its MFI
per analyte and the report renders the result as a heatmap.  No
threshold flagging at this stage; the legacy MPOX app likewise reported
NC MFI without auto-flagging.
"""

from __future__ import annotations

import pandas as pd


def qc_nc_levels(df: pd.DataFrame) -> pd.DataFrame:
    """Return NC well MFI per (well, analyte).

    Args:
        df: long-format data with at least [well, sample_name, analyte,
            mfi, well_type] (well_type == "nc" identifies NC wells).

    Returns DataFrame with columns [well, sample_name, analyte, mfi].
    Empty if the plate has no NC wells.
    """
    if df is None or df.empty or "well_type" not in df.columns:
        return pd.DataFrame(columns=["well", "sample_name", "analyte", "mfi"])
    nc = df[df["well_type"] == "nc"]
    if nc.empty:
        return pd.DataFrame(columns=["well", "sample_name", "analyte", "mfi"])
    return nc[["well", "sample_name", "analyte", "mfi"]].reset_index(drop=True)
