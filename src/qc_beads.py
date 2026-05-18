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


def bead_problem_summary(
    bead_qc: dict,
    well_types: dict[str, str] | None = None,
    fraction_threshold: float = 0.20,
) -> dict:
    """Aggregate the bead-count QC matrix into per-antigen and per-sample
    "≥ X% problematic" summaries.

    An antigen is "problem" when at least ``fraction_threshold`` of its
    wells fall into the red or yellow tier. Similarly for samples.

    Args:
        bead_qc: dict returned by :func:`qc_bead_counts`.
        well_types: optional {well -> well_type} map.  When provided,
            specimen wells are the only ones that count toward the
            sample summary (Standards / Background / NC are excluded
            from the denominator so that the threshold reflects
            unknown-sample QC).  When omitted, every well counts.
        fraction_threshold: ≥ this fraction of bad wells flags the
            antigen / sample.

    Returns dict:
        antigen_summary: DataFrame per antigen with n_wells,
            n_problem, frac_problem, is_problem, problem_wells.
        sample_summary:  DataFrame per well with n_analytes,
            n_problem, frac_problem, is_problem, problem_analytes,
            sample_name, well_type.
        n_problem_antigens / n_problem_samples: ints.
        threshold: the fraction used.
    """
    matrix = bead_qc.get("matrix")
    tier_matrix = bead_qc.get("tier_matrix")
    sample_labels = bead_qc.get("sample_labels", {}) or {}

    empty = pd.DataFrame()
    if matrix is None or matrix.empty or tier_matrix is None:
        return {
            "antigen_summary": empty,
            "sample_summary": empty,
            "n_problem_antigens": 0,
            "n_problem_samples": 0,
            "threshold": fraction_threshold,
        }

    well_types = well_types or {}
    is_problem_cell = tier_matrix.isin(("red", "yellow"))

    # Per antigen — denominator is all wells where the antigen was measured.
    ag_rows = []
    for analyte in tier_matrix.index:
        row = is_problem_cell.loc[analyte]
        n_wells = int(row.shape[0])
        n_problem = int(row.sum())
        frac = (n_problem / n_wells) if n_wells else 0.0
        problem_wells = [w for w, bad in row.items() if bad]
        ag_rows.append({
            "analyte": analyte,
            "n_wells": n_wells,
            "n_problem": n_problem,
            "frac_problem": round(frac, 4),
            "is_problem": frac >= fraction_threshold,
            "problem_wells": ";".join(problem_wells),
            "problem_well_labels": ";".join(
                f"{w} ({sample_labels.get(w, '')})".strip() for w in problem_wells
            ),
        })
    antigen_summary = pd.DataFrame(ag_rows)

    # Per sample — count only specimen wells when well_types is provided,
    # otherwise count all columns.
    if well_types:
        sample_wells = [w for w in tier_matrix.columns if well_types.get(w) == "specimen"]
    else:
        sample_wells = list(tier_matrix.columns)

    sm_rows = []
    for well in sample_wells:
        col = is_problem_cell[well]
        n_analytes = int(col.shape[0])
        n_problem = int(col.sum())
        frac = (n_problem / n_analytes) if n_analytes else 0.0
        problem_analytes = [a for a, bad in col.items() if bad]
        sm_rows.append({
            "well": well,
            "sample_name": sample_labels.get(well, ""),
            "well_type": well_types.get(well, ""),
            "n_analytes": n_analytes,
            "n_problem": n_problem,
            "frac_problem": round(frac, 4),
            "is_problem": frac >= fraction_threshold,
            "problem_analytes": ";".join(problem_analytes),
        })
    sample_summary = pd.DataFrame(sm_rows)

    return {
        "antigen_summary": antigen_summary,
        "sample_summary": sample_summary,
        "n_problem_antigens": int(antigen_summary["is_problem"].sum()) if not antigen_summary.empty else 0,
        "n_problem_samples": int(sample_summary["is_problem"].sum()) if not sample_summary.empty else 0,
        "threshold": fraction_threshold,
    }
