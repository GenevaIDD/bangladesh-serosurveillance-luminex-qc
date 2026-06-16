"""Main QC pipeline — orchestrates parsing, QC, and report generation."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from .parse_xponent import parse_xponent_csv
from .classify import classify_wells
from .qc_beads import qc_bead_counts, bead_problem_summary
from .qc_nc import qc_nc_levels
from .qc_background import qc_background_levels
from .qc_pc_replicates import qc_pc_replicates
from .qc_standard_curve import (
    fit_standard_curves,
    compute_concentrations,
    compute_net_mfi,
    compute_in_range_table,
    compute_pct_in_range_per_antigen,
    range_problem_summary,
    build_pool_map,
    _pool_slug,
)
from .settings import get_excluded_analytes
from .qc_history import load_history, append_history, save_history
from .parse_layout import read_plate_layout, build_layout
from .plate_summary import plate_summary
from .report import generate_report
from .settings import load_config


def run_pipeline(
    csv_path: str | Path,
    output_dir: str | Path | None = None,
    layout_path: str | Path | None = None,
    inputfile_path: str | Path | None = None,
    history_dir: str | Path | None = None,
    config: dict | None = None,
    plate_order: list | None = None,
) -> Path:
    """Run the full QC pipeline on a single plate CSV.

    Args:
        csv_path: path to xPONENT CSV file
        output_dir: where to write report and CSVs (defaults to csv parent dir)
        layout_path: optional path to plate layout xlsx
        history_dir: where to store history JSON files (defaults to output_dir/history)
        config: optional config dict (from settings.load_config); loaded if not provided

    Returns path to the generated HTML report.
    """
    csv_path = Path(csv_path)
    if output_dir is None:
        output_dir = csv_path.parent
    output_dir = Path(output_dir)
    if history_dir is None:
        history_dir = output_dir / "history"

    # Load config if not provided
    if config is None:
        config = load_config()

    # 1. Parse CSV
    parsed = parse_xponent_csv(csv_path)
    metadata = parsed["metadata"]
    data = parsed["data"]

    # 2. Optional layout enrichment — run BEFORE classify so the
    # input file's authoritative `Type` column (carried into
    # ``plate_well_type``) can override sample-name regex
    # classification (e.g. a `Type=Control` well that the operator
    # labelled `NI7`).
    # New (Uvira) path: inputfile CSV (well → plate_well_type, barcode)
    # + optional Box xlsx (barcode → patient_id), merged via
    # build_layout. Legacy path: a Sample-list xlsx via
    # read_plate_layout(layout_path).
    if inputfile_path:
        layout = build_layout(inputfile_path, box_xlsx_path=layout_path)
        if layout is not None and not layout.empty:
            # sample_id = patient_id when known, else on-plate barcode
            layout = layout.copy()
            layout["sample_id"] = layout["patient_id"].where(
                layout["patient_id"].astype(str).str.len() > 0,
                layout["barcode"],
            )
            keep_cols = [c for c in (
                "well", "plate_well_type", "sample_id", "barcode",
                "patient_id", "box_id",
            ) if c in layout.columns]
            data = data.merge(layout[keep_cols], on="well", how="left")
    elif layout_path:
        layout = read_plate_layout(layout_path)
        if layout is not None and any(c in layout.columns for c in ("sample_id", "visit_date", "dilution")):
            # Rename the layout's `dilution` column so it survives the
            # merge intact and can override classify_wells' regex-
            # derived dilution after step 3 below.
            if "dilution" in layout.columns:
                layout = layout.rename(columns={"dilution": "dilution_layout"})
            data = data.merge(layout, on="well", how="left")

    # 3. Classify wells. When ``plate_well_type`` is present (the
    # input file was uploaded), classify_wells uses it as the
    # primary signal; otherwise it falls back to sample-name regex
    # matching against the configured patterns.
    data = classify_wells(data, config=config)

    # 4. Legacy-path per-well dilution override — runs after classify
    # so it overrides the regex-derived Standard{N} dilution mapping.
    if "dilution_layout" in data.columns:
        mask = data["dilution_layout"].notna()
        data.loc[mask, "dilution"] = pd.to_numeric(
            data.loc[mask, "dilution_layout"], errors="coerce"
        )
        data = data.drop(columns=["dilution_layout"])

    # 4. QC: bead counts
    bead_qc = qc_bead_counts(data, config=config)

    # 5. QC: 4PL standard curves. Use the per-plate analyte list captured
    # by parse_xponent so the panel is always authoritative for this run
    # (Section 2 — auto-derivation from the CSV header).
    plate_antigens = list(metadata.get("analytes") or [])
    fits = fit_standard_curves(data, config=config, antigens=plate_antigens or None)

    # 6. Compute specimen AU and Net MFI.
    # (Legacy QC modules — qc_pc_replicates, qc_nc_levels, qc_kit_controls
    # — were removed in Session 4: Uvira plates have no PC duplicates, no
    # MagPix kit-control beads, and the row-A "Background" wells are
    # already classified as NC; their MFI is reported alongside specimens.)
    # Antigen → pool mapping for specimen scoring. In the default per-pool
    # mode this is a single scoring pool for every antigen (no per-antigen
    # auto-selection); in auto_select mode it's the pathogen match + best fit.
    pool_map = build_pool_map(fits, antigens=None, config=config)
    specimen_results = compute_concentrations(data, fits, config=config, pool_map=pool_map)
    data = compute_net_mfi(data)
    if "net_mfi" in data.columns:
        specimen_results["net_mfi"] = data.loc[specimen_results.index, "net_mfi"]

    # 9b. Section-3 deliverables: per-(antigen × sample) range table
    # and the per-antigen "% samples in linear range" summary, scored against
    # the mapped pool.
    excluded_analytes = get_excluded_analytes(config)
    in_range = compute_in_range_table(data, fits, excluded_analytes=excluded_analytes,
                                      config=config, pool_map=pool_map)
    pct_in_range = compute_pct_in_range_per_antigen(in_range, excluded_analytes=excluded_analytes)

    # 9c. NC well levels (empty when the plate has no NC samples).
    nc_levels = qc_nc_levels(data)

    # 9d. Section-8 summaries: "≥ X% problematic" counts for bead-count
    # and range tables, plus Background QC.
    qc_thresh = config.get("qc_thresholds", {})
    problem_frac = float(qc_thresh.get("problem_fraction_threshold", 0.20))
    well_types_map = (
        data.drop_duplicates("well").set_index("well")["well_type"].to_dict()
        if "well_type" in data.columns else {}
    )
    bead_summary = bead_problem_summary(
        bead_qc, well_types=well_types_map, fraction_threshold=problem_frac
    )
    range_summary = range_problem_summary(
        in_range, fraction_threshold=problem_frac, excluded_analytes=excluded_analytes
    )
    bg_levels = qc_background_levels(
        data,
        cv_threshold=float(qc_thresh.get("bg_cv_threshold", 0.25)),
        max_mfi_threshold=float(qc_thresh.get("bg_max_mfi", 300)),
        excluded_analytes=excluded_analytes,
    )
    # PC replicate variability — %CV between duplicate standard wells.
    pc_replicates = qc_pc_replicates(
        data, cv_threshold=float(qc_thresh.get("pc_cv_threshold", 0.20)),
    )

    # 10. Plate summary
    summary = plate_summary(data)

    # 8. History — load, append, save. Single pool on Uvira but the
    # per-pool dict structure is preserved for forward-compat.
    history_std: dict = {}
    history_fit: dict = {}
    for pool_name in fits:
        pool_slug = pool_name.replace(" ", "_")
        std_path = Path(history_dir) / f"std_curve_history_{pool_slug}.json"
        h = load_history(std_path)
        new_std = _build_std_history(metadata, fits[pool_name], pool_name)
        if not new_std.empty:
            h = append_history(h, new_std, ["plate_id", "analyte", "dilution"])
            save_history(h, std_path)
        history_std[pool_name] = h

        fit_path = Path(history_dir) / f"fit_history_{pool_slug}.json"
        h = load_history(fit_path)
        # Capture box(es) on this plate so the picker legend can compose
        # a labelled plate name (e.g. "PLATE_05112026_RUN000 · Box1").
        box_ids_str = ""
        if "box_id" in data.columns:
            boxes = sorted({b for b in data["box_id"].dropna().astype(str).unique() if b})
            box_ids_str = ",".join(boxes)
        new_fit = _build_fit_history(metadata, fits[pool_name], pool_name, box_ids=box_ids_str)
        if not new_fit.empty:
            h = append_history(h, new_fit, ["plate_id", "analyte"])
            save_history(h, fit_path)
        history_fit[pool_name] = h
    # Background-level history: one row per (plate × antigen) with the
    # current plate's Background mean / SD / CV / max MFI. Powers the
    # cross-plate Background overview scatter (x = antigen,
    # y = mean MFI, colour = plate).
    bg_history_path = Path(history_dir) / "background_history.json"
    bg_history_existing = load_history(bg_history_path)
    new_bg = _build_background_history(metadata, bg_levels)
    if not new_bg.empty:
        history_background = append_history(
            bg_history_existing, new_bg, ["plate_id", "analyte"]
        )
        save_history(history_background, bg_history_path)
    else:
        history_background = bg_history_existing

    # Specimen-MFI history: one row per (plate × specimen well × antigen)
    # with the IN_RANGE / BELOW_RANGE / ABOVE_RANGE / NO_FIT status from
    # the current run. Used by the curve picker to render a per-antigen
    # historical rug in grey alongside the current plate.
    spec_hist_path = Path(history_dir) / "specimen_mfi_history.json"
    spec_hist_existing = load_history(spec_hist_path)
    new_spec = _build_specimen_mfi_history(metadata, in_range)
    if not new_spec.empty:
        history_specimens = append_history(
            spec_hist_existing, new_spec, ["plate_id", "well", "analyte"]
        )
        save_history(history_specimens, spec_hist_path)
    else:
        history_specimens = spec_hist_existing

    # NC well history: persist mean NC MFI per (plate × well × antigen)
    # so we can spot cross-plate drift when a future plate has an NC
    # sample. The legacy MagPix kit-bead "NC" check does not apply; this
    # is the named-NC-sample history.
    nc_history_path = Path(history_dir) / "nc_well_history.json"
    history_nc_existing = load_history(nc_history_path)
    new_nc = _build_nc_history(metadata, nc_levels)
    if not new_nc.empty:
        history_nc = append_history(
            history_nc_existing, new_nc, ["plate_id", "well", "analyte"]
        )
        save_history(history_nc, nc_history_path)
    else:
        history_nc = history_nc_existing

    # 9. Generate the Uvira QC report.
    report_name = f"QC_{metadata['plate_id']}.html"
    report_path = output_dir / report_name

    generate_report(
        metadata=metadata,
        data=data,
        bead_qc=bead_qc,
        fits=fits,
        specimen_results=specimen_results,
        summary=summary,
        in_range=in_range,
        pct_in_range=pct_in_range,
        nc_levels=nc_levels,
        pc_replicates=pc_replicates,
        history_std=history_std,
        history_nc=history_nc,
        history_fit=history_fit,
        history_specimens=history_specimens,
        history_background=history_background,
        output_path=report_path,
        plate_order=plate_order,
        config=config,
    )

    # 13. Export specimen results CSV
    if not specimen_results.empty:
        csv_out = output_dir / f"specimens_{metadata['plate_id']}.csv"
        export_df = specimen_results.copy()

        pools = list(fits.keys())
        multi_pool = len(pools) > 1

        if multi_pool:
            # Per-pool AU columns + censored flags
            for pool_name in pools:
                slug = pool_name.replace(" ", "_")
                rau_col = f"rau_{slug}"
                lloq_col = f"below_lloq_{slug}"
                uloq_col = f"above_uloq_{slug}"
                au_col = f"AU_{slug}"
                cens_col = f"au_censored_{slug}"

                if rau_col in export_df.columns:
                    export_df = export_df.rename(columns={rau_col: au_col})
                if lloq_col in export_df.columns and uloq_col in export_df.columns:
                    export_df[cens_col] = "none"
                    export_df.loc[export_df[lloq_col], cens_col] = "left"
                    export_df.loc[export_df[uloq_col], cens_col] = "right"
            # Also rename plain rau → AU (first pool default)
            if "rau" in export_df.columns:
                export_df = export_df.rename(columns={"rau": "AU"})
        else:
            export_df = export_df.rename(columns={"rau": "AU"})

        # Add au_censored from the default (plain) columns
        if "below_lloq" in export_df.columns and "above_uloq" in export_df.columns:
            export_df["au_censored"] = "none"
            export_df.loc[export_df["below_lloq"], "au_censored"] = "left"
            export_df.loc[export_df["above_uloq"], "au_censored"] = "right"

        export_df.to_csv(csv_out, index=False, encoding="utf-8")

    # 13b. Clean per-plate results CSV — the tidy, analysis-ready table
    # (one row per specimen well × antigen) with the selected pool, RAU/AU,
    # and range status. This is what the master export concatenates.
    clean = _build_clean_results(metadata, in_range, specimen_results, fits, config, pool_map)
    if clean is not None and not clean.empty:
        clean.to_csv(
            output_dir / f"results_{metadata['plate_id']}.csv",
            index=False, encoding="utf-8",
        )

    # 14. Export Section-3 deliverables: per-(antigen × sample) IN/OUT-of-
    # range table and per-antigen %-in-range summary.
    if not in_range.empty:
        in_range.to_csv(
            output_dir / f"in_range_{metadata['plate_id']}.csv",
            index=False, encoding="utf-8",
        )
    if not pct_in_range.empty:
        pct_in_range.to_csv(
            output_dir / f"pct_in_range_{metadata['plate_id']}.csv",
            index=False, encoding="utf-8",
        )
    # NC well levels (one row per NC well × analyte). Only written when
    # the plate actually has NC wells.
    if nc_levels is not None and not nc_levels.empty:
        nc_levels.to_csv(
            output_dir / f"nc_levels_{metadata['plate_id']}.csv",
            index=False, encoding="utf-8",
        )
    # Background QC (mean / SD / CV / max-flag per antigen). Written
    # whenever the plate has Background wells (the pilot always does).
    if bg_levels is not None and not bg_levels.empty:
        bg_levels.to_csv(
            output_dir / f"background_qc_{metadata['plate_id']}.csv",
            index=False, encoding="utf-8",
        )
    # PC replicate variability — per (pool × antigen × dilution) %CV.
    pc_pts = pc_replicates.get("points") if pc_replicates else None
    if pc_pts is not None and not pc_pts.empty:
        pc_pts.to_csv(
            output_dir / f"pc_replicates_{metadata['plate_id']}.csv",
            index=False, encoding="utf-8",
        )
    # Section-8 problem CSVs: per-antigen and per-sample summaries for
    # bead-count and range. One file per axis × QC so users can drill in
    # without scrolling through the report.
    plate_id = metadata["plate_id"]
    if not bead_summary["antigen_summary"].empty:
        bead_summary["antigen_summary"].to_csv(
            output_dir / f"bead_problem_antigens_{plate_id}.csv",
            index=False, encoding="utf-8",
        )
    if not bead_summary["sample_summary"].empty:
        bead_summary["sample_summary"].to_csv(
            output_dir / f"bead_problem_samples_{plate_id}.csv",
            index=False, encoding="utf-8",
        )
    if not range_summary["antigen_summary"].empty:
        range_summary["antigen_summary"].to_csv(
            output_dir / f"range_problem_antigens_{plate_id}.csv",
            index=False, encoding="utf-8",
        )
    if not range_summary["sample_summary"].empty:
        range_summary["sample_summary"].to_csv(
            output_dir / f"range_problem_samples_{plate_id}.csv",
            index=False, encoding="utf-8",
        )
    # Section-4 deliverable: bead-count problem list (red + yellow cells).
    bead_problems = bead_qc.get("problems")
    if bead_problems is not None and not bead_problems.empty:
        bead_problems.to_csv(
            output_dir / f"bead_problems_{metadata['plate_id']}.csv",
            index=False, encoding="utf-8",
        )

    return report_path


_MATRIX_RE = re.compile(r"_r\d+_(serum|dbs)$", re.IGNORECASE)


def _matrix_series(sample_ids: pd.Series) -> pd.Series:
    """Serum/DBS matrix parsed from the sample name."""
    disp = {"serum": "Serum", "dbs": "DBS"}
    return (sample_ids.astype(str).str.extract(_MATRIX_RE, expand=False)
            .str.lower().map(disp))


def _build_clean_results(metadata, in_range, specimen_results, fits, config, pool_map=None) -> pd.DataFrame:
    """Clean, analysis-ready per-(specimen well × antigen) master results table.

    The shape depends on the scoring mode (``panel.pool_mode``):

    - **per_pool** (default — "fit every pool × antigen, no auto-selecting"):
      a *wide* table with one row per (well × antigen) and a RAU + status
      column pair for **every** control pool, e.g. ``RAU (Dengue pool)`` /
      ``status (Dengue pool)``. Antigens a pool never calibrated read
      ``NO_FIT``. This avoids the misleading single-pool collapse (where every
      antigen looked like it came from one pool).

    - **auto_select**: a *tidy* single-pool table — plate_id, well, sample_id,
      matrix, analyte, ``pool`` (the auto-selected calibrating pool), mfi, RAU,
      status, censored.

    Common columns: plate_id, well, sample_id, matrix (Serum/DBS), analyte, mfi.
    """
    if in_range is None or in_range.empty:
        return pd.DataFrame()

    base = in_range[["well", "sample_name", "analyte", "mfi"]].copy()
    base = base.rename(columns={"sample_name": "sample_id"})
    base["matrix"] = _matrix_series(base["sample_id"])
    base.insert(0, "plate_id", metadata.get("plate_id", ""))

    pool_mode = (config or {}).get("panel", {}).get("pool_mode", "per_pool")
    sr = specimen_results if (specimen_results is not None and not specimen_results.empty) else None

    # ---- per_pool mode: wide table, RAU + status under every pool ----------
    if pool_mode != "auto_select" and fits:
        out = base[["plate_id", "well", "sample_id", "matrix", "analyte", "mfi"]].copy()
        for pool in sorted(fits.keys()):
            slug = _pool_slug(pool)
            rau_col, lloq_col, uloq_col = f"rau_{slug}", f"below_lloq_{slug}", f"above_uloq_{slug}"
            rau = pd.Series(np.nan, index=out.index)
            status = pd.Series("NO_FIT", index=out.index)
            if sr is not None and rau_col in sr.columns:
                merged = out[["well", "analyte"]].merge(
                    sr[["well", "analyte", rau_col,
                        *(c for c in (lloq_col, uloq_col) if c in sr.columns)]],
                    on=["well", "analyte"], how="left")
                rau = merged[rau_col]
                has = rau.notna().to_numpy()
                below = (merged[lloq_col].fillna(False).to_numpy()
                         if lloq_col in merged else np.zeros(len(merged), bool))
                above = (merged[uloq_col].fillna(False).to_numpy()
                         if uloq_col in merged else np.zeros(len(merged), bool))
                status = np.where(~has, "NO_FIT",
                                  np.where(below, "BELOW_RANGE",
                                           np.where(above, "ABOVE_RANGE", "IN_RANGE")))
            out[f"RAU ({pool})"] = pd.Series(rau).astype(float).round(2).to_numpy()
            out[f"status ({pool})"] = status
        return out

    # ---- auto_select mode: tidy single (selected) pool table ---------------
    out = base.copy()
    out["status"] = in_range["status"].to_numpy()
    selected = pool_map if pool_map is not None else build_pool_map(fits, None, config)
    out["pool"] = out["analyte"].map(selected).fillna("—")
    if sr is not None and "rau" in sr.columns:
        out = out.merge(sr[["well", "analyte", "rau"]].rename(columns={"rau": "RAU"}),
                        on=["well", "analyte"], how="left")
        if {"below_lloq", "above_uloq"}.issubset(sr.columns):
            cen = sr[["well", "analyte", "below_lloq", "above_uloq"]].copy()
            cen["censored"] = "none"
            cen.loc[cen["below_lloq"], "censored"] = "left"
            cen.loc[cen["above_uloq"], "censored"] = "right"
            out = out.merge(cen[["well", "analyte", "censored"]], on=["well", "analyte"], how="left")
    if "RAU" not in out.columns:
        out["RAU"] = float("nan")
    if "censored" not in out.columns:
        out["censored"] = "none"
    return out[["plate_id", "well", "sample_id", "matrix", "analyte", "pool",
                "mfi", "RAU", "status", "censored"]]


def _build_std_history(metadata: dict, pool_fits: dict, pool_name: str = "") -> pd.DataFrame:
    """Build standard curve history entries from current plate fits for one pool."""
    rows = []
    for analyte, fit in pool_fits.items():
        std_data = fit.get("std_data", pd.DataFrame())
        if std_data.empty:
            continue
        for _, r in std_data.iterrows():
            row = {
                "plate_id": metadata["plate_id"],
                "run_date": metadata.get("run_date", ""),
                "analyte": analyte,
                "dilution": r["dilution"],
                "mfi": r["mfi"],
            }
            if pool_name:
                row["pool"] = pool_name
            rows.append(row)
    return pd.DataFrame(rows)


def _build_background_history(metadata: dict, bg_levels: pd.DataFrame) -> pd.DataFrame:
    """Per-(plate × antigen) Background QC rows for the cross-plate
    overview scatter. Empty when the plate has no Background wells."""
    if bg_levels is None or bg_levels.empty:
        return pd.DataFrame()
    keep = [c for c in ("analyte", "n_wells", "mean_mfi", "sd_mfi", "cv",
                        "max_mfi", "cv_flag", "max_flag", "excluded")
            if c in bg_levels.columns]
    sub = bg_levels[keep].copy()
    sub["plate_id"] = metadata["plate_id"]
    sub["run_date"] = metadata.get("run_date", "")
    return sub[["plate_id", "run_date"] + keep]


def _build_specimen_mfi_history(metadata: dict, in_range: pd.DataFrame) -> pd.DataFrame:
    """Per-(plate × specimen well × antigen) MFI rows for the curve-picker rug.

    Carries ``status`` (IN_RANGE / BELOW_RANGE / ABOVE_RANGE / NO_FIT)
    and ``box_id`` so the picker can compose human-readable plate
    labels in the legend (e.g. ``PLATE_05112026_RUN000 · Box1``).
    """
    if in_range is None or in_range.empty:
        return pd.DataFrame()
    # ``patient_id`` and ``barcode`` are also persisted so past-plate
    # rug hovers and the cross-run MFI scatter can show them.
    keep = [c for c in ("well", "sample_name", "analyte", "mfi", "status",
                        "box_id", "barcode", "patient_id")
            if c in in_range.columns]
    sub = in_range[keep].copy()
    sub["plate_id"] = metadata["plate_id"]
    sub["run_date"] = metadata.get("run_date", "")
    # Drop NaN MFI rows — nothing to plot.
    sub = sub.dropna(subset=["mfi"])
    return sub[["plate_id", "run_date"] + keep]


def _build_nc_history(metadata: dict, nc_levels: pd.DataFrame) -> pd.DataFrame:
    """Build NC well history entries from the current plate's NC MFI.

    One row per (plate, well, analyte). Empty if the plate has no NC
    wells. Re-running the same plate overwrites prior rows because the
    dedup key in ``append_history`` is ``(plate_id, well, analyte)``.
    """
    if nc_levels is None or nc_levels.empty:
        return pd.DataFrame()
    rows = []
    for r in nc_levels.itertuples(index=False):
        rows.append({
            "plate_id": metadata["plate_id"],
            "run_date": metadata.get("run_date", ""),
            "well": r.well,
            "sample_name": r.sample_name,
            "analyte": r.analyte,
            "mfi": float(r.mfi) if pd.notna(r.mfi) else None,
        })
    return pd.DataFrame(rows)


def _build_fit_history(metadata: dict, pool_fits: dict, pool_name: str = "", box_ids: str = "") -> pd.DataFrame:
    """Build fit coefficient history entries for one pool."""
    rows = []
    for analyte, fit in pool_fits.items():
        row = {
            "plate_id": metadata["plate_id"],
            "run_date": metadata.get("run_date", ""),
            "box_ids": box_ids,
            "analyte": analyte,
            "fit_ok": fit["fit_ok"],
        }
        if pool_name:
            row["pool"] = pool_name
        if fit["params"]:
            a, b, c, d = fit["params"]
            row.update({"a": a, "b": b, "c": c, "d": d})
        rows.append(row)
    return pd.DataFrame(rows)
