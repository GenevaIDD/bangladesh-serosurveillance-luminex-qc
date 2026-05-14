"""Bead-count QC: tier flags + per-(antigen × sample) matrix + problem list."""

from __future__ import annotations

import pandas as pd

from .config import BEAD_COUNT_MIN, BEAD_COUNT_WARN


def _tier(count, red_below: int, yellow_below: int) -> str:
    """Classify a bead count into 'red' / 'yellow' / 'green'.

    Reds: count < red_below.
    Yellows: red_below <= count < yellow_below.
    Greens: count >= yellow_below.
    NaN counts are classified as 'red' (worst case for QC).
    """
    if pd.isna(count):
        return "red"
    if count < red_below:
        return "red"
    if count < yellow_below:
        return "yellow"
    return "green"


def qc_bead_counts(
    df: pd.DataFrame,
    min_count: int | None = None,
    warn_count: int | None = None,
    config: dict | None = None,
) -> dict:
    """Build the Section-4 bead-count QC bundle.

    Args:
        df: long-format data with at least [well, sample_name, analyte, count, well_type]
        min_count: red/yellow boundary (count < min_count → RED). Defaults
            to ``config['qc_thresholds']['bead_count_min']`` or
            :data:`BEAD_COUNT_MIN`.
        warn_count: yellow/green boundary (count < warn_count → YELLOW,
            ≥ warn_count → GREEN). Defaults to
            ``config['qc_thresholds']['bead_count_warn']`` or
            :data:`BEAD_COUNT_WARN`.

    Returns dict with keys:
        flagged: legacy DataFrame of well-analyte pairs with count < min_count
        n_flagged: total number of red pairs
        red_threshold, yellow_threshold: integer cutoffs used
        matrix: wide DataFrame (analyte × well) of counts. Index =
            analyte. Columns = well IDs (e.g. A1, A2…) in order of
            first appearance. Cell = bead count.
        sample_labels: dict {well: sample_name} so the renderer can show
            human-readable column headers (and patient_id when present).
        tier_matrix: same shape as ``matrix`` but cells are 'red' /
            'yellow' / 'green'. Used by the renderer to colour cells.
        problems: long-format DataFrame [well, sample_name, analyte,
            count, tier] of every cell that is RED or YELLOW, sorted by
            tier (red first) then by well then by analyte.
    """
    qc = (config or {}).get("qc_thresholds", {})
    red_below = int(min_count if min_count is not None else qc.get("bead_count_min", BEAD_COUNT_MIN))
    yellow_below = int(warn_count if warn_count is not None else qc.get("bead_count_warn", BEAD_COUNT_WARN))
    if yellow_below < red_below:
        # User mis-set the thresholds; degrade gracefully — yellow band collapses.
        yellow_below = red_below

    # --- Legacy-compatible flagged list (red only) ---
    flagged = df[df["count"] < red_below][["well", "sample_name", "analyte", "count"]].copy()

    # --- Matrix (analyte × well) ---
    # Wells in their natural CSV order; preserve plate-row layout (A1..H12).
    well_order = list(df.drop_duplicates("well")["well"])
    analyte_order = list(df.drop_duplicates("analyte")["analyte"])

    sample_labels = (
        df.drop_duplicates("well").set_index("well")["sample_name"].to_dict()
    )

    matrix = (
        df.pivot_table(
            index="analyte", columns="well", values="count", aggfunc="first"
        )
        .reindex(index=analyte_order, columns=well_order)
    )

    tier_matrix = matrix.map(lambda c: _tier(c, red_below, yellow_below))

    # --- Problem list ---
    long_tiered = matrix.stack().reset_index()
    long_tiered.columns = ["analyte", "well", "count"]
    long_tiered["tier"] = long_tiered["count"].apply(lambda c: _tier(c, red_below, yellow_below))
    problems = long_tiered[long_tiered["tier"].isin(("red", "yellow"))].copy()
    problems["sample_name"] = problems["well"].map(sample_labels)
    # Sort: red first, then by well, then analyte
    tier_rank = {"red": 0, "yellow": 1, "green": 2}
    problems["_rank"] = problems["tier"].map(tier_rank)
    problems = (
        problems.sort_values(["_rank", "well", "analyte"])
        .drop(columns=["_rank"])
        .reset_index(drop=True)[["well", "sample_name", "analyte", "count", "tier"]]
    )

    # --- by_well legacy field (for any older report code that still
    # expects it) ---
    by_well = (
        df.groupby(["well", "sample_name", "well_type"])["count"]
        .median()
        .reset_index()
        .rename(columns={"count": "median_count"})
    )

    return {
        "flagged": flagged,
        "n_flagged": len(flagged),
        "red_threshold": red_below,
        "yellow_threshold": yellow_below,
        "matrix": matrix,
        "tier_matrix": tier_matrix,
        "sample_labels": sample_labels,
        "problems": problems,
        "by_well": by_well,
    }
