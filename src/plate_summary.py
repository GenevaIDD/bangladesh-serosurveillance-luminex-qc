"""Plate-level summary statistics."""

from __future__ import annotations

import pandas as pd


def plate_summary(df: pd.DataFrame) -> dict:
    """Compute plate-level summary stats.

    Returns dict with:
        well_counts: dict of well_type -> count (unique wells)
        total_wells: total unique wells
        analyte_list: list of analytes present
    """
    well_types = df.groupby("well_type")["well"].nunique().to_dict()
    return {
        "well_counts": well_types,
        "total_wells": df["well"].nunique(),
        "analyte_list": sorted(df["analyte"].unique().tolist()),
    }
