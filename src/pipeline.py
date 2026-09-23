"""Main QC pipeline — orchestrates parsing, QC, and report generation."""

from __future__ import annotations

import base64
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .parse_xponent import parse_xponent_csv
from .classify import classify_wells
from .qc_beads import qc_bead_counts, bead_problem_summary
from .qc_nc import qc_nc_levels
from .qc_background import qc_background_levels
from .qc_pc_single_point import qc_pc_single_point
from .qc_standard_curve import (
    fit_standard_curves,
    compute_concentrations,
    compute_net_mfi,
    compute_in_range_table,
    compute_pct_in_range_per_antigen,
    range_problem_summary,
    build_pool_map,
    antigen_calibration,
    _pool_slug,
    _mfi_bounds_for_fit,
    _antigen_scoring_groups,
    _pool_groups,
)
from .settings import get_excluded_analytes
from .qc_history import load_history, append_history, save_history
from .parse_layout import read_plate_layout, build_layout
from .plate_summary import plate_summary
from .report import generate_report, plate_number_label
from .settings import load_config


def run_pipeline(
    csv_path: str | Path,
    output_dir: str | Path | None = None,
    layout_path: str | Path | None = None,
    inputfile_path: str | Path | None = None,
    history_dir: str | Path | None = None,
    config: dict | None = None,
    plate_order: list | None = None,
    age_path: str | Path | None = None,
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
    # Single-point positive controls (Cholera High / Low) — duplicate-well
    # MFI per (control × antigen) for the current plate. Tracked across plates
    # in the Positive Control QC section.
    pc_single = qc_pc_single_point(data)

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

    # Single-point PC history: persist duplicate-well MFI per (plate × control
    # × analyte × well) so the Positive Control QC section can track each
    # Cholera High/Low control across plates.
    pc_sp_history_path = Path(history_dir) / "pc_single_point_history.json"
    pc_sp_existing = load_history(pc_sp_history_path)
    new_pc_sp = _build_pc_single_point_history(metadata, pc_single.get("points"))
    if not new_pc_sp.empty:
        history_pc = append_history(
            pc_sp_existing, new_pc_sp, ["plate_id", "control", "analyte", "well"]
        )
        save_history(history_pc, pc_sp_history_path)
    else:
        history_pc = pc_sp_existing

    # 9. Generate the QC report.
    report_name = f"QC_{metadata['plate_id']}.html"
    report_path = output_dir / report_name

    # Individual age metadata (optional; one global file per results dir). Build a
    # {sample_name -> age_group} map for this plate's specimens.
    from .age import load_age_data, specimen_age_groups
    if age_path is None:
        # The global age file lives in the results dir; try both the reports dir's
        # parent and the history dir's parent (normally the same 'results' dir).
        _cands = []
        if output_dir is not None:
            _cands.append(Path(output_dir).parent / "age_data.csv")
        if history_dir is not None:
            _cands.append(Path(history_dir).parent / "age_data.csv")
        age_path = next((c for c in _cands if c.exists()),
                        _cands[0] if _cands else Path("age_data.csv"))
    age_file_exists = Path(age_path).exists()
    age_df = load_age_data(age_path)
    _spec_names = (data.loc[data["well_type"] == "specimen", "sample_name"].unique()
                   if "well_type" in data.columns else [])
    specimen_age = specimen_age_groups(age_df, _spec_names)
    age_info = {"present": age_df is not None,
                "file_exists": bool(age_file_exists),
                "path": str(age_path),
                "n_rows": (int(len(age_df)) if age_df is not None else 0),
                "n_specimens": int(len(_spec_names)),
                "n_matched": len(specimen_age)}

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
        history_std=history_std,
        history_nc=history_nc,
        history_pc=history_pc,
        history_fit=history_fit,
        history_specimens=history_specimens,
        history_background=history_background,
        output_path=report_path,
        plate_order=plate_order,
        config=config,
        specimen_age=specimen_age,
        age_info=age_info,
    )

    # 13. Export the single canonical per-plate results CSV — one row per
    # (specimen well × antigen), wide by standard (AU + status for every
    # standard, plus the reporting-standard headline). This one table is served
    # from every download location and concatenated into the Export-All
    # workbook's ``results`` sheet, so downloads never disagree.
    clean = _build_clean_results(metadata, in_range, specimen_results, fits, config, pool_map)
    if clean is not None and not clean.empty:
        clean.to_csv(
            output_dir / f"results_{metadata['plate_id']}.csv",
            index=False, encoding="utf-8",
        )

    # Downloadable CSVs use a consistent specimen-id column name (``sample_id``,
    # matching the results table) instead of the internal ``sample_name``.
    def _sid(df):
        return (df.rename(columns={"sample_name": "sample_id"})
                if df is not None and "sample_name" in getattr(df, "columns", [])
                else df)

    # 14. Export Section-3 deliverables: per-(antigen × sample) IN/OUT-of-
    # range table and per-antigen %-in-range summary.
    if not in_range.empty:
        _sid(in_range).to_csv(
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
        _sid(nc_levels).to_csv(
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
    # Single-point PC (Cholera High/Low) — duplicate-well MFI per (control ×
    # antigen) on this plate.
    pc_sp_pts = pc_single.get("points") if pc_single else None
    if pc_sp_pts is not None and not pc_sp_pts.empty:
        pc_sp_out = pc_sp_pts.copy()
        pc_sp_out.insert(0, "plate_id", metadata["plate_id"])
        pc_sp_out.to_csv(
            output_dir / f"pc_single_point_{metadata['plate_id']}.csv",
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
        _sid(bead_summary["sample_summary"]).to_csv(
            output_dir / f"bead_problem_samples_{plate_id}.csv",
            index=False, encoding="utf-8",
        )
    if not range_summary["antigen_summary"].empty:
        range_summary["antigen_summary"].to_csv(
            output_dir / f"range_problem_antigens_{plate_id}.csv",
            index=False, encoding="utf-8",
        )
    if not range_summary["sample_summary"].empty:
        _sid(range_summary["sample_summary"]).to_csv(
            output_dir / f"range_problem_samples_{plate_id}.csv",
            index=False, encoding="utf-8",
        )
    # Section-4 deliverable: bead-count problem list (red + yellow cells).
    bead_problems = bead_qc.get("problems")
    if bead_problems is not None and not bead_problems.empty:
        _sid(bead_problems).to_csv(
            output_dir / f"bead_problems_{metadata['plate_id']}.csv",
            index=False, encoding="utf-8",
        )

    # Embed the per-plate CSVs into the report's Download buttons as base64
    # data-URIs, so the buttons work when the saved HTML is opened offline (and
    # still work when served live). Must run after all CSVs above are written.
    _embed_report_downloads(report_path, output_dir)

    return report_path


_DOWNLOAD_HREF_RE = re.compile(r'href="/download/(?:specimens|report)/([^"]+)"')


def _embed_report_downloads(report_path: Path, output_dir: Path) -> None:
    """Rewrite the report's ``/download/...`` links to base64 ``data:`` URIs of
    the on-disk files, so downloads work in a saved/offline HTML report.

    Files that don't exist (e.g. nc_levels when the plate has no NC wells) keep
    their server link untouched. Failures are swallowed — the report is already
    written and valid with server links.
    """
    try:
        html_text = Path(report_path).read_text(encoding="utf-8")
    except Exception:
        return
    out = Path(output_dir)

    def _repl(m):
        fname = m.group(1)
        fpath = out / fname
        try:
            if not fpath.is_file():
                return m.group(0)
            b64 = base64.b64encode(fpath.read_bytes()).decode("ascii")
        except Exception:
            return m.group(0)
        return f'href="data:text/csv;base64,{b64}" download="{fname}"'

    new_text = _DOWNLOAD_HREF_RE.sub(_repl, html_text)
    if new_text != html_text:
        try:
            Path(report_path).write_text(new_text, encoding="utf-8")
        except Exception:
            pass


def _build_clean_results(metadata, in_range, specimen_results, fits, config, pool_map=None) -> pd.DataFrame:
    """The single canonical, analysis-ready results table — one row per
    (specimen well × antigen), *wide by standard*.

    This is the one results representation used everywhere (per-plate CSV,
    per-report download, and the ``results`` sheet of the Export-All workbook),
    so downloads never disagree. Columns:

    ``plate_id, well, sample_id, analyte, mfi, net_mfi, result_type,
    reporting_standard`` then, for **every** standard on the plate,
    ``AU_<standard>`` and ``status_<standard>`` (underscore-only names, valid
    identifiers in R / pandas).

    - **Every antigen × standard AU is shown**, regardless of whether that
      standard is the antigen's dedicated one — nothing is hidden.
    - ``reporting_standard`` is a *pointer* to the standard the antigen is
      designed to report against (its dedicated calibrator, matched by pathogen
      name among the standards present — independent of whether that curve fit
      this run); read the value from the matching ``AU_<standard>`` /
      ``status_<standard>`` columns (which show ``NO_FIT`` when the fit failed).
      Blank only for antigens with no dedicated standard on the plate.
    - ``result_type`` is the reliability tier of the headline result:
      ``quantitative`` (dedicated standard), ``semi-quantitative`` (legacy
      shared reference pool), or ``qualitative`` (no calibrator — best-fit AU
      only, present in the per-standard columns but not reported).

    The table is independent of ``panel.pool_mode``: the reporting standard is
    always the pathogen match, so the download is identical in either mode.
    """
    if in_range is None or in_range.empty:
        return pd.DataFrame()

    _TIER = {"standard": "quantitative", "reference": "semi-quantitative",
             "uncalibrated": "qualitative"}

    out = in_range[["well", "sample_name", "analyte", "mfi"]].copy()
    out = out.rename(columns={"sample_name": "sample_id"})
    out.insert(0, "plate_id", metadata.get("plate_id", ""))
    sr = specimen_results if (specimen_results is not None and not specimen_results.empty) else None

    # net_mfi (background-subtracted signal) carried from the specimen results.
    if sr is not None and "net_mfi" in sr.columns:
        out = out.merge(sr[["well", "analyte", "net_mfi"]], on=["well", "analyte"], how="left")
    else:
        out["net_mfi"] = np.nan
    out = out.reset_index(drop=True)
    n = len(out)

    # Reporting standard + result_type describe the *intended* calibrator for
    # each antigen — the dedicated standard it is designed to be scored against,
    # matched by pathogen name among the standards present on the plate,
    # *independent of whether that curve fit on this run*. This keeps assay
    # design (stable) separate from run outcome: an antigen whose dedicated
    # standard failed to fit still shows its reporting_standard and result_type,
    # with the failure visible as NO_FIT in the matching status_<standard> column.
    pool_names = sorted(fits.keys()) if fits else []

    def _intended_standard(antigen: str):
        """The standard this antigen is designed to report against (by pathogen
        name), or None. Ignores fit success; prefers a dedicated pool over the
        legacy pan-arbovirus reference."""
        for sg in _antigen_scoring_groups(antigen):
            cands = [p for p in pool_names if sg in _pool_groups(p)]
            if not cands:
                continue
            if sg != "arbovirus":
                dedicated = [p for p in cands if "arbovirus" not in _pool_groups(p)]
                if dedicated:
                    cands = dedicated
            return sorted(cands)[0]
        return None

    intended = {a: _intended_standard(a) for a in set(out["analyte"])}
    out["reporting_standard"] = out["analyte"].map(lambda a: intended.get(a) or "")
    out["result_type"] = [_TIER.get(antigen_calibration(a, intended.get(a)), "qualitative")
                          for a in out["analyte"]]

    multi = bool(fits) and len(fits) > 1
    mfi_arr = out["mfi"].to_numpy(dtype=float)
    analyte_arr = out["analyte"].to_numpy()
    distinct_antigens = set(analyte_arr.tolist())

    def _pool_au_status(pool):
        """(AU array, status array) for one standard, aligned to ``out`` rows.

        Status is classified from the specimen MFI against that standard's
        reportable-range MFI bounds — the same rule as the authoritative
        ``compute_in_range_table`` — so a specimen below the curve floor reads
        ``BELOW_RANGE`` (not ``NO_FIT``) even when its AU can't be interpolated.
        """
        slug = _pool_slug(pool)
        au_src = f"rau_{slug}" if multi else "rau"
        # AU against this standard.
        if sr is not None and au_src in sr.columns:
            m = out[["well", "analyte"]].merge(
                sr[["well", "analyte", au_src]], on=["well", "analyte"], how="left")
            au = m[au_src].astype(float).round(2).to_numpy()
        else:
            au = np.full(n, np.nan)
        # Range status from MFI bounds of this pool's fit.
        pf = fits.get(pool, {}) if fits else {}
        bounds = {a: (_mfi_bounds_for_fit(pf.get(a)) if pf.get(a) else (None, None))
                  for a in distinct_antigens}
        status = np.empty(n, dtype=object)
        for i in range(n):
            lo, hi = bounds.get(analyte_arr[i], (None, None))
            mv = mfi_arr[i]
            if lo is None or hi is None or np.isnan(mv):
                status[i] = "NO_FIT"
            elif mv < lo:
                status[i] = "BELOW_RANGE"
            elif mv > hi:
                status[i] = "ABOVE_RANGE"
            else:
                status[i] = "IN_RANGE"
        return au, status

    pools = sorted(fits.keys()) if fits else []
    pool_data = {}
    for pool in pools:
        r = _pool_au_status(pool)
        if r is not None:
            pool_data[pool] = r

    # ``reporting_standard`` is a pointer to the standard that carries the
    # headline result — read that antigen's AU / status from the matching
    # ``AU_<standard>`` / ``status_<standard>`` columns below. (No duplicate
    # reporting_AU / reporting_status columns.)
    cols = ["plate_id", "well", "sample_id", "analyte", "mfi", "net_mfi",
            "result_type", "reporting_standard"]
    # Column names use underscores, no spaces/parentheses, so they are valid
    # identifiers in R / pandas (e.g. ``AU_mAb_Mix``, ``status_Rubella``).
    for pool in pools:
        if pool in pool_data:
            slug = _pool_slug(pool)
            out[f"AU_{slug}"] = pool_data[pool][0]
            out[f"status_{slug}"] = pool_data[pool][1]
            cols += [f"AU_{slug}", f"status_{slug}"]
    return out[cols]


def _build_std_history(metadata: dict, pool_fits: dict, pool_name: str = "") -> pd.DataFrame:
    """Build standard curve history entries from current plate fits for one pool."""
    _plabel = plate_number_label(metadata.get("file", ""), metadata.get("plate_id", ""))
    rows = []
    for analyte, fit in pool_fits.items():
        std_data = fit.get("std_data", pd.DataFrame())
        if std_data.empty:
            continue
        for _, r in std_data.iterrows():
            row = {
                "plate_id": metadata["plate_id"],
                "run_date": metadata.get("run_date", ""),
                "plate_label": _plabel,
                "analyte": analyte,
                "dilution": r["dilution"],
                "mfi": r["mfi"],
            }
            if pool_name:
                row["pool"] = pool_name
            rows.append(row)
    return pd.DataFrame(rows)


def _build_pc_single_point_history(metadata: dict, points: pd.DataFrame | None) -> pd.DataFrame:
    """Per-(plate × control × analyte × well) single-point PC MFI rows for the
    cross-plate Positive Control QC overview. Empty when the plate has no
    single-point controls."""
    if points is None or points.empty:
        return pd.DataFrame()
    keep = [c for c in ("control", "control_label", "analyte", "well", "mfi")
            if c in points.columns]
    sub = points[keep].copy()
    sub["plate_id"] = metadata["plate_id"]
    sub["run_date"] = metadata.get("run_date", "")
    sub["plate_label"] = (plate_number_label(metadata.get("file", ""),
                                             metadata.get("plate_id", "")))
    return sub[["plate_id", "run_date", "plate_label"] + keep]


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
    _plabel = plate_number_label(metadata.get("file", ""), metadata.get("plate_id", ""))
    rows = []
    for r in nc_levels.itertuples(index=False):
        rows.append({
            "plate_id": metadata["plate_id"],
            "run_date": metadata.get("run_date", ""),
            "plate_label": _plabel,
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
            p = fit["params"]
            row.update({"a": p[0], "b": p[1], "c": p[2], "d": p[3]})
            if len(p) == 5:
                row["g"] = p[4]
            row["model"] = fit.get("model", "4pl")
        rows.append(row)
    return pd.DataFrame(rows)
