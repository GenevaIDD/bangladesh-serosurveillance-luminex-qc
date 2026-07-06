"""HTML report generation for the Bangladesh Serosurveillance 202-plex Luminex QC tool.

The report is a single self-contained HTML file (Plotly is loaded from a
CDN) with these sections:

1. Plate Overview banner — metadata, instrument, panel size, excluded
   analytes, Box xlsx used (when provided).
2. Bead-Count Matrix — antigens × samples heatmap with discrete
   Red / Yellow / Green tiers, plus a problem list of every R/Y cell.
3. Standard-Curve Summary — per-antigen table with %-in-range, R²,
   fit-ok flag.
4. Standard-Curve Picker — dropdown over all 200 antigens; swaps a
   single 4PL plot at a time.
5. Standard-Curve Range Matrix — antigens × specimens heatmap with
   four states (IN_RANGE / BELOW_RANGE / ABOVE_RANGE / NO_FIT) plus the
   out-of-range detail list.
6. Negative-Control Levels — MFI heatmap of NC wells per antigen
   (rendered only when the plate has NC samples).
7. Downloads — links to per-plate CSV exports.

Excluded analytes (e.g. ``FLU_B_HA_Maryland_1959``) are kept in every
table but rendered visually muted (light grey) and listed in a banner.
"""

from __future__ import annotations

import base64
import html
import io
import json
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless — never opens a window in the desktop app
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import APP_VERSION, RECOVERY_TOLERANCE
from .settings import get_excluded_analytes, get_qc_thresholds
from .qc_standard_curve import (
    four_pl, curve_eval, range_problem_summary, select_pool_per_antigen, default_scoring_pool,
    _pool_groups, PATHOGEN_LABELS, antigen_group,
    antigen_calibration, CALIBRATION_LABELS, _antigen_scoring_groups,
    _mfi_bounds_for_fit,
)
from .qc_beads import bead_problem_summary
from .qc_pc_single_point import control_label


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_report(
    metadata: dict,
    data: pd.DataFrame,
    bead_qc: dict,
    fits: dict,
    specimen_results: pd.DataFrame,
    summary: dict,
    in_range: pd.DataFrame,
    pct_in_range: pd.DataFrame,
    nc_levels: pd.DataFrame | None = None,
    history_std: dict | pd.DataFrame | None = None,
    history_nc: pd.DataFrame | None = None,
    history_fit: dict | pd.DataFrame | None = None,
    history_specimens: pd.DataFrame | None = None,
    history_background: pd.DataFrame | None = None,
    history_pc: pd.DataFrame | None = None,
    output_path: Path | None = None,
    plate_order: list | None = None,
    config: dict | None = None,
    layout_info: dict | None = None,
) -> Path:
    """Render the QC report HTML and write it to ``output_path``."""
    _reset_plotlyjs_embed_flag()
    config = config or {}
    excluded = set(get_excluded_analytes(config))
    qc_thresh = get_qc_thresholds(config) if config else {}
    rec_tol = qc_thresh.get("recovery_tolerance", RECOVERY_TOLERANCE)
    problem_frac = float(qc_thresh.get("problem_fraction_threshold", 0.20))
    bg_cv_thr = float(qc_thresh.get("bg_cv_threshold", 0.25))
    bg_max_thr = float(qc_thresh.get("bg_max_mfi", 300))
    nc_cv_thr = float(qc_thresh.get("nc_cv_threshold", 0.25))
    hist_cv_thr = float(qc_thresh.get("hist_cv_threshold", 0.30))

    pool_fits = _first_pool(fits)
    plate_id = metadata.get("plate_id", "unknown")

    # Standard-curve presentation mode.
    pool_mode = config.get("panel", {}).get("pool_mode", "auto_select")
    # Active curve model for this report (uniform across all antigens).
    _cm = str(config.get("panel", {}).get("curve_model", "5pl")).lower()
    curve_model_label = "5PL" if _cm != "4pl" else "4PL"
    curve_model_name = ("5PL (five-parameter logistic)" if _cm != "4pl"
                        else "4PL (four-parameter logistic)")
    pools = list(fits.keys())
    scoring_pool = default_scoring_pool(fits, config) if pools else None

    pool_selection = _build_pool_selection_summary(fits, config)

    # Per-antigen fit used by the Picker / cross-run / scoring sections (a
    # single curve per antigen). In auto_select mode this is the pathogen-
    # matched best-fit pool; in per_pool mode it is the single scoring pool
    # (no matching). The All-Curves Overview / Summary handle per-pool
    # presentation separately below.
    if pool_mode == "auto_select":
        selected_fits = _build_selected_fits(fits, config)
    else:
        selected_fits = {
            a: {**fits[scoring_pool][a], "pool": scoring_pool}
            for a in (fits.get(scoring_pool) or {})
        } if scoring_pool else {}
    if not selected_fits:
        selected_fits = pool_fits

    # All antigens for this plate. The Summary shows every antigen (one table per
    # pool, with a Relevance column) and the All-Curves Overview shows every
    # antigen per pool — there is no priority-antigen display filter.
    panel_order = list(metadata.get("analytes") or list(selected_fits.keys()))

    well_types_map = (
        data.drop_duplicates("well").set_index("well")["well_type"].to_dict()
        if not data.empty and "well_type" in data.columns
        else {}
    )

    # Per-well-type counts for the Plate Overview number cards.
    _wt_counts: dict[str, int] = {}
    for _wt in well_types_map.values():
        _wt_counts[_wt] = _wt_counts.get(_wt, 0) + 1
    plate_counts = {
        "total": len(well_types_map),
        "nc": _wt_counts.get("nc", 0),
        "pc": _wt_counts.get("pc", 0),
        "specimen": _wt_counts.get("specimen", 0),
        "background": _wt_counts.get("background", 0),
        "antigens": len(metadata.get("analytes") or []) or (len(pool_fits) if pool_fits else 0),
    }
    # Single-point PC well counts (e.g. Cholera High / Cholera Low), one entry
    # per control, for the Plate Overview cards. Counts distinct wells on THIS
    # plate. These wells are also part of the "PC / standard" total above.
    single_point_pc: list[dict] = []
    if (not data.empty and {"well_type", "pc_single_point", "pc_pool", "well"}
            <= set(data.columns)):
        sp = data[(data["well_type"] == "pc") & data["pc_single_point"].fillna(False)]
        for pool, g in sp.groupby("pc_pool", sort=False):
            single_point_pc.append(
                {"label": control_label(str(pool)), "n_wells": int(g["well"].nunique())})
    plate_counts["single_point_pc"] = single_point_pc

    # IMPORTANT: build figures in the same order they appear in the
    # rendered HTML.  ``_plotly_html`` embeds the Plotly.js library
    # inline on the FIRST call (then references the loaded library on
    # subsequent ones).  If a later-built figure ends up earlier in
    # the DOM, the browser tries to call ``Plotly.newPlot`` before the
    # library is defined and the figure silently fails to render.
    # Template emits sections in this order:
    #   1. Plate Overview    → plate_layout
    #   2. Background QC     → bg_overview
    #   3. Bead-Count Matrix → bead_heatmap
    #   4. (Standard-Curve Summary — no Plotly figures)
    #   5. All Curves Overview → curve_grid (matplotlib PNG)
    #   6. Standard-Curve Picker → curve_picker
    #   7. Range Matrix      → range_heatmap
    #   8. NC QC             → nc_heatmap + nc_history
    # Build figures in DOM order (Plotly.js embeds on the first call):
    #   1. Plate Overview → 2. Bead Count → 3. Background QC → …
    plate_layout_html = _make_plate_layout_overview(data)
    bead_heatmap_html = _make_bead_heatmap(bead_qc, excluded, well_types=well_types_map)

    # ----- Background QC -----
    # Unified with PC/NC: current-plate Background wells (per well) + each past
    # plate's mean Background MFI (one pseudo-well per plate), fed through the
    # same cross-plate overview + stats helpers so all three sections match.
    cur_pid = metadata.get("plate_id")
    cur_rd = metadata.get("run_date")
    bgw = (data[data["well_type"] == "background"][["analyte", "well", "mfi"]].copy()
           if (not data.empty and "well_type" in data.columns)
           else pd.DataFrame(columns=["analyte", "well", "mfi"]))
    bgw["plate_id"] = cur_pid
    bgw["run_date"] = cur_rd
    if (isinstance(history_background, pd.DataFrame) and not history_background.empty
            and "mean_mfi" in history_background.columns):
        _cols = ["plate_id", "analyte", "mean_mfi"] + (
            ["run_date"] if "run_date" in history_background.columns else [])
        _hb = history_background[history_background["plate_id"] != cur_pid][
            _cols].dropna(subset=["mean_mfi"]).copy()
        _hb = _hb.rename(columns={"mean_mfi": "mfi"})
        _hb["well"] = "(plate mean)"
    else:
        _hb = pd.DataFrame(columns=["plate_id", "analyte", "mfi", "well", "run_date"])
    bg_hist = pd.concat([bgw] + ([_hb] if not _hb.empty else []), ignore_index=True)
    n_prev_bg = len(_past_plate_ids(bg_hist, cur_pid, cur_rd))
    bg_overview_html = _cross_plate_mfi_overview(
        bg_hist, panel_order, cur_pid, cur_rd, "Mean Background MFI (log scale)",
        "fig-bg-overview", excluded,
        hline=(float(bg_max_thr), f"Max background ({int(bg_max_thr)} MFI)"))
    bg_stats, bg_well_cols = _format_control_stats(
        bg_hist, panel_order, cur_pid, cur_rd, excluded, cv_flag_threshold=bg_cv_thr,
        hist_cv_flag_threshold=hist_cv_thr)
    # Hidden Background tables: (a) single-well outliers, (e) negative net MFI.
    bg_outliers = _bg_well_outliers(bgw, panel_order, cur_pid, excluded)
    bg_negative_net = _bg_negative_net(data, bgw, cur_pid, excluded)
    # Mark antigens that have a flagged well-outlier so the main table can show
    # it in context (and the row can be highlighted).
    _outlier_ans = {r["analyte"] for r in bg_outliers}
    for r in bg_stats:
        r["has_outlier"] = r["analyte"] in _outlier_ans
    n_high_cv = sum(1 for r in bg_stats if r.get("high_cv"))
    n_high_hist_cv = sum(1 for r in bg_stats if r.get("high_hist_cv"))
    bg_levels_ctx = {"present": bool(bg_stats), "n_antigens": len(bg_stats),
                     "n_prev_plates": n_prev_bg, "rows": bg_stats,
                     "well_cols": bg_well_cols, "n_high_cv": n_high_cv,
                     "n_high_hist_cv": n_high_hist_cv, "n_outliers": len(bg_outliers)}

    # ----- Positive Control QC (single-point Cholera High/Low) -----
    # Cross-plate overview + stats per control, modelled on Background QC.
    pc_hist = (history_pc.copy()
               if isinstance(history_pc, pd.DataFrame) and not history_pc.empty
               else pd.DataFrame())
    if not pc_hist.empty and "control_label" in pc_hist.columns:
        pc_hist["control"] = pc_hist["control_label"]
    pc_controls = _control_qc_sections(
        pc_hist, panel_order, cur_pid, cur_rd, excluded,
        "Single-point PC MFI (log scale)", "pc-sp",
        cv_flag_threshold=nc_cv_thr, hist_cv_flag_threshold=hist_cv_thr)
    pc_present = bool(pc_controls)

    # ----- Negative Control QC -----
    # One cross-plate overview + stats per NC control (Negative 0/49).
    nc_hist = (history_nc.copy()
               if isinstance(history_nc, pd.DataFrame) and not history_nc.empty
               else pd.DataFrame())
    if not nc_hist.empty and "sample_name" in nc_hist.columns:
        nc_hist["control"] = nc_hist["sample_name"].apply(_nc_control)
    nc_controls = _control_qc_sections(
        nc_hist, panel_order, cur_pid, cur_rd, excluded,
        "NC MFI (log scale)", "nc-ctrl", cv_flag_threshold=nc_cv_thr,
        hist_cv_flag_threshold=hist_cv_thr)
    # ----- Standard-Curve Summary + All-Curves Overview -----
    # The Summary (one sortable table per pool over ALL antigens, with a
    # Relevance column) is built by _build_summary_by_pool_all below. The
    # All-Curves Overview shows one curve grid per pool over all antigens.
    def _all_pool_grids() -> str:
        """One grid per pool over ALL panel antigens (the collapsed 'all curve
        fits, all pools' block)."""
        parts = []
        for pi, pool in enumerate(pools):
            pf = {a: {**fits[pool][a], "pool": pool}
                  for a in panel_order if a in fits.get(pool, {})}
            if not pf:
                continue
            parts.append(
                f'<h4 style="margin:18px 0 4px; color:#2c3e50;">Pool: {html.escape(pool)}</h4>'
                + _make_curve_grid(pf, excluded, in_range=in_range,
                                   div_id=f"fig-curve-grid-{pi}"))
        return "".join(parts) or "<p style='color:#999;'>No standard curve fits.</p>"

    curve_grid_html = _all_pool_grids()

    # Featured priority antigens (pathogen-relevant) vs their pool(s).
    _featured_past = _past_plate_ids(history_specimens, cur_pid, cur_rd) \
        if isinstance(history_specimens, pd.DataFrame) and not history_specimens.empty else []
    featured_grid_html = _build_featured_grids(
        panel_order, fits, pools, excluded, in_range,
        history_fit=history_fit, past_ids=_featured_past)
    layout_info = layout_info or _derive_layout_info(data)
    current_box_ids = layout_info.get("box_ids") or []
    # Picker: on-demand explorer over ALL (pool × antigen) fits — review tool.
    curve_picker_html = _make_curve_picker(
        fits, excluded,
        antigens=panel_order,
        in_range=in_range,
        history_specimens=history_specimens,
        history_fit=history_fit,
        current_plate_id=metadata.get("plate_id"),
        current_run_date=metadata.get("run_date"),
        current_box_ids=current_box_ids,
    )
    cross_run_html = _make_cross_run_scatter(
        selected_fits, excluded,
        in_range=in_range,
        history_specimens=history_specimens,
        current_plate_id=metadata.get("plate_id"),
        current_box_ids=current_box_ids,
    )
    _xr_m, _xr_t = _xrun_overlap(in_range, history_specimens, metadata.get("plate_id"))
    cross_run_match = {"matched": _xr_m, "total": _xr_t}
    range_heatmap_html = _make_in_range_heatmap(
        in_range, excluded,
        antigen_pool={a: (selected_fits[a].get("pool") or "—") for a in selected_fits},
        pool_mode=pool_mode)
    serum_dbs_html = _make_serum_dbs_comparison(in_range)

    bead_problems = _format_problem_list(bead_qc.get("problems", pd.DataFrame()))
    range_problems = _format_range_problems(
        in_range, excluded,
        antigen_pool={a: (selected_fits[a].get("pool") or "—") for a in selected_fits},
        pool_mode=pool_mode)
    nc_present = nc_levels is not None and not nc_levels.empty
    n_nc_wells = int(nc_levels["well"].nunique()) if nc_present else 0

    # Summary cards (Section-8 work).
    bead_summary = bead_problem_summary(
        bead_qc, well_types=well_types_map, fraction_threshold=problem_frac
    )
    range_summary = range_problem_summary(
        in_range, fraction_threshold=problem_frac, excluded_analytes=excluded
    )

    base_dir = Path(__file__).parent.parent
    env = Environment(
        loader=FileSystemLoader(str(base_dir / "templates")),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("report.html")

    range_problem_by_pool = _build_range_problem_by_pool(
        fits, data, pools, problem_frac, excluded)
    _rp_below = {r["well"] for blk in range_problem_by_pool for r in blk["rows"] if r["n_below"]}
    _rp_above = {r["well"] for blk in range_problem_by_pool for r in blk["rows"] if r["n_above"]}
    range_problem_counts = {
        "n_flagged": len({r["well"] for blk in range_problem_by_pool for r in blk["rows"]}),
        "n_below": len(_rp_below), "n_above": len(_rp_above),
    }

    rendered_html = template.render(
        metadata=metadata,
        version=APP_VERSION,
        summary=summary,
        excluded_analytes=sorted(excluded),
        layout_info=layout_info,
        plate_counts=plate_counts,
        csv_file=metadata.get("file", ""),
        bead_thresholds={
            "red_below": bead_qc.get("red_threshold"),
            "yellow_below": bead_qc.get("yellow_threshold"),
        },
        bead_heatmap_html=bead_heatmap_html,
        plate_layout_html=plate_layout_html,
        curve_grid_html=curve_grid_html,
        featured_grid_html=featured_grid_html,
        bead_problems=bead_problems,
        bead_problem_counts=_tier_counts(bead_qc.get("problems", pd.DataFrame())),
        bead_n_wells=(bead_qc.get("matrix").shape[1]
                      if bead_qc.get("matrix") is not None else 0),
        curve_summary_by_pool=_build_summary_by_pool_all(
            fits, pools, panel_order, excluded, rec_tol),
        pool_selection=pool_selection,
        pool_mode=pool_mode,
        curve_model_label=curve_model_label,
        curve_model_name=curve_model_name,
        scoring_pool=scoring_pool or "",
        n_panel_antigens=len(panel_order),
        curve_picker_html=curve_picker_html,
        cross_run_html=cross_run_html,
        cross_run_present=bool(cross_run_html),
        cross_run_match=cross_run_match,
        range_heatmap_html=range_heatmap_html,
        serum_dbs_html=serum_dbs_html,
        serum_dbs_present=bool(serum_dbs_html),
        range_problems=range_problems,
        nc_controls=nc_controls,
        pc_controls=pc_controls,
        pc_present=pc_present,
        nc_present=nc_present,
        n_nc_wells=n_nc_wells,
        bead_summary=_format_bead_summary(bead_summary),
        range_summary=_format_range_summary(
            range_summary,
            antigen_pool={a: (selected_fits[a].get("pool") or "—") for a in selected_fits}),
        range_problem_by_pool=range_problem_by_pool,
        range_problem_counts=range_problem_counts,
        bg_levels=bg_levels_ctx,
        bg_outliers=bg_outliers,
        bg_negative_net=bg_negative_net,
        bg_overview_html=bg_overview_html,
        bg_overview_present=bool(bg_overview_html),
        problem_threshold_pct=int(round(problem_frac * 100)),
        bg_cv_pct=int(round(bg_cv_thr * 100)),
        bg_max_mfi=int(bg_max_thr),
        nc_cv_pct=int(round(nc_cv_thr * 100)),
        hist_cv_pct=int(round(hist_cv_thr * 100)),
        n_specimens=int(data[data["well_type"] == "specimen"]["well"].nunique()) if not data.empty else 0,
        n_antigens=len(pool_fits) if pool_fits else 0,
        plate_id=plate_id,
        specimen_csv=f"specimens_{plate_id}.csv",
        in_range_csv=f"in_range_{plate_id}.csv",
        pct_in_range_csv=f"pct_in_range_{plate_id}.csv",
    )
    output_path.write_text(rendered_html, encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# Figure builders
# ---------------------------------------------------------------------------


_plotlyjs_embedded = False


def _plotly_html(fig: go.Figure, div_id: str, height: int = 500, responsive: bool = True) -> str:
    """Render a Plotly figure to an HTML <div>.

    The first call per report embeds the matching plotly.js inline so the
    report is fully self-contained (no internet required, no version
    skew between the JSON we emit and the runtime library). Subsequent
    calls reference the already-loaded library.

    ``responsive=False`` is the right choice for figures that pin an
    explicit ``width`` (e.g. the Background MFI overview, which is
    drawn ~2000 px wide and lives inside a horizontally-scrolling
    container).
    """
    global _plotlyjs_embedded
    include = True if not _plotlyjs_embedded else False
    _plotlyjs_embedded = True
    return pio.to_html(
        fig,
        include_plotlyjs=include,
        full_html=False,
        default_height=f"{height}px",
        div_id=div_id,
        config={"displaylogo": False, "responsive": responsive},
    )


def _reset_plotlyjs_embed_flag() -> None:
    """Reset the per-report inline-embed flag. Called once at the top of
    ``generate_report`` so successive calls each get a self-contained file."""
    global _plotlyjs_embedded
    _plotlyjs_embedded = False


def _group_boundaries(well_order: list[str], well_types: dict[str, str]) -> list[tuple[int, str, str]]:
    """Return ``(boundary_index, left_label, right_label)`` for every place
    a well_type change occurs in ``well_order``. ``boundary_index`` is
    the heatmap x-coordinate at which the dotted line should sit
    (between column i-1 and column i, so x = i - 0.5)."""
    boundaries: list[tuple[int, str, str]] = []
    if not well_order:
        return boundaries
    prev = well_types.get(well_order[0], "specimen")
    for i, w in enumerate(well_order[1:], start=1):
        cur = well_types.get(w, "specimen")
        if cur != prev:
            boundaries.append((i, prev, cur))
            prev = cur
    return boundaries


def _make_bead_heatmap(bead_qc: dict, excluded: set[str], well_types: dict[str, str] | None = None) -> str:
    matrix = bead_qc.get("matrix")
    tier_matrix = bead_qc.get("tier_matrix")
    if matrix is None or matrix.empty:
        return "<p style='color:#999;'>No bead-count data.</p>"

    sample_labels = bead_qc.get("sample_labels", {})
    # Order wells by plate position (A1, A2, …) so re-run wells appended at the
    # end of the CSV don't trail off the right of the grid out of sequence.
    well_cols = sorted(matrix.columns, key=_well_sort_key)
    matrix = matrix.reindex(columns=well_cols)
    tier_matrix = tier_matrix.reindex(columns=well_cols)
    analyte_rows = list(matrix.index)

    tier_to_int = {"red": 0, "yellow": 1, "green": 2}
    z = np.vectorize(lambda t: tier_to_int.get(t, 0))(tier_matrix.values)

    text = np.empty(z.shape, dtype=object)
    for i, an in enumerate(analyte_rows):
        for j, w in enumerate(well_cols):
            count = matrix.iat[i, j]
            label = sample_labels.get(w, "") or "—"
            count_str = "—" if pd.isna(count) else f"{int(count)}"
            _tier_label = {"red": "Critically Low Bead Count",
                           "yellow": "Low Bead Count",
                           "green": "Adequate Bead Count"}.get(
                str(tier_matrix.iat[i, j]).lower(), str(tier_matrix.iat[i, j]))
            text[i, j] = (
                f"<b>{an}</b><br>Well: {w}<br>Sample: {label}<br>"
                f"Bead count: {count_str}<br>Tier: {_tier_label}"
            )

    # Colour-blind-safe tiers (Okabe–Ito): vermillion = low/fail,
    # amber = warn, bluish-green = OK.
    colorscale = [
        [0.0, _CB_VERMILLION], [0.34, _CB_VERMILLION],
        [0.34, _CB_AMBER], [0.67, _CB_AMBER],
        [0.67, _CB_GREEN], [1.0, _CB_GREEN],
    ]
    boundaries = _group_boundaries(well_cols, well_types) if well_types else None
    # Shared freeze-panes layout: frozen antigen rows (left) + frozen well-
    # position header (top) + scrolling heatmap body.
    return _freeze_pane_heatmap(
        analyte_rows, well_cols, z, text, colorscale, 0, 2, excluded,
        "fig-bead", group_boundaries=boundaries,
    )


# Colour-blind-safe palette (Okabe–Ito) used across the report. These hues are
# distinguishable under deuteranopia / protanopia / tritanopia; where colour
# encodes pass/fail we also vary marker SHAPE so colour is never the only cue.
_CB_BLUE = "#0072B2"        # within range / OK
_CB_VERMILLION = "#D55E00"  # out of range / fail (paired with a diamond/shape)
_CB_AMBER = "#E69F00"       # warning / intermediate
_CB_GREEN = "#009E73"       # good / pass (bluish-green, not red-green ambiguous)
_CB_GREY = "#999999"        # neutral / historical reference
_CUR_RED = "#D7191C"        # current plate in the per-plate control view


def _blue_green_gradient(t: float) -> str:
    """Chronological past-plate colour: Okabe–Ito blue → green with age-based
    opacity. ``t`` in [0, 1]: 0 = oldest (faded blue), 1 = newest (bold green)."""
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    b, g = (0, 114, 178), (0, 158, 115)  # _CB_BLUE, _CB_GREEN
    r = int(b[0] + (g[0] - b[0]) * t)
    gg = int(b[1] + (g[1] - b[1]) * t)
    bb = int(b[2] + (g[2] - b[2]) * t)
    return f"rgba({r},{gg},{bb},{0.35 + 0.60 * t:.2f})"

# Specimen range-status colours (shared with the picker rug) — Okabe–Ito,
# colour-blind safe.
_STATUS_COLORS = {
    "BELOW_RANGE": "#0072B2", "IN_RANGE": "#009E73",
    "ABOVE_RANGE": "#D55E00", "NO_FIT": "#999999",
}
# Above this many panels the interactive grid gets too heavy, so we fall
# back to the static image. Setting priority antigens keeps it interactive.
_INTERACTIVE_GRID_CAP = 48

# Pathogen-group colours for grouping/labelling antigens (Okabe–Ito).
_PATHOGEN_COLORS = {
    "cholera": "#0072B2",    # blue
    "dengue": "#009E73",     # green
    "typhoid": "#D55E00",    # vermillion
    "arbovirus": "#E69F00",  # amber
    "vpd": "#CC79A7",        # reddish purple
}


def _linear_range_box(fit: dict):
    """Return (x0, x1, y0, y1) of the reportable/linear-range rectangle, or None.

    x spans ULOQ→LLOQ dilution; y spans the MFI at those dilutions on the 4PL.
    """
    params = fit.get("params")
    rr = fit.get("reportable_range") or {}
    lo_d, hi_d = rr.get("lloq_dilution"), rr.get("uloq_dilution")
    if params is None or lo_d is None or hi_d is None:
        return None
    try:
        y_lo = float(curve_eval(params, np.array([float(lo_d)]))[0])
        y_hi = float(curve_eval(params, np.array([float(hi_d)]))[0])
    except Exception:
        return None
    x0, x1 = sorted((float(lo_d), float(hi_d)))
    y0, y1 = sorted((y_lo, y_hi))
    return x0, x1, y0, y1


_FEATURED_CAT_ORDER = ["cholera", "dengue", "typhoid", "arbovirus", "vpd"]


def _pool_sort_rank(pool: str) -> tuple:
    """Order pool sections: cholera/typhoid pools, then NIBSC, then dengue/orpal
    reference pools, then anything else; alphabetical within a tier so 'Dengue'
    precedes 'Orpal'."""
    g = _pool_groups(pool)
    if "cholera" in g or "typhoid" in g:
        return (0, pool)
    if "vpd_nibsc" in g:
        return (1, pool)
    if "dengue" in g:
        return (2, pool)
    return (3, pool)


def _build_featured_grids(
    panel_order: list[str],
    fits: dict,
    pools: list[str],
    excluded: set[str],
    in_range: pd.DataFrame | None,
    history_fit: dict | None = None,
    past_ids=None,
) -> str:
    """Featured priority-antigen curves, organized **by standard pool**.

    One section per standard pool on the plate; each shows the antigens relevant
    to that pool (its designated calibrator / reference, resolved against which
    pools are present — NIBSC preferred for measles/diphtheria/rubella/tetanus
    when present, else the Dengue/Orpal reference), each fit **against that
    pool**. A dengue antigen therefore appears under both the Dengue and Orpal
    sections. No-standard antigens (no pathogen category) are not featured here.
    """
    if not pools:
        return "<p style='color:#999;'>No standard pools on this plate.</p>"
    pool_grp = {p: _pool_groups(p) for p in pools}
    groups_present = set().union(*pool_grp.values()) if pool_grp else set()

    def _eff_group(a: str) -> str | None:
        # First of the antigen's preferred→fallback scoring groups that some
        # pool on THIS plate actually provides.
        for g in _antigen_scoring_groups(a):
            if g in groups_present:
                return g
        return None

    eff = {a: _eff_group(a) for a in panel_order if antigen_group(a)}
    parts = []
    for pi, pool in enumerate(sorted(pools, key=_pool_sort_rank)):
        pg = pool_grp[pool]
        feat = [a for a in panel_order
                if a in eff and eff[a] in pg and a in fits.get(pool, {})]
        if not feat:
            continue
        fc = {a: {**fits[pool][a], "pool": pool} for a in feat}
        parts.append(
            f'<h4 style="margin:16px 0 4px; color:#2c3e50;">Pool: {html.escape(pool)} '
            f'<span style="font-weight:400; color:#7f8c8d; font-size:13px;">'
            f'({len(fc)} antigen{"s" if len(fc) != 1 else ""} · targets: '
            f'{html.escape(_pool_target_label(pool))})</span></h4>'
            + _make_curve_grid(fc, excluded, in_range=in_range,
                               div_id=f"fig-featured-{pi}",
                               history_fit=history_fit, past_ids=past_ids)
        )
    return "".join(parts) or "<p style='color:#999;'>No pathogen-matched priority antigens on this plate.</p>"


def _make_curve_grid(pool_fits: dict, excluded: set[str], cols: int = 6,
                     in_range: pd.DataFrame | None = None,
                     div_id: str = "fig-curve-grid",
                     history_fit: dict | None = None,
                     past_ids=None) -> str:
    """All-Curves Overview for the (priority) antigens.

    Interactive Plotly small-multiples when the count is manageable — each
    panel shows the standard points (blue; out-of-tolerance points as red
    triangles, a dropped point as ✕), the 4PL fit (red), the shaded
    linear/reportable range (green square), and a rug of the *current plate's*
    specimens coloured by range status, with hover. Falls back to a static
    image when there are too many panels (set priority antigens to keep it
    interactive).
    """
    if not pool_fits:
        return "<p style='color:#999;'>No standard curve fits.</p>"
    analytes = list(pool_fits.keys())
    if len(analytes) <= _INTERACTIVE_GRID_CAP:
        return _make_curve_grid_interactive(pool_fits, excluded, cols, in_range,
                                            div_id=div_id, history_fit=history_fit,
                                            past_ids=past_ids)
    return _make_curve_grid_static(pool_fits, excluded, cols=10)


def _hist_curve_params(history_fit: dict | None, pool: str | None,
                       analyte: str, past_ids) -> list:
    """Past-plate curve params ``[(plate_id, [a,b,c,d(,g)]), …]`` for
    (pool × analyte), limited to ``past_ids`` when given. Each past plate's
    params are returned **with the model it was actually fit under** (5 values
    when that plate stored a 5PL ``g``, else 4) so the overlay is drawn under
    that plate's own model (Option A)."""
    dfp = (history_fit or {}).get(pool)
    if dfp is None or getattr(dfp, "empty", True) or "analyte" not in dfp.columns:
        return []
    sub = dfp[dfp["analyte"] == analyte]
    if past_ids is not None and "plate_id" in sub.columns:
        sub = sub[sub["plate_id"].isin(list(past_ids))]
    out = []
    for r in sub.itertuples(index=False):
        try:
            pr = [float(r.a), float(r.b), float(r.c), float(r.d)]
        except Exception:
            continue
        if any(v != v for v in pr):
            continue
        g = getattr(r, "g", None)
        try:
            if g is not None and float(g) == float(g):  # 5PL entry (g not NaN)
                pr.append(float(g))
        except (TypeError, ValueError):
            pass
        out.append((str(getattr(r, "plate_id", "")), pr))
    return out


def _make_curve_grid_interactive(pool_fits: dict, excluded: set[str], cols: int,
                                 in_range: pd.DataFrame | None,
                                 div_id: str = "fig-curve-grid",
                                 history_fit: dict | None = None,
                                 past_ids=None) -> str:
    from plotly.subplots import make_subplots

    analytes = list(pool_fits.keys())
    n = len(analytes)
    cols = max(1, min(cols, n))
    rows = (n + cols - 1) // cols

    # Fixed per-panel height + fixed inter-row gap (px), converted to the
    # fraction make_subplots wants. A *fractional* vertical_spacing squishes
    # tall grids (e.g. a 43-antigen pool → ~8 rows), so keep it pixel-based.
    panel_h = 165
    gap_px = 44
    plot_area_h = rows * panel_h + max(rows - 1, 0) * gap_px
    v_space = min(gap_px / plot_area_h, 0.9 / max(rows - 1, 1)) if rows > 1 else 0.0

    titles = []
    for an in analytes:
        fit = pool_fits[an]
        color = ("#95a5a6" if an in excluded
                 else _CB_GREEN if fit.get("fit_ok") else _CB_VERMILLION)
        short = an if len(an) <= 22 else an[:20] + "…"
        titles.append(f"<span style='color:{color}'>{short}</span>")

    fig = make_subplots(rows=rows, cols=cols, subplot_titles=titles,
                        horizontal_spacing=0.055, vertical_spacing=v_space)

    # Per-antigen current-plate specimen MFIs (for the rug), grouped once.
    spec_by_an: dict[str, pd.DataFrame] = {}
    if in_range is not None and not in_range.empty:
        for an, g in in_range.groupby("analyte"):
            spec_by_an[an] = g

    shown_legend = set()  # only emit each legend entry once
    hist_idx = []          # trace indices of past-plate curves (for the toggle)
    for i, an in enumerate(analytes):
        r, c = divmod(i, cols)
        rr_, cc_ = r + 1, c + 1
        fit = pool_fits[an]
        std = fit.get("mean_data")
        params = fit.get("params")
        if std is None or std.empty:
            continue
        xd = std["dilution"].astype(float).values
        yd = std["mfi"].astype(float).values

        # Past-plate fitted curves (light grey), overlaid like the picker.
        hp = _hist_curve_params(history_fit, fit.get("pool"), an, past_ids)
        if hp:
            xs_h = np.geomspace(max(float(xd.min()), 1e-9), float(xd.max()), 60)
            for pid_, pr in hp:
                _hm = "5PL" if len(pr) == 5 else "4PL"
                hist_idx.append(len(fig.data))
                fig.add_trace(go.Scatter(
                    x=xs_h, y=curve_eval(pr, xs_h), mode="lines",
                    line=dict(color="rgba(150,150,150,0.55)", width=0.7),
                    name="Past plates", legendgroup="hist",
                    showlegend="hist" not in shown_legend, visible=True,
                    hovertemplate=f"{pid_} · {_hm} (as fit)<br>Dilution 1:%{{x:.0f}}<br>MFI %{{y:.0f}}<extra></extra>",
                ), row=rr_, col=cc_); shown_legend.add("hist")

        # Out-of-tolerance standard points (red triangles) from obs/exp recovery.
        oe = fit.get("obs_exp") or []
        in_tol = [bool(o.get("in_range")) for o in oe] if oe else [True] * len(xd)
        if len(in_tol) != len(xd):
            in_tol = [True] * len(xd)
        ok_x = [x for x, t in zip(xd, in_tol) if t]
        ok_y = [y for y, t in zip(yd, in_tol) if t]
        bad_x = [x for x, t in zip(xd, in_tol) if not t]
        bad_y = [y for y, t in zip(yd, in_tol) if not t]

        # Fitted curve (red).
        if params is not None:
            xs = np.geomspace(max(xd.min(), 1e-9), xd.max(), 100)
            ys = curve_eval(params, xs)
            _fitname = "5PL fit" if len(params) == 5 else "4PL fit"
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines", line=dict(color=_CB_VERMILLION, width=1.4),
                name=_fitname, legendgroup="fit",
                showlegend="fit" not in shown_legend, hoverinfo="skip",
            ), row=rr_, col=cc_); shown_legend.add("fit")

        # Observed standard points (blue).
        fig.add_trace(go.Scatter(
            x=ok_x, y=ok_y, mode="markers",
            marker=dict(color="#2c7fb8", size=5),
            name="Observed", legendgroup="obs",
            showlegend="obs" not in shown_legend,
            hovertemplate="Dilution 1:%{x:.0f}<br>MFI %{y:.0f}<extra></extra>",
        ), row=rr_, col=cc_); shown_legend.add("obs")
        if bad_x:
            fig.add_trace(go.Scatter(
                x=bad_x, y=bad_y, mode="markers",
                marker=dict(color=_CB_VERMILLION, size=7, symbol="triangle-up"),
                name="Out of tolerance", legendgroup="oot",
                showlegend="oot" not in shown_legend,
                hovertemplate="Dilution 1:%{x:.0f}<br>MFI %{y:.0f}<br>out of tolerance<extra></extra>",
            ), row=rr_, col=cc_); shown_legend.add("oot")

        # Dropped / excluded standard point (✕).
        dp = fit.get("dropped_point")
        if dp and dp.get("dilution") is not None:
            fig.add_trace(go.Scatter(
                x=[dp["dilution"]], y=[dp["mfi"]], mode="markers",
                marker=dict(color="#2c3e50", size=9, symbol="x-thin",
                            line=dict(width=2, color="#2c3e50")),
                name="Dropped point", legendgroup="drop",
                showlegend="drop" not in shown_legend,
                hovertemplate="Dropped<br>Dilution 1:%{x:.0f}<br>MFI %{y:.0f}<extra></extra>",
            ), row=rr_, col=cc_); shown_legend.add("drop")

        # Current-plate specimen rug, coloured by range status. Placed just
        # right of the highest dilution as horizontal ticks.
        g = spec_by_an.get(an)
        if g is not None and not g.empty:
            rug_x = xd.max() * 1.6
            for status, col_hex in _STATUS_COLORS.items():
                gs = g[g["status"] == status]
                if gs.empty:
                    continue
                yy = gs["mfi"].astype(float).values
                names = gs.get("sample_name", pd.Series([""] * len(gs))).astype(str).values
                fig.add_trace(go.Scatter(
                    x=[rug_x] * len(yy), y=yy, mode="markers",
                    marker=dict(color=col_hex, size=9, symbol="line-ew",
                                line=dict(width=1.4, color=col_hex)),
                    name=status.replace("_", " ").title(), legendgroup=status,
                    showlegend=status not in shown_legend,
                    customdata=names,
                    hovertemplate=("%{customdata}<br>MFI %{y:.0f}<br>"
                                   + status.replace("_", " ").lower() + "<extra></extra>"),
                ), row=rr_, col=cc_); shown_legend.add(status)

        # Linear-range (reportable range) shaded square.
        box = _linear_range_box(fit)
        if box is not None:
            x0, x1, y0, y1 = box
            fig.add_shape(
                type="rect", x0=x0, x1=x1, y0=y0, y1=y1,
                line=dict(color=_CB_GREEN, width=1, dash="dash"),
                fillcolor="rgba(39,174,96,0.12)", layer="below",
                row=rr_, col=cc_,
            )

        fig.update_xaxes(type="log", tickfont=dict(size=6), row=rr_, col=cc_)
        fig.update_yaxes(type="log", tickfont=dict(size=6), row=rr_, col=cc_)

    fig.update_annotations(font_size=8)
    bottom_margin = 44
    # Reserve top-margin room so the buttons + legend sit ABOVE the grid. Their
    # y is set in PIXELS (converted to paper fraction via the grid height) so the
    # legend↔button gap is constant regardless of the number of rows — otherwise
    # short 1-row grids (Cholera/Typhoid) crush them together.
    top_margin = 104 if hist_idx else 70
    fig_h = plot_area_h + top_margin + bottom_margin
    grid_px = max(plot_area_h, 1)
    legend_y = 1 + 14 / grid_px
    buttons_y = 1 + 52 / grid_px
    layout_kw = dict(
        height=fig_h,
        margin=dict(l=45, r=20, t=top_margin, b=bottom_margin),
        plot_bgcolor="#fbfcfd",
        legend=dict(orientation="h", x=0.5, xanchor="center", y=legend_y,
                    yanchor="bottom", font=dict(size=10)),
    )
    # Show all / hide past-plate curves (default shown), like the other sections.
    if hist_idx:
        layout_kw["updatemenus"] = [dict(
            type="buttons", direction="right", showactive=False,
            x=0, xanchor="left", y=buttons_y, yanchor="bottom", pad=dict(t=2, r=2),
            font=dict(size=10),
            buttons=[
                dict(label="Show all past plates", method="restyle",
                     args=[{"visible": True}, hist_idx]),
                dict(label="Hide past plates", method="restyle",
                     args=[{"visible": "legendonly"}, hist_idx]),
            ],
        )]
    fig.update_layout(**layout_kw)
    return _plotly_html(fig, div_id, height=fig_h)


def _make_curve_grid_static(pool_fits: dict, excluded: set[str], cols: int = 10) -> str:
    """Static matplotlib small-multiples (used when there are too many panels
    for the interactive grid). Includes the green linear-range square."""
    analytes = list(pool_fits.keys())
    n = len(analytes)
    rows = (n + cols - 1) // cols
    panel_w, panel_h = 1.6, 1.05
    fig, axes = plt.subplots(rows, cols, figsize=(cols * panel_w, rows * panel_h), squeeze=False)

    for i, an in enumerate(analytes):
        r, c = divmod(i, cols)
        ax = axes[r][c]
        fit = pool_fits[an]
        std = fit.get("mean_data")
        params = fit.get("params")
        title_color = ("#95a5a6" if an in excluded
                       else _CB_GREEN if fit.get("fit_ok") else _CB_VERMILLION)
        if std is not None and not std.empty:
            box = _linear_range_box(fit)
            if box is not None:
                x0, x1, y0, y1 = box
                ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0,
                             facecolor=_CB_GREEN, alpha=0.12, edgecolor=_CB_GREEN,
                             linewidth=0.6, linestyle="--", zorder=1))
            ax.scatter(std["dilution"], std["mfi"], s=10, color="#2c7fb8", zorder=3)
            if params is not None:
                xs = np.geomspace(std["dilution"].min(), std["dilution"].max(), 80)
                ax.plot(xs, curve_eval(params, xs), color=_CB_VERMILLION, linewidth=1.2, zorder=2)
            ax.set_xscale("log"); ax.set_yscale("log")
        ax.tick_params(labelsize=5, length=2, pad=1)
        title = an if len(an) <= 20 else an[:18] + "…"
        ax.set_title(title, fontsize=6.5, color=title_color, pad=2)

    for j in range(n, rows * cols):
        r, c = divmod(j, cols)
        axes[r][c].axis("off")

    plt.tight_layout(pad=0.4, h_pad=0.6, w_pad=0.4)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return (
        f'<img src="data:image/png;base64,{b64}" alt="All {n} standard curves" '
        f'style="width:100%; height:auto; display:block;">'
    )


_BOX_SHORT_RE = re.compile(r"^(Box\d+)", re.IGNORECASE)
_PLATE_DATE_RE = re.compile(r"^PLATE_(\d{2})(\d{2})(\d{4})_RUN(\d+)$", re.IGNORECASE)


def _short_plate_label(plate_id: str | None, box_ids: str | list[str] | None) -> str:
    """Compact legend-friendly plate label.

    ``PLATE_05112026_RUN000`` → ``05/11/2026 · R0`` (run number stripped of
    padding zeros).  When a Box xlsx is attached the leading ``Box\\d+``
    is appended: ``05/11/2026 · R0 · Box1``.  Falls back to the full
    ``_plate_label`` output when the plate_id doesn't match the
    expected pattern.
    """
    if not plate_id:
        return ""
    m = _PLATE_DATE_RE.match(str(plate_id))
    if not m:
        return _plate_label(plate_id, box_ids)
    mm, dd, yyyy, run = m.group(1), m.group(2), m.group(3), m.group(4)
    short = f"{mm}/{dd}/{yyyy} · R{int(run)}"
    if box_ids is None or (isinstance(box_ids, str) and not box_ids.strip()):
        return short
    if isinstance(box_ids, str):
        raw = [b.strip() for b in box_ids.split(",") if b.strip()]
    else:
        raw = [str(b).strip() for b in box_ids if str(b).strip()]
    boxes = []
    for b in raw:
        bm = _BOX_SHORT_RE.match(b)
        boxes.append(bm.group(1) if bm else b)
    if not boxes:
        return short
    return f"{short} · {', '.join(boxes)}"


def _plate_label(plate_id: str | None, box_ids: str | list[str] | None) -> str:
    """Compose a human-readable plate label, e.g.

        PLATE_05112026_RUN000               # no box info
        PLATE_05112026_RUN000 · Box1        # one box (long-form
                                              Container Id 'Box1_Uvira_sera_2023'
                                              is shortened to 'Box1')
        PLATE_05112026_RUN000 · Box1, Box2  # multi-box plate

    ``box_ids`` may be a comma-separated string (the format stored in
    history) or a list of strings (the layout-info format).
    """
    if not plate_id:
        return ""
    if box_ids is None or (isinstance(box_ids, str) and not box_ids.strip()):
        return str(plate_id)
    if isinstance(box_ids, str):
        raw = [b.strip() for b in box_ids.split(",") if b.strip()]
    else:
        raw = [str(b).strip() for b in box_ids if str(b).strip()]
    if not raw:
        return str(plate_id)
    boxes = []
    for b in raw:
        m = _BOX_SHORT_RE.match(b)
        boxes.append(m.group(1) if m else b)
    return f"{plate_id} · {', '.join(boxes)}"


def _hist_fits_by_analyte(history_fit, current_plate_id: str | None) -> dict[str, list[dict]]:
    """Flatten ``history_fit`` (dict-of-DataFrames *or* single DataFrame
    *or* None) into ``{analyte: [{plate_id, params}, …]}``.

    Drops rows for the current plate (those are rendered as the live
    fit) and rows missing any of the four 4PL parameters.
    """
    if history_fit is None:
        return {}
    frames: list[pd.DataFrame] = []
    if isinstance(history_fit, dict):
        for v in history_fit.values():
            if isinstance(v, pd.DataFrame) and not v.empty:
                frames.append(v)
    elif isinstance(history_fit, pd.DataFrame):
        if not history_fit.empty:
            frames.append(history_fit)
    if not frames:
        return {}
    df = pd.concat(frames, ignore_index=True)
    if current_plate_id and "plate_id" in df.columns:
        df = df[df["plate_id"] != current_plate_id]
    needed = {"analyte", "a", "b", "c", "d"}
    if not needed.issubset(df.columns):
        return {}
    df = df.dropna(subset=["a", "b", "c", "d"])
    out: dict[str, list[dict]] = {}
    for r in df.itertuples(index=False):
        pr = [float(r.a), float(r.b), float(r.c), float(r.d)]
        gg = getattr(r, "g", None)
        try:
            if gg is not None and float(gg) == float(gg):
                pr.append(float(gg))
        except (TypeError, ValueError):
            pass
        out.setdefault(r.analyte, []).append({
            "plate_id": getattr(r, "plate_id", ""),
            "box_ids": getattr(r, "box_ids", ""),
            "params": tuple(pr),
        })
    return out


def _make_curve_picker(
    fits: dict,
    excluded: set[str],
    antigens: list[str] | None = None,
    in_range: pd.DataFrame | None = None,
    history_specimens: pd.DataFrame | None = None,
    history_fit: dict | pd.DataFrame | None = None,
    current_plate_id: str | None = None,
    current_run_date=None,
    current_box_ids: list[str] | None = None,
) -> str:
    """On-demand standard-curve explorer.

    Pick an antigen (typeahead) and a control pool (dropdown) to draw that
    (pool x antigen) 4PL fit + reportable range, with the current plate's
    specimen rug (coloured by range status) and legend-toggleable historical
    overlays (one curve + rug column per past plate; toggling a plate hides
    both). Only one figure is rendered client-side per selection, so it stays
    fast even across the full 200-antigen panel. "Past" = plates run before the
    current one (by run_date).
    """
    pools = list(fits.keys())
    if not pools:
        return "<p style='color:#999;'>No standard curve fits.</p>"
    present = {a for pf in fits.values() for a in pf}
    order = [a for a in (antigens or []) if a in present]
    for a in sorted(present):
        if a not in order:
            order.append(a)

    def _entry(fit):
        std = fit.get("mean_data")
        std_pts = ([[float(d), round(float(m), 2)]
                    for d, m in zip(std["dilution"], std["mfi"]) if pd.notna(m)]
                   if std is not None and not std.empty else [])
        params = fit.get("params")
        p = [float(x) for x in params] if params is not None else None
        box = _linear_range_box(fit)
        boxj = [round(float(v), 4) for v in box] if box else None
        oot = []
        oe = fit.get("obs_exp") or []
        if std is not None and not std.empty and oe and len(oe) == len(std):
            for d, m, o in zip(std["dilution"], std["mfi"], oe):
                if pd.notna(m) and not (o or {}).get("in_range", True):
                    oot.append([float(d), round(float(m), 2)])
        dp = fit.get("dropped_point")
        drop = ([float(dp["dilution"]), round(float(dp["mfi"]), 2)]
                if dp and dp.get("dilution") is not None and dp.get("mfi") is not None else None)
        return {"p": p, "ok": bool(fit.get("fit_ok")), "std": std_pts,
                "box": boxj, "oot": oot, "drop": drop}

    cur = {}
    for pool in pools:
        pf = fits[pool]
        cur[pool] = {a: _entry(pf[a]) for a in order if a in pf}

    rug = {}
    if in_range is not None and not in_range.empty and "mfi" in in_range.columns:
        for a, g in in_range.groupby("analyte", sort=False):
            vals = g["mfi"].dropna().astype(float)
            if len(vals):
                rug[a] = [round(float(v), 1) for v in vals.values]

    past_ids = (_past_plate_ids(history_specimens, current_plate_id, current_run_date)
                if isinstance(history_specimens, pd.DataFrame) and not history_specimens.empty
                else [])
    hrug = {}
    if past_ids and isinstance(history_specimens, pd.DataFrame):
        hs = history_specimens[history_specimens["plate_id"].isin(past_ids)]
        for (a, p), g in hs.groupby(["analyte", "plate_id"], sort=False):
            vals = g["mfi"].dropna().astype(float)
            if len(vals):
                hrug.setdefault(a, {})[str(p)] = [round(float(v), 1) for v in vals.values]
    hfit = {}
    if isinstance(history_fit, dict):
        for pool, dfp in history_fit.items():
            if not isinstance(dfp, pd.DataFrame) or dfp.empty or "plate_id" not in dfp.columns:
                continue
            sub = dfp[dfp["plate_id"].isin(past_ids)]
            d2 = {}
            for r in sub.itertuples(index=False):
                try:
                    pr = [float(r.a), float(r.b), float(r.c), float(r.d)]
                except Exception:
                    continue
                if any(v != v for v in pr):
                    continue
                gg = getattr(r, "g", None)
                try:
                    if gg is not None and float(gg) == float(gg):
                        pr.append(float(gg))
                except (TypeError, ValueError):
                    pass
                d2.setdefault(r.analyte, []).append(
                    {"plate": str(getattr(r, "plate_id", "")), "p": pr})
            if d2:
                hfit[pool] = d2

    # Rug columns/legend run current → nearest-past → oldest. ``past_ids`` is
    # chronological ascending (oldest→newest), so reverse it for nearest-first.
    past_ordered = list(reversed(past_ids))
    data = {
        "pools": pools, "ants": order, "cur": cur, "rug": rug,
        "hrug": hrug, "hfit": hfit, "past": [str(p) for p in past_ordered],
        "curlabel": (_short_plate_label(current_plate_id, current_box_ids) or "This run"),
        "colors": {
            "BELOW": _STATUS_COLORS["BELOW_RANGE"], "IN": _STATUS_COLORS["IN_RANGE"],
            "ABOVE": _STATUS_COLORS["ABOVE_RANGE"], "NOFIT": _STATUS_COLORS["NO_FIT"],
            "fit": _CB_VERMILLION, "std": "#2c3e50", "box": _CB_GREEN, "grey": _CB_GREY,
        },
    }
    data_js = json.dumps(data).replace("</", "<\\/")
    options_html = "\n".join(f'<option value="{html.escape(a)}">' for a in order)
    pool_opts = "\n".join(
        f'<option value="{html.escape(p)}">{html.escape(p)}</option>' for p in pools)
    first_ant = json.dumps(order[0] if order else "")
    first_pool = json.dumps(pools[0])

    tmpl = """
<style>
  .cp-field { display:flex; flex-direction:column; }
  .cp-field > label { font-size:13px; color:#34495e; font-weight:600; margin-bottom:3px; }
  .cp-ctrl { height:34px; box-sizing:border-box; padding:6px 10px; font-size:13px;
             border:1px solid #d0d7de; border-radius:4px; background:#fff; }
</style>
<div style="display:flex; gap:14px; align-items:flex-end; flex-wrap:wrap; margin:6px 0 10px;">
  <div class="cp-field">
    <label for="cp-ant">Antigen</label>
    <input id="cp-ant" class="cp-ctrl" list="cp-ant-list" autocomplete="off"
           placeholder="Search antigen, e.g. RES_Ade3" style="min-width:300px;">
    <datalist id="cp-ant-list">__OPTIONS__</datalist>
  </div>
  <div class="cp-field">
    <label for="cp-pool">Standard pool</label>
    <select id="cp-pool" class="cp-ctrl" style="min-width:220px;">__POOLOPTS__</select>
  </div>
</div>
<div style="max-width:100%; overflow-x:auto; border:1px solid #e1e4e8; border-radius:4px;">
  <div id="fig-curve-picker"></div>
</div>
<script>
(function () {
  var D = __DATA__;
  var DIV = "fig-curve-picker";
  var antEl = document.getElementById("cp-ant");
  var poolEl = document.getElementById("cp-pool");

  // Curve eval: 4 params → 4PL, 5 params → 5PL (p[4] = asymmetry g). Each past
  // plate is drawn under the model it was fit with (Option A).
  function curve(x, p) {
    var base = 1 + Math.pow(x/p[2], p[1]);
    var denom = (p.length === 5) ? Math.pow(base, p[4]) : base;
    return p[3] + (p[0]-p[3]) / denom;
  }
  function geomspace(a, b, n) {
    if (!(a>0)) a = 1e-6; var out=[], la=Math.log(a), lb=Math.log(b);
    for (var i=0;i<n;i++) out.push(Math.exp(la + (lb-la)*i/(n-1))); return out;
  }
  function classify(m, box) {
    if (!box) return "NOFIT";
    if (m < box[2]) return "BELOW";
    if (m > box[3]) return "ABOVE";
    return "IN";
  }

  function draw() {
    var ant = antEl.value, pool = poolEl.value;
    if (D.ants.indexOf(ant) < 0) ant = D.ants[0];
    if (D.pools.indexOf(pool) < 0) pool = D.pools[0];
    var e = (D.cur[pool] || {})[ant];
    var traces = [], shapes = [], pastIdx = [];
    var pastN = D.past.length;

    // ----- historical curves (grey, per past plate) -----
    var hf = (D.hfit[pool] || {})[ant] || [];
    var stdAll = (e && e.std) ? e.std.map(function(d){return d[0];}) : [];
    hf.forEach(function (h) {
      var xs = (stdAll.length ? geomspace(Math.min.apply(null,stdAll), Math.max.apply(null,stdAll), 60)
                              : geomspace(1, 100000, 60));
      var ys = xs.map(function (x) { return curve(x, h.p); });
      var hm = (h.p.length === 5) ? "5PL" : "4PL";
      pastIdx.push(traces.length);
      traces.push({x:xs, y:ys, mode:"lines", line:{color:D.colors.grey, width:1, dash:"dot"},
                   name:h.plate, legendgroup:"plate:"+h.plate,
                   hovertemplate: h.plate+" · "+hm+" (as fit)<br>1:%{x:.0f}<br>MFI %{y:.0f}<extra></extra>",
                   xaxis:"x", yaxis:"y"});
    });

    // ----- current standards + fit + box + oot + dropped -----
    if (e) {
      if (e.std.length) {
        traces.push({x:e.std.map(function(d){return d[0];}), y:e.std.map(function(d){return d[1];}),
          mode:"markers", marker:{size:8, color:D.colors.std}, name:"Standards",
          hovertemplate:"Dilution 1:%{x:.0f}<br>MFI %{y:.0f}<extra></extra>", xaxis:"x", yaxis:"y"});
      }
      if (e.p && e.std.length) {
        var xs = geomspace(Math.min.apply(null,stdAll), Math.max.apply(null,stdAll), 80);
        var fitName = (e.p.length === 5) ? "5PL fit" : "4PL fit";
        traces.push({x:xs, y:xs.map(function(x){return curve(x, e.p);}), mode:"lines",
          line:{color:D.colors.fit, width:2}, name:fitName, hoverinfo:"skip", xaxis:"x", yaxis:"y"});
      }
      if (e.oot && e.oot.length) {
        traces.push({x:e.oot.map(function(d){return d[0];}), y:e.oot.map(function(d){return d[1];}),
          mode:"markers", marker:{size:9, color:D.colors.fit, symbol:"triangle-up"},
          name:"Out of tolerance", hovertemplate:"Dilution 1:%{x:.0f}<br>MFI %{y:.0f}<br>out of tolerance<extra></extra>",
          xaxis:"x", yaxis:"y"});
      }
      if (e.drop) {
        traces.push({x:[e.drop[0]], y:[e.drop[1]], mode:"markers",
          marker:{size:10, color:"#2c3e50", symbol:"x-thin", line:{width:2, color:"#2c3e50"}},
          name:"Dropped point", hovertemplate:"Dropped<br>Dilution 1:%{x:.0f}<br>MFI %{y:.0f}<extra></extra>",
          xaxis:"x", yaxis:"y"});
      }
      if (e.box) {
        shapes.push({type:"rect", xref:"x", yref:"y", x0:e.box[0], x1:e.box[1], y0:e.box[2], y1:e.box[3],
          line:{color:D.colors.box, width:1, dash:"dash"}, fillcolor:"rgba(0,158,115,0.12)", layer:"below"});
      }
    }

    // ----- rug (xaxis2): current at x=0, each past plate at x=1..P -----
    var box = e ? e.box : null;
    var curMfi = D.rug[ant] || [];
    var counts = {BELOW:0, IN:0, ABOVE:0, NOFIT:0};
    var byStatus = {BELOW:[], IN:[], ABOVE:[], NOFIT:[]};
    curMfi.forEach(function (m) { var s = classify(m, box); counts[s]++; byStatus[s].push(m); });
    var slbl = {BELOW:"BELOW", IN:"IN", ABOVE:"ABOVE", NOFIT:"NO_FIT"};
    ["BELOW","IN","ABOVE","NOFIT"].forEach(function (s) {
      if (byStatus[s].length) {
        traces.push({x:byStatus[s].map(function(){return 0;}), y:byStatus[s], mode:"markers",
          marker:{symbol:"line-ew-open", size:13, color:D.colors[s], line:{width:2, color:D.colors[s]}},
          name:slbl[s]+" (this plate)", legendgroup:"cur", showlegend:false, xaxis:"x2", yaxis:"y",
          hovertemplate:slbl[s]+"<br>MFI %{y:.0f}<extra></extra>"});
      }
    });
    var ticktext = [D.curlabel], tickvals = [0];
    D.past.forEach(function (p, i) {
      tickvals.push(i+1); ticktext.push(p);
      var ms = ((D.hrug[ant] || {})[p]) || [];
      if (ms.length) {
        // Colour past-plate specimens by the SAME range status as the current
        // plate (classified against the selected pool's box), at higher
        // transparency so prior out-of-range samples stand out but stay muted.
        var pByStatus = {BELOW:[], IN:[], ABOVE:[], NOFIT:[]};
        ms.forEach(function (m) { pByStatus[classify(m, box)].push(m); });
        ["BELOW","IN","ABOVE","NOFIT"].forEach(function (s) {
          if (!pByStatus[s].length) return;
          pastIdx.push(traces.length);
          traces.push({x:pByStatus[s].map(function(){return i+1;}), y:pByStatus[s], mode:"markers",
            marker:{symbol:"line-ew-open", size:11, color:D.colors[s], opacity:0.45,
                    line:{width:1.5, color:D.colors[s]}},
            name:p, legendgroup:"plate:"+p, showlegend:false, xaxis:"x2", yaxis:"y",
            hovertemplate:p+"<br>"+slbl[s]+"<br>MFI %{y:.0f}<extra></extra>"});
        });
      }
    });

    var tot = curMfi.length || 1;
    function pct(n){ return Math.round(100*n/tot); }
    // In-plot status box (compact, upper-right of the curve panel) — one line each.
    var boxText = "<b>This plate · " + curMfi.length + " specimens</b><br>" +
      "<span style='color:"+D.colors.IN+"'>IN " + counts.IN + " (" + pct(counts.IN) + "%)</span><br>" +
      "<span style='color:"+D.colors.BELOW+"'>BELOW " + counts.BELOW + " (" + pct(counts.BELOW) + "%)</span><br>" +
      "<span style='color:"+D.colors.ABOVE+"'>ABOVE " + counts.ABOVE + " (" + pct(counts.ABOVE) + "%)</span><br>" +
      "<span style='color:"+D.colors.NOFIT+"'>NO FIT " + counts.NOFIT + " (" + pct(counts.NOFIT) + "%)</span><br>" +
      "<span style='color:#7f8c8d'>fit OK: " + (e ? (e.ok ? "yes" : "no") : "—") + "</span>";

    // Layout: curve | rug, with a vertical "click to toggle" legend in the
    // right margin and the toggle buttons above (no overlap).
    // Size the rug to a fixed pixel width per column so columns pack tightly
    // (no wasted side space), while the curve keeps a generous fixed width.
    var nCols = 1 + pastN;
    var CURVE_PX = 720, GAP_PX = 30, RUG_COL_PX = 46, L = 60, R = 180;
    var plotAreaW = CURVE_PX + GAP_PX + RUG_COL_PX * nCols;
    var width = L + plotAreaW + R;
    var curveEnd = CURVE_PX / plotAreaW;
    var rugStart2 = (CURVE_PX + GAP_PX) / plotAreaW;
    var layout = {
      // Rug plate labels sit at the TOP (vertical), so the bottom margin only
      // holds the curve's Dilution axis; top margin holds the vertical labels.
      width: width, height: 640, margin:{l:L, r:R, t:140, b:64},
      showlegend:true, hovermode:"closest", plot_bgcolor:"#fbfcfd",
      // Status box (top) + legend (below) live in the right margin, so neither
      // overlaps the curve / reportable-range box.
      legend:{title:{text:"Click to toggle", font:{size:10, color:"#7f8c8d"}},
              orientation:"v", x:1.01, xanchor:"left", y:0.60, yanchor:"top", font:{size:10}},
      shapes: shapes,
      annotations: [{
        xref:"paper", yref:"paper", x:1.01, y:1.0, xanchor:"left", yanchor:"top",
        align:"left", text:boxText, showarrow:false, bordercolor:"#d0d7de", borderwidth:1,
        bgcolor:"rgba(255,255,255,0.92)", font:{size:9},
      }, {
        // Antigen × pool title, using the free top-left space above the curve.
        xref:"paper", yref:"paper", x:0, y:1.12, xanchor:"left", yanchor:"bottom",
        align:"left", showarrow:false, font:{size:14, color:"#2c3e50"},
        text:"<b>"+ant+"</b>  <span style='color:#7f8c8d;'>×  "+pool+"</span>",
      }],
      xaxis:{domain:[0, curveEnd], type:"log", title:{text:"Standard dilution (1:x)", font:{size:12}},
             gridcolor:"#eef1f4"},
      xaxis2:{domain:[rugStart2, 1], side:"top", tickmode:"array", tickvals:tickvals, ticktext:ticktext,
              tickangle:-90, tickfont:{size:8}, range:[-0.55, (nCols-1)+0.55],
              title:{text:"Plate run (current → oldest)", font:{size:10, color:"#7f8c8d"}}},
      yaxis:{type:"log", title:{text:"MFI (log scale)", font:{size:12}, standoff:8},
             gridcolor:"#eef1f4"},
    };
    if (pastIdx.length) {
      layout.updatemenus = [{
        type:"buttons", direction:"right", showactive:false,
        x:0, xanchor:"left", y:1.02, yanchor:"bottom", font:{size:10}, pad:{t:2,r:2},
        buttons:[
          {label:"Show all past plates", method:"restyle", args:[{"visible":true}, pastIdx]},
          {label:"Hide past plates", method:"restyle", args:[{"visible":"legendonly"}, pastIdx]},
        ],
      }];
    }
    Plotly.newPlot(DIV, traces, layout, {displaylogo:false, responsive:false});
  }

  antEl.value = __FIRST_ANT__;
  // default pool: the first that has a fit for the first antigen, else first pool
  (function () {
    var a = antEl.value, chosen = __FIRST_POOL__;
    for (var i=0;i<D.pools.length;i++){ if ((D.cur[D.pools[i]]||{})[a]){ chosen = D.pools[i]; break; } }
    poolEl.value = chosen;
  })();
  antEl.addEventListener("change", draw);
  antEl.addEventListener("input", function(){ if (D.ants.indexOf(antEl.value)>=0) draw(); });
  poolEl.addEventListener("change", draw);
  draw();
})();
</script>
"""
    return (tmpl
            .replace("__OPTIONS__", options_html)
            .replace("__POOLOPTS__", pool_opts)
            .replace("__DATA__", data_js)
            .replace("__FIRST_ANT__", first_ant)
            .replace("__FIRST_POOL__", first_pool))


def _xrun_overlap(in_range, history_specimens, current_plate_id):
    """(matched, total) specimens: how many of this plate's specimen wells have a
    sample (patient_id > barcode > sample_name) that also appears on a past plate."""
    def _keys(df):
        s = pd.Series("", index=df.index, dtype="object")
        for c in ("sample_name", "barcode", "patient_id"):  # ascending priority
            if c in df.columns:
                v = df[c].astype("string").fillna("").str.strip()
                s = s.mask(v != "", v)
        return s
    if in_range is None or not isinstance(in_range, pd.DataFrame) or in_range.empty:
        return 0, 0
    cur = in_range.drop_duplicates("well")
    total = int(cur.shape[0])
    if (history_specimens is None or not isinstance(history_specimens, pd.DataFrame)
            or history_specimens.empty):
        return 0, total
    past = history_specimens
    if current_plate_id and "plate_id" in past.columns:
        past = past[past["plate_id"] != current_plate_id]
    if past.empty:
        return 0, total
    pk = set(k for k in _keys(past).tolist() if k)
    ck = _keys(cur)
    matched = int(ck[(ck != "") & ck.isin(pk)].shape[0])
    return matched, total


def _make_cross_run_scatter(
    pool_fits: dict,
    excluded: set[str],
    in_range: pd.DataFrame | None,
    history_specimens: pd.DataFrame | None,
    current_plate_id: str | None,
    current_box_ids: list[str] | None,
) -> str:
    """Antigen-switching scatter comparing this run's specimen MFI to
    each past run's MFI for the same sample.

    For the selected antigen, every sample that appears on the current
    plate **and** a past plate produces one point at
    ``(current_mfi, past_mfi)``. Samples are joined preferentially on
    ``patient_id`` and fall back to ``barcode`` / ``sample_name`` when
    no patient ID is known. One trace per past plate (legend-toggleable);
    a faint y=x reference line shows where perfect agreement would land.

    Returns the HTML for a self-contained figure + typeahead lookup
    that drives `Plotly.update` on antigen change. Returns an empty
    string when there are no past plates or no joinable samples.
    """
    if not pool_fits or in_range is None or in_range.empty:
        return ""
    if history_specimens is None or not isinstance(history_specimens, pd.DataFrame) or history_specimens.empty:
        return ""

    # Filter history to past plates only.
    hist = history_specimens
    if current_plate_id and "plate_id" in hist.columns:
        hist = hist[hist["plate_id"] != current_plate_id]
    if hist.empty:
        return ""

    # Plate roster (chronological where run_date is known).
    if "run_date" in hist.columns:
        rd_by_plate = (
            hist.groupby("plate_id")["run_date"]
            .agg(lambda s: s.dropna().iloc[0] if s.dropna().size else "")
        )
        past_plates = sorted(rd_by_plate.index, key=lambda p: (rd_by_plate.get(p, ""), p))
    else:
        past_plates = sorted(hist["plate_id"].dropna().astype(str).unique())
    if not past_plates:
        return ""

    box_by_plate: dict[str, str] = {}
    if "box_id" in hist.columns:
        for p, g in hist.groupby("plate_id"):
            boxes = sorted({str(b) for b in g["box_id"].dropna().unique() if str(b).strip()})
            if boxes:
                box_by_plate[str(p)] = ",".join(boxes)

    analytes = list(pool_fits.keys())

    # Build a per-(analyte, plate) lookup of joined samples.
    # Sample identity preference: patient_id > barcode > sample_name.
    def _sample_key(row) -> str:
        for col in ("patient_id", "barcode", "sample_name"):
            v = row.get(col, "")
            if isinstance(v, str) and v.strip():
                return v
            if v not in (None, "") and not pd.isna(v):
                return str(v)
        return ""

    cur_by_an: dict[str, dict[str, dict]] = {}
    for an, g in in_range.groupby("analyte", sort=False):
        cur_by_an[an] = {}
        for r in g.to_dict(orient="records"):
            k = _sample_key(r)
            if k:
                cur_by_an[an][k] = r

    hist_by_an_plate: dict[tuple[str, str], dict[str, dict]] = {}
    for (plate, an), g in hist.groupby(["plate_id", "analyte"], sort=False):
        d: dict[str, dict] = {}
        for r in g.to_dict(orient="records"):
            k = _sample_key(r)
            if k:
                d[k] = r
        hist_by_an_plate[(str(plate), an)] = d

    # CB-safe palette (matches the picker).
    palette = ["#4477AA", "#EE7733", "#44AA99", "#CCBB44",
               "#AA3377", "#66CCEE", "#7f8c8d", "#228833"]

    # Trace counts are computed after the build loop (see below) — we
    # need to know how many anchor traces get appended.
    fig = go.Figure()

    # Reference line (added first so it sits behind the scatter).
    # Spans the entire log-MFI range we'll likely use; clipped to axis.
    fig.add_trace(go.Scatter(
        x=[1, 1e6], y=[1, 1e6], mode="lines",
        line=dict(color="#bdc3c7", width=1, dash="dot"),
        name="y = x (perfect agreement)",
        hoverinfo="skip", showlegend=True, visible=True,
    ))

    # One trace per (antigen, past_plate). Only antigen-0's traces are
    # visible initially; typeahead lookup toggles which antigen is shown.
    cur_label_full = _plate_label(current_plate_id, current_box_ids) or "this run"
    for ai, an in enumerate(analytes):
        for pi, plate in enumerate(past_plates):
            plate_full  = _plate_label(plate, box_by_plate.get(plate, ""))
            plate_short = _short_plate_label(plate, box_by_plate.get(plate, ""))
            cur_d  = cur_by_an.get(an, {})
            hist_d = hist_by_an_plate.get((plate, an), {})
            xs, ys, cust = [], [], []
            for k in cur_d.keys() & hist_d.keys():
                cr, hr = cur_d[k], hist_d[k]
                cx, cy = cr.get("mfi"), hr.get("mfi")
                if cx is None or cy is None: continue
                try:
                    fx, fy = float(cx), float(cy)
                except (TypeError, ValueError):
                    continue
                if not (fx > 0 and fy > 0): continue  # log axes
                xs.append(fx); ys.append(fy)
                cust.append([
                    plate_full,                       # 0
                    str(cr.get("sample_name") or ""), # 1 — current sample/barcode
                    str(cr.get("well") or ""),        # 2 — current well
                    str(cr.get("patient_id") or ""),  # 3 — patient id
                    str(hr.get("well") or ""),        # 4 — past well
                ])
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="markers",
                marker=dict(size=7, color=palette[pi % len(palette)],
                            opacity=0.75, line=dict(width=0)),
                name="",
                legendgroup=f"plate:{plate}",
                # showlegend=False on every per-antigen trace; the
                # legend entries are anchored on always-visible traces
                # appended after the per-antigen loop (see below). This
                # makes the legend persist across antigen typeahead
                # switches; without anchors the legend would only show
                # the first antigen's traces and toggling them would
                # have no visible effect on subsequent antigens.
                showlegend=False,
                customdata=cust,
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "Sample: %{customdata[1]}<br>"
                    "Patient ID: %{customdata[3]}<br>"
                    "Well — this run: %{customdata[2]} · past run: %{customdata[4]}<br>"
                    f"<b>{cur_label_full}</b> MFI: %{{x:.0f}}<br>"
                    f"<b>%{{customdata[0]}}</b> MFI: %{{y:.0f}}"
                    "<extra></extra>"
                ),
                visible=(ai == 0),
            ))

    # ----- Legend-anchor traces (one per past plate) -----
    # Always-visible placeholder traces that host the per-plate legend
    # entries. Live OUTSIDE the per-antigen scheme so the legend stays
    # populated regardless of which antigen is selected. Click is
    # intercepted by the JS shim which manages a hiddenPlates set and
    # overrides Plotly's default toggle behaviour.
    for pi, plate in enumerate(past_plates):
        plate_short = _short_plate_label(plate, box_by_plate.get(plate, ""))
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(size=7, color=palette[pi % len(palette)],
                        opacity=0.85, line=dict(width=0)),
            name=plate_short,
            legendgroup=f"plate:{plate}",
            showlegend=True, visible=True,
            hoverinfo="skip",
        ))

    # Layout
    fig.update_layout(
        margin=dict(l=70, r=160, t=70, b=60),
        height=460,
        title=dict(text=(
            f"<b>{('⚠ ' if analytes[0] in excluded else '') + analytes[0]}</b>"
            " &nbsp;·&nbsp; current-run MFI vs past-run MFI"
        )),
        xaxis=dict(
            type="log",
            title=f"This run ({_short_plate_label(current_plate_id, current_box_ids)}) — MFI",
            gridcolor="#eef1f4",
        ),
        yaxis=dict(
            type="log",
            title="Past run — MFI",
            gridcolor="#eef1f4",
        ),
        showlegend=True,
        legend=dict(
            title=dict(text="Past run · click to toggle",
                       font=dict(size=10, color="#7f8c8d")),
            orientation="v",
            x=1.01, xanchor="left", y=1.0, yanchor="top",
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#d0d7de", borderwidth=1,
            font=dict(size=10),
        ),
    )
    fig_html = _plotly_html(fig, "fig-cross-run", height=480)

    # ----- Trace layout -----
    # Index 0:                  y=x reference line (always visible)
    # Indices 1 .. n_per_analyte:  one trace per past plate, per antigen
    #                              (only the active antigen's are visible)
    # Tail indices:             P anchor traces (always visible, host the
    #                              legend entries — see comment above)
    n_past = len(past_plates)
    n_per_analyte = n_past
    n_total = 1 + len(analytes) * n_per_analyte + n_past

    # ``trace_plate_map``: plate_id for every trace whose visibility is
    # controlled by the per-plate legend toggle; null otherwise.
    trace_plate_map: list[str | None] = [None]  # trace 0 = ref line
    for _ai in range(len(analytes)):
        for plate in past_plates:
            trace_plate_map.append(plate)
    for plate in past_plates:
        trace_plate_map.append(plate)
    assert len(trace_plate_map) == n_total

    # Typeahead lookup: per-antigen visibility array (length n_total).
    lookup: dict[str, dict] = {}
    for ai, an in enumerate(analytes):
        vis: list = [False] * n_total
        vis[0] = True  # reference line
        for k in range(n_past):
            vis[1 + ai * n_per_analyte + k] = True
        # Anchor traces (tail) — always visible by default; the JS
        # shim downgrades to "legendonly" for any plate the user hid.
        for idx in range(1 + len(analytes) * n_per_analyte, n_total):
            vis[idx] = True
        label = f"⚠ {an} (excluded)" if an in excluded else an
        title = (
            f"<b>{label}</b> &nbsp;·&nbsp; "
            "current-run MFI vs past-run MFI"
        )
        lookup[an] = {"vis": vis, "title": title}

    lookup_js = json.dumps(lookup).replace("</", "<\\/")
    trace_plate_map_js = json.dumps(trace_plate_map).replace("</", "<\\/")
    past_plates_js = json.dumps(past_plates).replace("</", "<\\/")
    first_antigen_js = json.dumps(analytes[0])
    options_html = "\n".join(f'<option value="{html.escape(a)}">' for a in analytes)
    typeahead_html = f"""
<div style="display:flex; gap:10px; align-items:center; margin: 4px 0 8px;">
  <label for="cross-run-input" style="font-size:13px; color:#34495e; font-weight:600;">
    Search antigen:
  </label>
  <input id="cross-run-input" list="cross-run-list"
         placeholder="Search antigen, e.g. RES_Ade3"
         autocomplete="off"
         style="flex:1; max-width:340px; padding:6px 10px; font-size:13px;
                border:1px solid #d0d7de; border-radius:4px;">
  <datalist id="cross-run-list">
    {options_html}
  </datalist>
  <span id="cross-run-status" style="font-size:12px; color:#7f8c8d;"></span>
</div>
<script>
(function () {{
  var DIV = "fig-cross-run";
  var lookup = {lookup_js};
  var tracePlateMap = {trace_plate_map_js};
  var pastPlates = {past_plates_js};
  var input  = document.getElementById("cross-run-input");
  var status = document.getElementById("cross-run-status");
  if (!input) return;
  var hiddenPlates = {{}};
  var currentEntry = lookup[{first_antigen_js}];

  function applyVisibility(entry) {{
    if (!entry) return;
    var vis = entry.vis.slice();
    for (var i = 0; i < vis.length; i++) {{
      var plate = tracePlateMap[i];
      if (plate && hiddenPlates[plate]) vis[i] = "legendonly";
    }}
    Plotly.restyle(DIV, {{visible: vis}});
  }}

  function wireLegend() {{
    var gd = document.getElementById(DIV);
    if (!gd || !gd.on) return;
    gd.on('plotly_legendclick', function (eventData) {{
      var plate = tracePlateMap[eventData.curveNumber];
      if (!plate) return true;  // y=x reference line — let Plotly handle.
      if (hiddenPlates[plate]) delete hiddenPlates[plate];
      else hiddenPlates[plate] = true;
      applyVisibility(currentEntry);
      return false;
    }});
    gd.on('plotly_legenddoubleclick', function (eventData) {{
      var plate = tracePlateMap[eventData.curveNumber];
      if (!plate) return true;
      var others = pastPlates.filter(function (p) {{ return p !== plate; }});
      var allHidden = others.every(function (p) {{ return hiddenPlates[p]; }});
      if (allHidden && !hiddenPlates[plate]) {{
        hiddenPlates = {{}};
      }} else {{
        hiddenPlates = {{}};
        others.forEach(function (p) {{ hiddenPlates[p] = true; }});
      }}
      applyVisibility(currentEntry);
      return false;
    }});
  }}

  function pick(name) {{
    var entry = lookup[name];
    if (!entry) {{ status.textContent = name ? "no match" : ""; return; }}
    status.textContent = "";
    currentEntry = entry;
    applyVisibility(entry);
    Plotly.relayout(DIV, "title.text", entry.title);
  }}

  input.addEventListener("change", function () {{ pick(input.value.trim()); }});
  input.addEventListener("input",  function () {{
    if (lookup[input.value.trim()]) pick(input.value.trim());
  }});
  if (document.getElementById(DIV)) wireLegend();
  else window.addEventListener("load", wireLegend);
}})();
</script>
"""
    return typeahead_html + fig_html


def _freeze_pane_heatmap(
    analyte_rows: list[str],
    well_cols: list[str],
    z: np.ndarray,
    text: np.ndarray,
    colorscale: list,
    zmin: float,
    zmax: float,
    excluded: set[str],
    div_prefix: str,
    group_boundaries: list | None = None,
    row_label_colors: dict | None = None,
    row_group_lines: list | None = None,
) -> str:
    """Wide antigen × well heatmap with BOTH headers frozen (spreadsheet-style).

    Four quadrants: a fixed corner, a frozen column header (well positions, top),
    a frozen row header (antigen names, left), and the scrolling heatmap body.
    Scrolling the body horizontally scrolls the column header in sync; scrolling
    it vertically scrolls the row header in sync (via a small JS shim) — so both
    the antigen names and the well positions stay visible at all times. The well
    position is the only thing on the column axis; the sample ID is in the hover.
    """
    n_rows = len(analyte_rows)
    n_cols = len(well_cols)
    ROW_PX, COL_PX = 10, 9
    PADT, PADB = 2, 8        # body top/bottom margins (rows align across panes)
    HDR_H = 64               # frozen column-header height (rotated well labels)
    LABEL_MARGIN = 150       # antigen-text width in the row header
    corner_w = LABEL_MARGIN + 8
    body_w = 4 + n_cols * COL_PX + 18
    body_h = PADT + n_rows * ROW_PX + PADB
    max_h = 560              # viewport height of the scrolling body
    row_label_colors = row_label_colors or {}

    def _ylabel(a: str) -> str:
        base = f"<i>{a} (excluded)</i>" if a in excluded else a
        col = row_label_colors.get(a)
        return f"<span style='color:{col}'>{base}</span>" if col else base

    y_ticktext = [_ylabel(a) for a in analyte_rows]

    # --- Body: the heatmap, no tick labels on either axis. ---
    heat = go.Figure(go.Heatmap(
        z=z, x=well_cols, y=analyte_rows, text=text, hoverinfo="text",
        colorscale=colorscale, zmin=zmin, zmax=zmax,
        showscale=False, xgap=0.5, ygap=0.5,
    ))
    heat.update_layout(
        margin=dict(l=4, r=18, t=PADT, b=PADB),
        width=body_w, height=body_h, plot_bgcolor="white",
        xaxis=dict(showticklabels=False, range=[-0.5, n_cols - 0.5],
                   tickvals=list(range(n_cols))),
        yaxis=dict(showticklabels=False, autorange="reversed",
                   range=[n_rows - 0.5, -0.5]),
    )
    if group_boundaries:
        for idx, _l, _r in group_boundaries:
            heat.add_shape(type="line", xref="x", yref="paper",
                           x0=idx - 0.5, x1=idx - 0.5, y0=0, y1=1,
                           line=dict(color="#2c3e50", width=1.2, dash="dot"),
                           opacity=0.7, layer="above")
    # Horizontal separators between pathogen row-groups (antigen axis).
    for idx in (row_group_lines or []):
        heat.add_shape(type="line", xref="paper", yref="y",
                       x0=0, x1=1, y0=idx - 0.5, y1=idx - 0.5,
                       line=dict(color="#2c3e50", width=1.0, dash="dot"),
                       opacity=0.6, layer="above")

    # --- Frozen column header: well positions only (same x geometry as body). ---
    colhdr = go.Figure(go.Heatmap(
        z=[[None] * n_cols], x=well_cols, y=[""], showscale=False, hoverinfo="skip",
    ))
    colhdr.update_layout(
        margin=dict(l=4, r=18, t=HDR_H - 6, b=2),
        width=body_w, height=HDR_H, plot_bgcolor="white",
        xaxis=dict(side="top", tickangle=-90, tickfont=dict(size=7),
                   range=[-0.5, n_cols - 0.5], tickmode="array",
                   tickvals=list(range(n_cols)), ticktext=[str(w) for w in well_cols],
                   fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True),
    )

    # --- Frozen row header: antigen names (same y geometry as body). ---
    rowhdr = go.Figure(go.Heatmap(
        z=[[None]] * n_rows, x=[""], y=analyte_rows, showscale=False, hoverinfo="skip",
    ))
    rowhdr.update_layout(
        margin=dict(l=LABEL_MARGIN, r=2, t=PADT, b=PADB),
        width=corner_w, height=body_h, plot_bgcolor="white",
        xaxis=dict(visible=False, fixedrange=True),
        yaxis=dict(side="left", tickfont=dict(size=7), autorange="reversed",
                   range=[n_rows - 0.5, -0.5], tickmode="array",
                   tickvals=list(range(n_rows)), ticktext=y_ticktext, fixedrange=True),
    )

    colhdr_html = _plotly_html(colhdr, f"{div_prefix}-colhdr", height=HDR_H, responsive=False)
    rowhdr_html = _plotly_html(rowhdr, f"{div_prefix}-rowhdr", height=body_h, responsive=False)
    heat_html = _plotly_html(heat, f"{div_prefix}-body", height=body_h, responsive=False)
    p = div_prefix
    return f"""
<div style="max-width:100%; border:1px solid #e1e4e8; border-radius:4px; overflow:hidden;">
  <div style="display:flex; flex-wrap:nowrap;">
    <div style="flex:0 0 {corner_w}px; height:{HDR_H}px; background:#fff;"></div>
    <div id="{p}-colwrap" style="flex:1 1 0; min-width:0; overflow:hidden;">{colhdr_html}</div>
  </div>
  <div style="display:flex; flex-wrap:nowrap;">
    <div id="{p}-rowwrap" style="flex:0 0 {corner_w}px; max-height:{max_h}px; overflow:hidden;">{rowhdr_html}</div>
    <div id="{p}-bodywrap" style="flex:1 1 0; min-width:0; max-height:{max_h}px; overflow:auto;">{heat_html}</div>
  </div>
  <script>(function(){{
    var body=document.getElementById("{p}-bodywrap"),
        col=document.getElementById("{p}-colwrap"),
        row=document.getElementById("{p}-rowwrap");
    if(body){{ body.addEventListener("scroll",function(){{
      if(col) col.scrollLeft=body.scrollLeft;
      if(row) row.scrollTop=body.scrollTop;
    }}); }}
  }})();</script>
</div>"""


def _make_in_range_heatmap(in_range: pd.DataFrame, excluded: set[str],
                           antigen_pool: dict | None = None,
                           pool_mode: str = "auto_select") -> str:
    if in_range is None or in_range.empty:
        return "<p style='color:#999;'>No in-range data.</p>"
    antigen_pool = antigen_pool or {}

    # Four-state classification with a colorblind-friendly scheme:
    #   BELOW_RANGE = blue, IN_RANGE = teal, ABOVE_RANGE = orange, NO_FIT = yellow.
    status_to_int = {"BELOW_RANGE": 0, "IN_RANGE": 1, "ABOVE_RANGE": 2, "NO_FIT": 3}
    pivot = in_range.pivot_table(
        index="analyte", columns="well", values="status", aggfunc="first",
    )
    base_order = list(in_range.drop_duplicates("analyte")["analyte"])
    well_order = list(in_range.drop_duplicates("well")["well"])

    # Group antigen rows by pathogen category (cholera, dengue, typhoid, other
    # arbovirus, VPD) first — so the antigens relevant to each standard sit
    # together — then all uncategorized antigens, each block in original order.
    cat_rank = {c: i for i, c in enumerate(_FEATURED_CAT_ORDER)}
    n_cats = len(_FEATURED_CAT_ORDER)

    def _rank(a):
        g = antigen_group(a)
        return (cat_rank.get(g, n_cats), base_order.index(a))

    analyte_order = sorted(base_order, key=_rank)
    # Colour each antigen label by its pathogen group; add a separator line
    # wherever the category changes (within the categorized block).
    row_label_colors, row_group_lines, present_cats = {}, [], []
    prev_cat = None
    for i, a in enumerate(analyte_order):
        g = antigen_group(a)
        if g:
            row_label_colors[a] = _PATHOGEN_COLORS.get(g, "#2c3e50")
            if g not in present_cats:
                present_cats.append(g)
        if i > 0 and g != prev_cat:
            row_group_lines.append(i)
        prev_cat = g
    pivot = pivot.reindex(index=analyte_order, columns=well_order)

    z = np.vectorize(lambda s: status_to_int.get(s, 3))(pivot.values)
    # Prefer an explicit sample_id when present, else the sample_name.
    id_col = "sample_id" if "sample_id" in in_range.columns else "sample_name"
    sample_labels = (
        in_range.drop_duplicates("well").set_index("well")[id_col].astype(str).to_dict()
    )
    status_disp = {"BELOW_RANGE": "Below range", "IN_RANGE": "In range",
                   "ABOVE_RANGE": "Above range", "NO_FIT": "No fit"}
    # Per-antigen calibrating standard for the hover (so the range call's basis
    # is explicit — especially for uncalibrated/best-fit antigens).
    an_std = {a: (f"{antigen_pool.get(a, '—')} · {CALIBRATION_LABELS[antigen_calibration(a, antigen_pool.get(a))]}")
              for a in analyte_order}
    text = np.empty(z.shape, dtype=object)
    for i, an in enumerate(analyte_order):
        for j, w in enumerate(well_order):
            status = pivot.iat[i, j]
            sid = sample_labels.get(w, "") or "—"
            text[i, j] = (f"<b>{an}</b><br>Well: {w}<br>Sample: {sid}<br>"
                          f"Status: {status_disp.get(status, status)}<br>"
                          f"Calibrated vs: {an_std.get(an, '—')}")

    colorscale = [
        [0.00, "#4477AA"], [0.25, "#4477AA"],   # BELOW_RANGE — blue
        [0.25, "#44AA99"], [0.50, "#44AA99"],   # IN_RANGE — teal
        [0.50, "#EE7733"], [0.75, "#EE7733"],   # ABOVE_RANGE — orange
        [0.75, "#CCBB44"], [1.00, "#CCBB44"],   # NO_FIT — yellow
    ]
    heatmap_html = _freeze_pane_heatmap(
        analyte_order, well_order, z, text, colorscale, 0, 3, excluded, "fig-range",
        row_label_colors=row_label_colors, row_group_lines=row_group_lines,
    )
    # Pathogen-group legend (antigen row labels are coloured to match).
    if present_cats:
        chips = " ".join(
            f'<span style="display:inline-block; margin-right:12px;">'
            f'<span style="color:{_PATHOGEN_COLORS.get(c, "#2c3e50")}; font-weight:700;">■</span> '
            f'{html.escape(PATHOGEN_LABELS.get(c, c))}</span>'
            for c in present_cats)
        if pool_mode == "per_pool":
            basis = ('against the single <b>scoring pool</b> — every antigen is '
                     'scored against one pool, so a cell for an antigen that pool '
                     'does not calibrate may read BELOW / ABOVE / NO_FIT for that '
                     'reason')
        else:
            basis = ('against <b>its antigen\'s matched standard</b> — this grid '
                     'mixes standards, one per antigen row: antigens with a '
                     'dedicated or reference standard use that standard, while '
                     '<b>antigens with no standard (e.g. influenza, malaria) are '
                     'scored against the best-fitting pool</b>, so read those calls '
                     'with care')
        legend = (
            '<p style="margin:0 0 6px; font-size:12px; color:#7f8c8d;">'
            'Cell colour = the specimen\'s range status ' + basis +
            ' (BELOW / IN / ABOVE / NO_FIT). Hover a cell to see the exact standard '
            'it was scored against (see "How to read this matrix" above). Antigen '
            '<b>labels</b> are coloured by pathogen group (dotted lines separate '
            'groups): ' + chips + '.</p>')
        return legend + heatmap_html
    return heatmap_html


_SERUM_DBS_RE = re.compile(r"^(?P<pid>.+)_r\d+_(?P<matrix>serum|dbs)$", re.IGNORECASE)


def _make_serum_dbs_comparison(in_range: pd.DataFrame) -> str:
    """Paired Serum-vs-DBS MFI scatter.

    Each specimen is run as both a Serum and a DBS sample
    (``{id}_r3_{Serum|DBS}``). For every person × antigen that has both, plot
    (serum MFI, DBS MFI). Points on the dashed y=x line agree; points off it
    read higher in one matrix than the other. Returns "" when the plate has no
    matched Serum/DBS pairs.
    """
    if in_range is None or in_range.empty or "sample_name" not in in_range.columns:
        return ""
    df = in_range[["sample_name", "analyte", "mfi"]].copy()
    parsed = df["sample_name"].astype(str).str.extract(_SERUM_DBS_RE)
    df["pid"] = parsed["pid"]
    df["matrix"] = parsed["matrix"].str.lower()
    df = df.dropna(subset=["pid", "matrix", "mfi"])
    if df.empty:
        return ""
    piv = df.pivot_table(index=["pid", "analyte"], columns="matrix",
                         values="mfi", aggfunc="mean")
    if "serum" not in piv.columns or "dbs" not in piv.columns:
        return ""
    paired = piv.dropna(subset=["serum", "dbs"]).reset_index()
    if paired.empty:
        return ""

    n_persons = paired["pid"].nunique()
    n_pairs = len(paired)
    s = paired["serum"].astype(float).clip(lower=0.1)
    b = paired["dbs"].astype(float).clip(lower=0.1)
    lo = float(min(s.min(), b.min()))
    hi = float(max(s.max(), b.max()))

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[lo, hi], y=[lo, hi], mode="lines",
        line=dict(color="#bdc3c7", width=1, dash="dot"),
        name="y = x", hoverinfo="skip",
    ))
    fig.add_trace(go.Scattergl(
        x=s, y=b, mode="markers",
        marker=dict(size=4, color="#4477AA", opacity=0.5),
        name="Serum vs DBS",
        customdata=np.stack([paired["pid"].astype(str), paired["analyte"].astype(str)], axis=-1),
        hovertemplate=("Person %{customdata[0]} · %{customdata[1]}<br>"
                       "Serum MFI %{x:.0f} · DBS MFI %{y:.0f}<extra></extra>"),
    ))
    fig.update_layout(
        margin=dict(l=60, r=20, t=46, b=50), height=460,
        title=dict(text=f"<b>Serum vs DBS</b> — {n_pairs:,} paired "
                        f"(person × antigen) points across {n_persons} people"),
        xaxis=dict(type="log", title="Serum MFI", gridcolor="#eef1f4"),
        yaxis=dict(type="log", title="DBS MFI", gridcolor="#eef1f4"),
        plot_bgcolor="white", showlegend=False,
    )
    return _plotly_html(fig, "fig-serum-dbs", height=480)


# ---------------------------------------------------------------------------
# Table builders
# ---------------------------------------------------------------------------


def _build_curve_summary(
    pool_fits: dict,
    pct_in_range: pd.DataFrame,
    excluded: set[str],
    recovery_tolerance: float,
) -> list[dict]:
    pct_lookup: dict = {}
    if pct_in_range is not None and not pct_in_range.empty:
        pct_lookup = pct_in_range.set_index("analyte")["pct_in_range"].to_dict()
    rows = []
    for an, fit in pool_fits.items():
        params = fit.get("params") or (None, None, None, None)
        a, b, c, d = params[0], params[1], params[2], params[3]
        g = params[4] if len(params) == 5 else None  # 5PL asymmetry (None for 4PL)
        rr = fit.get("reportable_range") or {}
        pct = pct_lookup.get(an)
        rows.append({
            "analyte": an,
            "pool": fit.get("pool", "—"),
            "excluded": an in excluded,
            "fit_ok": bool(fit.get("fit_ok")),
            # No curve at all (no signal / too few points / non-convergence),
            # distinct from a curve that fit but failed QC (fit_ok False).
            "no_fit": fit.get("params") is None,
            "n_points": len(fit.get("mean_data", [])) if fit.get("mean_data") is not None else 0,
            "a": _fmt(a, 1),
            "b": _fmt(b, 2),
            "c_ic50": _fmt(c, 1),
            "d": _fmt(d, 1),
            "g": _fmt(g, 2) if g is not None else "—",
            "model": fit.get("model", "4pl"),
            "lloq_dilution": _fmt(rr.get("lloq_dilution"), 1),
            "uloq_dilution": _fmt(rr.get("uloq_dilution"), 1),
            "pct_in_range": _fmt(pct, 1),
            "qc_warnings": "; ".join(fit.get("qc_warnings") or []) or "—",
            "dropped_point": fit.get("dropped_point"),
        })
    return rows


def _pool_target_label(pool_name: str) -> str:
    """Human label for the pathogen(s) a standard pool calibrates, e.g.
    'Dengue pool' → 'Dengue'; 'Orpal pool' → 'Dengue & other arboviruses
    (pan-arbovirus reference)'; 'NIBSC pool' → 'Measles / Diphtheria / Rubella /
    Tetanus'."""
    groups = _pool_groups(pool_name)
    if not groups:
        return "—"
    parts = []
    if "cholera" in groups:
        parts.append("Cholera")
    if "typhoid" in groups:
        parts.append("Typhoid")
    if "arbovirus" in groups:
        # Pan-arbovirus reference pool (also carries dengue). The whole pool is a
        # semi-quantitative reference; dengue's dedicated standard is elsewhere.
        parts.append("Dengue & other arboviruses (pan-arbovirus reference)")
    elif "dengue" in groups:
        parts.append("Dengue")
    if "vpd_nibsc" in groups:
        parts.append("Measles / Diphtheria / Rubella / Tetanus")
    return " · ".join(parts) if parts else "—"


def _group_summary_by_pool(curve_summary: list[dict]) -> list[dict]:
    """Group curve-summary rows into one block per standard pool, each tagged
    with the pathogen target(s) it calibrates. Preserves first-seen pool order.
    """
    order: list[str] = []
    buckets: dict[str, list[dict]] = {}
    for r in curve_summary or []:
        pool = r.get("pool") or "—"
        if pool not in buckets:
            buckets[pool] = []
            order.append(pool)
        buckets[pool].append(r)
    return [{"pool": p, "targets": _pool_target_label(p),
             "n": len(buckets[p]), "rows": buckets[p]} for p in order]


def _build_summary_by_pool_all(fits: dict, pools: list[str], panel_order: list[str],
                               excluded: set[str], rec_tol: float) -> list[dict]:
    """One summary block per standard pool over **every** antigen fit against
    that pool. Each row carries ``relevant`` = whether that pool is the antigen's
    designated calibrator/reference (its pathogen's effective scoring group,
    resolved against the pools present) — independent of best-fit. Relevant rows
    are listed first. %-in-range is omitted (a single-pool scoring metric).
    """
    if not pools:
        return []
    pool_grp = {p: _pool_groups(p) for p in pools}
    groups_present = set().union(*pool_grp.values()) if pool_grp else set()

    def _eff(a):
        for g in _antigen_scoring_groups(a):
            if g in groups_present:
                return g
        return None
    eff_map = {a: _eff(a) for a in panel_order if antigen_group(a)}
    order_index = {a: i for i, a in enumerate(panel_order)}

    out = []
    for pool in sorted(pools, key=_pool_sort_rank):
        pf = {a: {**fits[pool][a], "pool": pool}
              for a in panel_order if a in fits.get(pool, {})}
        if not pf:
            continue
        rows = _build_curve_summary(pf, pd.DataFrame(), excluded, rec_tol)
        for r in rows:
            a = r["analyte"]
            r["relevant"] = bool(a in eff_map and eff_map[a] in pool_grp[pool])
        rows.sort(key=lambda r: (not r["relevant"], order_index.get(r["analyte"], 1_000_000)))
        out.append({"pool": pool, "targets": _pool_target_label(pool),
                    "n": len(rows), "n_relevant": sum(1 for r in rows if r["relevant"]),
                    "rows": rows})
    return out


_DEDICATED_GROUPS = ("cholera", "typhoid", "dengue")


def _build_range_problem_by_pool(fits: dict, data: pd.DataFrame, pools: list[str],
                                 threshold: float, excluded: set[str]) -> list[dict]:
    """Range-problem specimens computed **within each standard pool** (not pooled).

    Each standard pool is assessed independently and the flag is clearly attributed
    to a specific standard:

    * The **flag** fires for a (specimen, pool) pair when ≥ ``threshold`` of that
      pool's *dedicated* antigens (cholera / typhoid / dengue whose group the pool
      targets) read outside **that pool's** reportable range. This keeps the flag
      on trustworthy curves. A dengue antigen is assessed separately against Dengue
      and against Orpal, so a specimen can be flagged for one and not the other.
    * **Non-dedicated antigens** (reference arbo/VPD + no-match antigens such as
      influenza / malaria) are *not dropped*: for the reference pools (Dengue /
      Orpal) they are read against that reference curve and reported per flagged
      specimen as **informational context** only — they never drive the flag,
      keeping seronegative noise out of the trigger.

    Informational only.
    """
    if data is None or data.empty or "well_type" not in data.columns:
        return []
    spec = data[data["well_type"] == "specimen"]
    if spec.empty:
        return []
    id_col = "sample_id" if "sample_id" in spec.columns else "sample_name"
    out = []
    for pool in sorted(pools, key=_pool_sort_rank):
        pf = fits.get(pool, {})
        pg = _pool_groups(pool)
        is_ref_pool = "dengue" in pg  # Dengue / Orpal double as the reference pools
        ded_bounds, ref_bounds = {}, {}
        for a in pf:
            if a in excluded:
                continue
            g = antigen_group(a)
            lo, hi = _mfi_bounds_for_fit(pf[a])
            if lo is None or hi is None:
                continue
            if g in _DEDICATED_GROUPS and g in pg:
                ded_bounds[a] = (lo, hi)
            elif is_ref_pool and g not in _DEDICATED_GROUPS:
                ref_bounds[a] = (lo, hi)
        n_ded = len(ded_bounds)
        if n_ded == 0:
            continue
        n_ref = len(ref_bounds)
        all_bounds = {**ded_bounds, **ref_bounds}
        sub = spec[spec["analyte"].isin(all_bounds.keys())]
        rows = []
        for well, g in sub.groupby("well", sort=False):
            d_below, d_above, r_out = [], [], 0
            sid = ""
            for r in g.itertuples(index=False):
                a = r.analyte
                m = getattr(r, "mfi", None)
                if not sid:
                    _s = getattr(r, id_col, "")
                    sid = str(_s) if _s is not None and str(_s).strip() and str(_s).lower() != "nan" else str(well)
                if m is None or pd.isna(m):
                    continue
                if a in ded_bounds:
                    lo, hi = ded_bounds[a]
                    if m < lo:
                        d_below.append(a)
                    elif m > hi:
                        d_above.append(a)
                elif a in ref_bounds:
                    lo, hi = ref_bounds[a]
                    if m < lo or m > hi:
                        r_out += 1
            n_out = len(d_below) + len(d_above)
            if n_ded and (n_out / n_ded) >= threshold:
                rows.append({
                    "well": str(well), "sample_id": sid, "n_dedicated": n_ded,
                    "n_below": len(d_below), "n_above": len(d_above),
                    "frac": round(n_out / n_ded, 4),
                    "below": ", ".join(d_below), "above": ", ".join(d_above),
                    "n_reference": n_ref, "n_reference_out": r_out,
                    "frac_reference": round(r_out / n_ref, 4) if n_ref else 0.0,
                })
        if rows:
            rows.sort(key=lambda d: d["frac"], reverse=True)
            out.append({"pool": pool, "targets": _pool_target_label(pool),
                        "n_dedicated": n_ded, "n_reference": n_ref,
                        "n_flagged": len(rows), "rows": rows})
    return out


def _format_problem_list(problems: pd.DataFrame) -> list[dict]:
    if problems is None or problems.empty:
        return []
    return [
        {
            "well": r.well,
            "sample_name": r.sample_name,
            "analyte": r.analyte,
            "count": "—" if pd.isna(r.count) else int(r.count),
            "tier": r.tier,
        }
        for r in problems.itertuples(index=False)
    ]


def _tier_counts(problems: pd.DataFrame) -> dict:
    if problems is None or problems.empty:
        return {"red": 0, "yellow": 0, "red_wells": 0}
    counts = problems["tier"].value_counts().to_dict()
    red = problems[problems["tier"] == "red"]
    # Distinct wells with ≥ 1 antigen at critically-low (red) bead count.
    red_wells = int(red["well"].nunique()) if not red.empty else 0
    return {"red": int(counts.get("red", 0)), "yellow": int(counts.get("yellow", 0)),
            "red_wells": red_wells}


def _format_range_problems(in_range: pd.DataFrame, excluded: set[str],
                           antigen_pool: dict | None = None,
                           pool_mode: str = "auto_select") -> list[dict]:
    if in_range is None or in_range.empty:
        return []
    antigen_pool = antigen_pool or {}
    out = in_range[in_range["status"].isin(["BELOW_RANGE", "ABOVE_RANGE"])]
    rows = []
    for r in out.itertuples(index=False):
        pool = antigen_pool.get(r.analyte, "—")
        # The per-antigen calibration tier only means something when each antigen
        # is matched to its own pool (auto-select). In per_pool mode every antigen
        # is scored against the one scoring pool, so the tier would be misleading.
        if pool_mode == "per_pool":
            cal_label = "scoring pool (not pathogen-matched)"
        else:
            cal_label = CALIBRATION_LABELS[antigen_calibration(r.analyte, None if pool == "—" else pool)]
        rows.append({
            "well": r.well,
            "sample_name": r.sample_name,
            "analyte": r.analyte,
            "mfi": _fmt(r.mfi, 1),
            "mfi_lloq": _fmt(r.mfi_lloq, 1),
            "mfi_uloq": _fmt(r.mfi_uloq, 1),
            "status": r.status,
            "standard": pool,
            "calibration": cal_label,
            "excluded": r.analyte in excluded,
        })
    return rows


def _format_bead_summary(bead_summary: dict) -> dict:
    """Trim a bead_problem_summary dict to the bits the template needs."""
    ant = bead_summary.get("antigen_summary", pd.DataFrame())
    smp = bead_summary.get("sample_summary", pd.DataFrame())
    return {
        "n_problem_antigens": bead_summary.get("n_problem_antigens", 0),
        "n_problem_samples": bead_summary.get("n_problem_samples", 0),
        "threshold": bead_summary.get("threshold", 0.20),
        "antigen_rows": _problem_rows(ant, "analyte", "problem_well_labels"),
        "sample_rows": _problem_rows(smp, "well", "problem_analytes",
                                     extra=("sample_name", "well_type")),
    }


def _format_range_summary(range_summary: dict, antigen_pool: dict | None = None) -> dict:
    ant = range_summary.get("antigen_summary", pd.DataFrame())
    smp = range_summary.get("sample_summary", pd.DataFrame())
    antigen_pool = antigen_pool or {}

    def _rows(df: pd.DataFrame, key: str, kind: str) -> list[dict]:
        if df is None or df.empty:
            return []
        flag_col = f"{kind}_flag"
        list_col = f"problem_samples_{kind}" if key == "analyte" else f"problem_analytes_{kind}"
        n_col = f"n_{kind}"
        frac_col = f"frac_{kind}"
        out = []
        sub = df[df[flag_col]]
        for r in sub.itertuples(index=False):
            row = {
                "key": getattr(r, key),
                "n_problem": getattr(r, n_col),
                "frac_problem": getattr(r, frac_col),
                "detail": getattr(r, list_col, ""),
            }
            if key == "well":
                row["sample_name"] = getattr(r, "sample_name", "")
                # Split the specimen's out-of-range antigens by the SAME three
                # calibration tiers used across the report: dedicated standard
                # (the trustworthy signal), reference pool, and best-fit (no
                # standard). Inline only the dedicated ones (usually few); the
                # reference and best-fit lists are collapsed so the cell stays
                # readable.
                ants = [x for x in (row["detail"] or "").split(";") if x]
                ded, ref, bestfit = [], [], []
                for a in ants:
                    t = antigen_calibration(a, antigen_pool.get(a))
                    if t == "standard":
                        ded.append(f"{a} ({antigen_pool.get(a, '—')})")
                    elif t == "reference":
                        ref.append(a)
                    else:
                        bestfit.append(a)
                row["n_dedicated"] = len(ded)
                row["n_reference"] = len(ref)
                row["n_bestfit"] = len(bestfit)
                row["detail_dedicated"] = "; ".join(ded)
                row["detail_reference"] = ", ".join(ref)
                row["detail_bestfit"] = ", ".join(bestfit)
            else:
                # Which standard the antigen was scored against + its tier.
                an = getattr(r, key)
                row["excluded"] = bool(getattr(r, "excluded", False))
                row["pool"] = antigen_pool.get(an, "—")
                row["calibration"] = antigen_calibration(an, row["pool"])
                row["calibration_label"] = CALIBRATION_LABELS[row["calibration"]]
            out.append(row)
        return out

    return {
        "n_below_antigens": range_summary.get("n_below_antigens", 0),
        "n_above_antigens": range_summary.get("n_above_antigens", 0),
        "n_below_samples": range_summary.get("n_below_samples", 0),
        "n_above_samples": range_summary.get("n_above_samples", 0),
        "threshold": range_summary.get("threshold", 0.20),
        "antigen_below": _rows(ant, "analyte", "below"),
        "antigen_above": _rows(ant, "analyte", "above"),
        "sample_below": _rows(smp, "well", "below"),
        "sample_above": _rows(smp, "well", "above"),
    }


def _problem_rows(df: pd.DataFrame, key: str, list_col: str,
                  extra: tuple[str, ...] = ()) -> list[dict]:
    if df is None or df.empty:
        return []
    sub = df[df["is_problem"]] if "is_problem" in df.columns else df
    out = []
    for r in sub.itertuples(index=False):
        row = {
            "key": getattr(r, key),
            "n_problem": int(getattr(r, "n_problem", 0)),
            "frac_problem": float(getattr(r, "frac_problem", 0.0)),
            "detail": getattr(r, list_col, ""),
        }
        for col in extra:
            row[col] = getattr(r, col, "")
        out.append(row)
    return out


def _past_plate_ids(hist: pd.DataFrame, current_plate_id, current_run_date) -> list:
    """Plate IDs that were run *before* the current plate (chronological).

    Uses ``run_date`` to order plates so a report never treats a later-run plate
    as 'historical'. Falls back to 'all other plates' only when the current
    plate's run date is unknown. Returned in chronological order.
    """
    if hist is None or hist.empty or "plate_id" not in hist.columns:
        return []
    rd = {}
    if "run_date" in hist.columns:
        for p, g in hist.groupby("plate_id"):
            s = g["run_date"].dropna()
            rd[p] = pd.to_datetime(s.iloc[0], errors="coerce") if len(s) else pd.NaT
    cur_ts = pd.to_datetime(current_run_date, errors="coerce") if current_run_date else pd.NaT
    others = [p for p in hist["plate_id"].dropna().unique() if p != current_plate_id]
    if pd.notna(cur_ts):
        past = [p for p in others if pd.notna(rd.get(p, pd.NaT)) and rd[p] < cur_ts]
    else:
        past = others
    past.sort(key=lambda p: (rd.get(p) if pd.notna(rd.get(p, pd.NaT)) else pd.Timestamp.min, str(p)))
    return past


def _cross_plate_mfi_overview(
    hist: pd.DataFrame,
    antigens: list[str] | None,
    current_plate_id: str | None,
    current_run_date,
    value_label: str,
    div_id: str,
    excluded: set[str] | None = None,
    hline: tuple[float, str] | None = None,
) -> str:
    """Cross-plate MFI overview for one control (Background, PC, or NC).

    The plot is drawn at a fixed width (~12 px/antigen) inside a horizontally
    scrolling container so all ~200 antigens stay legible. ``hline=(value,
    label)`` draws a dashed reference line (used for the Background max-MFI
    threshold).

    x = antigen (panel order), y = MFI (log scale). "Past" plates are those run
    *before* the current plate (by ``run_date``). The historical reference is
    each past plate's mean for the control:

    - **≥ 3 past plates** — a grey bar spans the historical Q1–Q3 (IQR);
      this plate's mean is a dot, **blue within the IQR** and **orange ♦
      above/below it** (provisional flag). Individual past plates are available
      as legend-toggleable grey traces (off by default).
    - **< 3 past plates** — each past plate's mean is a grey dot (its own legend
      entry); this plate's mean is a blue dot.

    A "Show all / hide past plates" button toggles every historical trace at
    once; individual plates can also be toggled via their legend entries.
    """
    excluded = set(excluded or [])
    if (hist is None or not isinstance(hist, pd.DataFrame) or hist.empty
            or "mfi" not in hist.columns):
        return ""
    df = hist.dropna(subset=["mfi"]).copy()
    if df.empty:
        return ""
    df["mfi"] = df["mfi"].astype(float)

    present = set(df["analyte"])
    order_keys = [a for a in (antigens or []) if a in present]
    for a in df["analyte"].drop_duplicates().tolist():
        if a not in order_keys:
            order_keys.append(a)
    an_index = {a: i for i, a in enumerate(order_keys)}

    past_plate_ids = _past_plate_ids(df, current_plate_id, current_run_date)
    cur = df[df["plate_id"] == current_plate_id]
    past = df[df["plate_id"].isin(past_plate_ids)]
    past_means = (past.groupby(["plate_id", "analyte"])["mfi"].mean().reset_index()
                  if not past.empty else pd.DataFrame(columns=["plate_id", "analyte", "mfi"]))
    n_past_plates = len(past_plate_ids)
    iqr_mode = n_past_plates >= 3

    # Small per-plate horizontal offset so overlapping past-plate means separate.
    _npp = len(past_plate_ids)
    _xoff = ({p: (k - (_npp - 1) / 2) * 0.16 for k, p in enumerate(past_plate_ids)}
             if _npp > 1 else {p: 0.0 for p in past_plate_ids})

    def _floor(v):
        return max(float(v), 0.1)

    iqr_x, iqr_y = [], []
    med_x, med_y, med_t = [], [], []
    plate_pts = {p: {"x": [], "y": [], "t": []} for p in past_plate_ids}
    in_x, in_y, in_t = [], [], []     # current mean within IQR
    out_x, out_y, out_t = [], [], []  # current mean outside IQR (flag)
    neu_x, neu_y, neu_t = [], [], []  # current mean, no IQR yet (neutral)
    curB_x, curB_y, curB_t = [], [], []  # current mean for the per-plate view (red)

    pm_by_an = {a: g for a, g in past_means.groupby("analyte")} if not past_means.empty else {}
    cur_groups = cur.groupby("analyte") if not cur.empty else None
    for a in order_keys:
        i = an_index[a]
        sub = pm_by_an.get(a)
        pmv = sub["mfi"].dropna().astype(float).values if sub is not None else np.array([])
        q1r = q3r = None
        if iqr_mode and pmv.size >= 1:
            q1r = float(np.percentile(pmv, 25))
            q3r = float(np.percentile(pmv, 75))
            medr = float(np.percentile(pmv, 50))
            iqr_x += [i, i, None]
            iqr_y += [_floor(q1r), _floor(q3r), None]
            med_x.append(i); med_y.append(_floor(medr))
            med_t.append(f"<b>{a}</b><br>Historical IQR ({pmv.size} plates):<br>"
                         f"Q1: {q1r:.1f}; Median: {medr:.1f}; Q3: {q3r:.1f}")
        # Per-plate past dots (always collected; visibility set per mode below).
        if sub is not None:
            for _, rr in sub.iterrows():
                pid_ = rr["plate_id"]; vv = float(rr["mfi"])
                if pid_ not in plate_pts:
                    continue
                plate_pts[pid_]["x"].append(i + _xoff.get(pid_, 0.0))
                plate_pts[pid_]["y"].append(_floor(vv))
                plate_pts[pid_]["t"].append(f"<b>{a}</b><br>{pid_}<br>Plate mean MFI: {vv:.1f}")
        if cur_groups is not None and a in cur_groups.groups:
            wells = cur_groups.get_group(a)["mfi"].dropna().astype(float).values
            if len(wells) == 0:
                continue
            m = float(np.mean(wells))
            reps = ", ".join(f"{v:.1f}" for v in wells)
            head = f"<b>{a}</b><br>This plate — mean MFI: {m:.1f} (wells: {reps})"
            curB_x.append(i); curB_y.append(_floor(m)); curB_t.append(head)
            if q1r is not None and q3r is not None:
                pos = ("above historical Q3" if m > q3r else
                       "below historical Q1" if m < q1r else "within historical IQR")
                lbl = (f"{head}<br>Historical IQR: {q1r:.1f}–{q3r:.1f}<br>Position: {pos}")
                if q1r <= m <= q3r:
                    in_x.append(i); in_y.append(_floor(m)); in_t.append(lbl)
                else:
                    out_x.append(i); out_y.append(_floor(m)); out_t.append(lbl)
            else:
                neu_x.append(i); neu_y.append(_floor(m))
                neu_t.append(f"{head}<br>Historical IQR: not established (requires ≥ 3 prior plates)")

    # Two switchable views (Plotly buttons toggle their visibility):
    #   A "Median ± IQR"        — grey IQR band + current-plate dots coloured by
    #                             IQR position (blue in / orange ♦ out).
    #   B "Per-plate data points" — each past plate its own dot on a chronological
    #                             blue→green gradient (oldest faded, newest bold);
    #                             current plate in bold red.
    # Default = A when an IQR exists (≥ 3 past plates), else B.
    fig = go.Figure()
    default_A = iqr_mode
    visA = True if default_A else False
    visB = True if not default_A else False
    iqrA_idx, curA_idx, past_idx, curB_idx = [], [], [], []

    # --- View A traces ---
    if iqr_x:
        iqrA_idx.append(len(fig.data))
        fig.add_trace(go.Scatter(
            x=iqr_x, y=iqr_y, mode="lines", line=dict(color=_CB_GREY, width=4),
            opacity=0.7, name="Previous plates IQR (Q1–Q3)", hoverinfo="skip",
            visible=visA))
        iqrA_idx.append(len(fig.data))
        fig.add_trace(go.Scatter(
            x=med_x, y=med_y, mode="markers",
            marker=dict(size=14, color="rgba(0,0,0,0)"),
            name="Historical IQR", hovertext=med_t, hoverinfo="text",
            showlegend=False, visible=visA))
    if in_x:
        curA_idx.append(len(fig.data))
        fig.add_trace(go.Scatter(
            x=in_x, y=in_y, mode="markers", name="This plate (within IQR)",
            marker=dict(size=6, color=_CB_BLUE, line=dict(width=0.5, color="#04395e")),
            hovertext=in_t, hoverinfo="text", visible=visA))
    if out_x:
        curA_idx.append(len(fig.data))
        fig.add_trace(go.Scatter(
            x=out_x, y=out_y, mode="markers", name="This plate (outside IQR — review)",
            marker=dict(size=7, color=_CB_VERMILLION, symbol="diamond",
                        line=dict(width=0.5, color="#7a3500")),
            hovertext=out_t, hoverinfo="text", visible=visA))
    if neu_x:
        curA_idx.append(len(fig.data))
        fig.add_trace(go.Scatter(
            x=neu_x, y=neu_y, mode="markers", name="This plate (mean of wells)",
            marker=dict(size=6, color=_CB_BLUE, line=dict(width=0.5, color="#04395e")),
            hovertext=neu_t, hoverinfo="text", visible=visA))

    # --- View B traces: one per past plate (chronological gradient) + red current ---
    _npast = len(past_plate_ids)
    for k, p in enumerate(past_plate_ids):
        pts = plate_pts[p]
        if not pts["x"]:
            continue
        t = (k / (_npast - 1)) if _npast > 1 else 1.0
        col = _blue_green_gradient(t)
        past_idx.append(len(fig.data))
        fig.add_trace(go.Scatter(
            x=pts["x"], y=pts["y"], mode="markers",
            marker=dict(size=5, color=col, line=dict(width=0.4, color=col)),
            name=str(p), legendgroup=f"past:{p}",
            hovertext=pts["t"], hoverinfo="text", visible=visB))
    if curB_x:
        curB_idx.append(len(fig.data))
        fig.add_trace(go.Scatter(
            x=curB_x, y=curB_y, mode="markers", name="This plate",
            marker=dict(size=9, color=_CUR_RED, symbol="circle",
                        line=dict(width=0.8, color="#7a1012")),
            hovertext=curB_t, hoverinfo="text", visible=visB))

    n_an = len(order_keys)
    plot_w = max(1100, 70 + n_an * 12)
    # Explicit log y-range from the plotted values (+ the hline) so the axis is
    # bounded — add_hline on a log axis otherwise blows autorange up to ~1e304.
    import math
    yv = df["mfi"].astype(float).values
    yv = yv[yv > 0]
    ylo = float(yv.min()) if yv.size else 1.0
    yhi = float(yv.max()) if yv.size else 10.0
    if hline is not None:
        ylo = min(ylo, float(hline[0]))
        yhi = max(yhi, float(hline[0]))
    yrange = [math.log10(max(ylo * 0.6, 0.05)), math.log10(yhi * 1.6)]
    layout = dict(
        # autoexpand=False keeps the top margin fixed so toggling views/legend
        # entries can't resize the plot area and shift the paper-anchored buttons.
        margin=dict(l=60, r=30, t=118, b=200, autoexpand=False), height=620, width=plot_w,
        xaxis=dict(
            title="Antigen (panel order from xPONENT CSV header)",
            tickmode="array", tickvals=list(range(n_an)),
            ticktext=[(f"<i>{a}</i>" if a in excluded else a) for a in order_keys],
            tickangle=-90, tickfont=dict(size=9), showgrid=False, automargin=False),
        yaxis=dict(title=value_label, type="log", gridcolor="#eef1f4",
                   range=yrange, autorange=False),
        # Legend row at the top-left; the view toggle + past-plate buttons stack
        # beneath it.
        legend=dict(orientation="h", x=0, xanchor="left", y=1.24, yanchor="bottom",
                    bgcolor="rgba(255,255,255,0.85)", bordercolor="#d0d7de",
                    borderwidth=1, font=dict(size=10)),
    )
    # Offline-safe Plotly buttons, stacked on the LEFT under the legend:
    #   (1) view toggle: Median ± IQR  vs  Per-plate data points
    #   (2) bulk show/hide of the past-plate traces (per-plate view)
    n_traces = len(fig.data)
    viewA = iqrA_idx + curA_idx
    viewB = past_idx + curB_idx
    visA_list = [i in viewA for i in range(n_traces)]
    visB_list = [i in viewB for i in range(n_traces)]
    menus = []
    if viewA and viewB:
        menus.append(dict(
            type="buttons", direction="right", showactive=True,
            active=(0 if default_A else 1),
            x=0, xanchor="left", y=1.12, yanchor="bottom", pad=dict(t=2, r=2),
            font=dict(size=10),
            buttons=[
                dict(label="Median ± IQR", method="update",
                     args=[{"visible": visA_list}]),
                dict(label="Per-plate data points", method="update",
                     args=[{"visible": visB_list}]),
            ],
        ))
    if past_idx:
        menus.append(dict(
            type="buttons", direction="right", showactive=False,
            x=0, xanchor="left", y=1.015, yanchor="bottom", pad=dict(t=2, r=2),
            font=dict(size=10),
            buttons=[
                dict(label="Show all past plates", method="restyle",
                     args=[{"visible": True}, past_idx]),
                dict(label="Hide past plates", method="restyle",
                     args=[{"visible": "legendonly"}, past_idx]),
            ],
        ))
    if menus:
        layout["updatemenus"] = menus
    fig.update_layout(**layout)
    if hline is not None:
        hval, hlabel = hline
        fig.add_hline(
            y=hval, line=dict(color=_CB_AMBER, width=1.6, dash="dash"),
            annotation_text=hlabel, annotation_position="top left",
            annotation_font=dict(size=10, color="#a06a00"))
    inner = _plotly_html(fig, div_id, height=620, responsive=False)
    # Fixed-width plot inside a horizontally scrolling container.
    return (
        '<div style="max-width:100%; overflow-x:auto; border:1px solid #e1e4e8; '
        'border-radius:4px; padding:4px;">'
        f'<div style="display:inline-block;">{inner}</div></div>'
    )


def _well_sort_key(w):
    """Sort well IDs by row letter then column number (A1, A2, …, B1, …)."""
    m = re.match(r"\s*([A-Za-z]+)\s*0*(\d+)", str(w))
    if m:
        return (m.group(1).upper(), int(m.group(2)))
    return (str(w), 0)


def _format_control_stats(
    hist: pd.DataFrame,
    antigens: list[str] | None,
    current_plate_id: str | None,
    current_run_date=None,
    excluded: set[str] | None = None,
    cv_flag_threshold: float | None = None,
    hist_cv_flag_threshold: float | None = None,
) -> tuple[list[dict], list[str]]:
    """Per-antigen cross-plate stats rows + the current-plate well columns.

    ``cv_flag_threshold`` (a fraction, e.g. 0.25) sets ``row['high_cv']`` when
    this plate's %CV across the control's wells exceeds it (intra-assay).
    ``hist_cv_flag_threshold`` sets ``row['high_hist_cv']`` when the *historical*
    (between-plate, inter-assay) %CV exceeds it.

    Shared by Background, Positive, and Negative Control QC so all three tables
    carry identical columns. Each row has a ``wells`` dict (well → this-plate
    MFI) plus:

    - **current** (across this plate's wells): n_wells, mean, SD (ddof=1), %CV
      (SD/mean×100), IQR (Q1–Q3).
    - **historical** (across each *past* plate's mean for this control): mean,
      SD, %CV, IQR, and ``n_past`` = the number of past plates.

    ``well_cols`` is the sorted list of this plate's well IDs (one column each).
    """
    excluded = set(excluded or [])
    if (hist is None or not isinstance(hist, pd.DataFrame) or hist.empty
            or "mfi" not in hist.columns):
        return [], []
    df = hist.dropna(subset=["mfi"]).copy()
    df["mfi"] = df["mfi"].astype(float)
    present = set(df["analyte"])
    order_keys = [a for a in (antigens or []) if a in present]
    for a in df["analyte"].drop_duplicates().tolist():
        if a not in order_keys:
            order_keys.append(a)

    cur = df[df["plate_id"] == current_plate_id]
    past = df[df["plate_id"].isin(_past_plate_ids(df, current_plate_id, current_run_date))]
    past_means = (past.groupby(["plate_id", "analyte"])["mfi"].mean().reset_index()
                  if not past.empty else pd.DataFrame(columns=["plate_id", "analyte", "mfi"]))
    has_well = "well" in cur.columns
    well_cols = (sorted(cur["well"].dropna().astype(str).unique(), key=_well_sort_key)
                 if (not cur.empty and has_well) else [])
    cur_an = cur.groupby("analyte") if not cur.empty else None

    def _iqr(arr):
        if arr.size >= 1:
            return f"{float(np.percentile(arr, 25)):.1f}–{float(np.percentile(arr, 75)):.1f}"
        return "—"

    rows = []
    for a in order_keys:
        wells_map = {}
        cvals = pd.Series(dtype=float)
        if cur_an is not None and a in cur_an.groups:
            g = cur_an.get_group(a)
            cvals = g["mfi"].dropna().astype(float)
            if has_well:
                wells_map = {str(w): _fmt(float(m), 1)
                             for w, m in zip(g["well"], g["mfi"]) if pd.notna(m)}
        n_wells = int(cvals.size)
        cur_mean = float(cvals.mean()) if n_wells else float("nan")
        cur_sd = float(cvals.std(ddof=1)) if n_wells > 1 else float("nan")
        cur_cv = (cur_sd / cur_mean) if (n_wells > 1 and cur_mean > 0) else float("nan")
        cur_iqr = _iqr(cvals.values) if n_wells else "—"
        pm = (past_means.loc[past_means["analyte"] == a, "mfi"].dropna().astype(float)
              if not past_means.empty else pd.Series(dtype=float))
        n_past = int(pm.size)
        h_mean = float(pm.mean()) if n_past else float("nan")
        h_sd = float(pm.std(ddof=1)) if n_past > 1 else float("nan")
        h_cv = (h_sd / h_mean) if (n_past > 1 and h_mean > 0) else float("nan")
        h_iqr = _iqr(pm.values) if n_past else "—"
        # Provisional flag: this plate's mean above/below the historical IQR
        # (only once ≥ 3 past plates establish an IQR).
        flag = ""
        if n_past >= 3 and n_wells:
            q1v = float(np.percentile(pm.values, 25))
            q3v = float(np.percentile(pm.values, 75))
            if cur_mean > q3v:
                flag = "above"
            elif cur_mean < q1v:
                flag = "below"
        high_cv = bool(cv_flag_threshold is not None and cur_cv == cur_cv
                       and cur_cv > cv_flag_threshold)
        high_hist_cv = bool(hist_cv_flag_threshold is not None and h_cv == h_cv
                            and h_cv > hist_cv_flag_threshold)
        rows.append({
            "analyte": a,
            "excluded": a in excluded,
            "flag": flag,
            "high_cv": high_cv,
            "high_hist_cv": high_hist_cv,
            "n_wells": n_wells,
            "wells": wells_map,
            "current_mfi": _fmt(cur_mean, 1),
            "current_sd": _fmt(cur_sd, 1),
            "current_cv": _fmt(cur_cv * 100 if cur_cv == cur_cv else None, 1),
            "current_iqr": cur_iqr,
            "hist_mean": _fmt(h_mean, 1),
            "hist_sd": _fmt(h_sd, 1),
            "hist_cv": _fmt(h_cv * 100 if h_cv == h_cv else None, 1),
            "hist_iqr": h_iqr,
            "n_past": n_past,
        })
    return rows, well_cols


def _bg_well_outliers(
    bgw: pd.DataFrame,
    antigens: list[str] | None,
    current_plate_id,
    excluded: set[str] | None = None,
) -> list[dict]:
    """Flag any single Background well that sits > 2·SD above the mean of the
    *other* Background wells for that antigen (this plate only).

    A leave-one-out test: for each well the mean/SD are computed from the
    remaining wells, so a lone high well can't hide inside its own inflated
    SD (with only ~4 wells, an all-wells mean+2SD almost never triggers). The
    LOO Mean / SD / Threshold decide the flag; the literal *all-wells* mean / SD
    / threshold are also reported alongside (per the "show both" request) so the
    reviewer can compare. Needs ≥ 3 wells (so the remaining set has ≥ 2). One row
    per (antigen × outlier well).
    """
    excluded = set(excluded or [])
    if bgw is None or bgw.empty or "mfi" not in bgw.columns:
        return []
    cur = bgw[bgw["plate_id"] == current_plate_id] if "plate_id" in bgw.columns else bgw
    cur = cur.dropna(subset=["mfi"]).copy()
    if cur.empty:
        return []
    cur["mfi"] = cur["mfi"].astype(float)
    order = [a for a in (antigens or []) if a in set(cur["analyte"])]
    for a in cur["analyte"].drop_duplicates().tolist():
        if a not in order:
            order.append(a)
    rows = []
    for a in order:
        g = cur[cur["analyte"] == a]
        vals = g["mfi"].dropna().astype(float).values
        wells = g["well"].astype(str).values if "well" in g.columns else [""] * len(vals)
        if vals.size < 3:
            continue
        # Literal all-wells stats (same for every well of this antigen).
        all_mean = float(vals.mean())
        all_sd = float(vals.std(ddof=1))
        all_thr = all_mean + 2 * all_sd
        for k, v in enumerate(vals):
            rest = np.delete(vals, k)
            mean = float(rest.mean())
            sd = float(rest.std(ddof=1))
            if not (sd > 0):
                continue
            thr = mean + 2 * sd
            if v > thr:
                rows.append({
                    "analyte": a,
                    "excluded": a in excluded,
                    "well": str(wells[k]),
                    "well_mfi": _fmt(float(v), 1),
                    "mean": _fmt(mean, 1),
                    "sd": _fmt(sd, 1),
                    "threshold": _fmt(thr, 1),
                    "z": _fmt((float(v) - mean) / sd, 2),
                    "n_wells": int(vals.size),
                    # Literal all-wells comparison (shown alongside the LOO flag).
                    "all_mean": _fmt(all_mean, 1),
                    "all_sd": _fmt(all_sd, 1),
                    "all_threshold": _fmt(all_thr, 1),
                    "all_flag": bool(float(v) > all_thr),
                })
    rows.sort(key=lambda d: float(d["z"]), reverse=True)
    return rows


def _bg_negative_net(
    data: pd.DataFrame,
    bgw: pd.DataFrame,
    current_plate_id,
    excluded: set[str] | None = None,
) -> list[dict]:
    """Flag specimen (sample-ID × antigen) combos with a negative net MFI,
    where net = specimen MFI − mean of this plate's Background wells for that
    antigen. A negative value means the specimen signal fell below background.
    """
    excluded = set(excluded or [])
    if data is None or data.empty or "well_type" not in data.columns:
        return []
    cur = bgw[bgw["plate_id"] == current_plate_id] if "plate_id" in bgw.columns else bgw
    cur = cur.dropna(subset=["mfi"]) if cur is not None else None
    if cur is None or cur.empty:
        return []
    bg_mean = cur.groupby("analyte")["mfi"].mean()
    spec = data[data["well_type"] == "specimen"].copy()
    if spec.empty:
        return []
    id_col = "sample_id" if "sample_id" in spec.columns else "sample_name"
    rows = []
    for r in spec.itertuples(index=False):
        a = getattr(r, "analyte", None)
        mfi = getattr(r, "mfi", None)
        if a is None or a not in bg_mean.index or pd.isna(mfi):
            continue
        net = float(mfi) - float(bg_mean[a])
        if net < 0:
            sid = getattr(r, id_col, None)
            rows.append({
                "sample_id": (str(sid).strip() if sid is not None and str(sid).strip()
                              and str(sid).lower() != "nan" else str(getattr(r, "well", ""))),
                "well": str(getattr(r, "well", "")),
                "analyte": str(a),
                "excluded": a in excluded,
                "sample_mfi": _fmt(float(mfi), 1),
                "bg_mean": _fmt(float(bg_mean[a]), 1),
                "net": _fmt(net, 1),
            })
    rows.sort(key=lambda d: float(d["net"]))
    return rows


def _control_qc_sections(
    hist: pd.DataFrame,
    antigens: list[str] | None,
    current_plate_id: str | None,
    current_run_date,
    excluded: set[str] | None,
    value_label: str,
    id_prefix: str,
    cv_flag_threshold: float | None = None,
    hist_cv_flag_threshold: float | None = None,
) -> list[dict]:
    """Build one {control, plot_html, stats, well_cols, n_past_plates} block
    per control.

    ``hist`` must carry a ``control`` column (display label). Controls are
    rendered in sorted order; each gets a cross-plate overview + stats table.
    "Past" plates are those run before ``current_run_date``.

    ``cv_flag_threshold`` (fraction) flags a control × antigen whose duplicate
    wells disagree by more than that %CV (used for NC duplicate wells, where an
    n=2 mean+2SD outlier test is not meaningful). Each block also carries
    ``n_high_cv``.
    """
    if (hist is None or not isinstance(hist, pd.DataFrame) or hist.empty
            or "control" not in hist.columns):
        return []
    out = []
    controls = sorted(c for c in hist["control"].dropna().drop_duplicates())
    for idx, ctrl in enumerate(controls):
        sub = hist[hist["control"] == ctrl]
        plot = _cross_plate_mfi_overview(
            sub, antigens, current_plate_id, current_run_date,
            value_label, f"fig-{id_prefix}-{idx}", excluded)
        stats, well_cols = _format_control_stats(
            sub, antigens, current_plate_id, current_run_date, excluded,
            cv_flag_threshold=cv_flag_threshold,
            hist_cv_flag_threshold=hist_cv_flag_threshold)
        n_past = len(_past_plate_ids(sub, current_plate_id, current_run_date))
        on_plate = bool((sub["plate_id"] == current_plate_id).any())
        out.append({"control": ctrl, "plot_html": plot, "stats": stats,
                    "well_cols": well_cols, "n_past_plates": n_past,
                    "on_plate": on_plate,
                    "n_high_cv": sum(1 for r in stats if r.get("high_cv")),
                    "n_high_hist_cv": sum(1 for r in stats if r.get("high_hist_cv"))})
    return out


def _make_plate_layout_overview(data: pd.DataFrame) -> str:
    """Shape-coded plate map (96- or 384-well).

    Well types are distinguished by marker *shape* (not colour):
    circle = PC/standard, ✕ = NC (negative), square = specimen,
    open square = background. No sample labels are drawn — the well
    position, sample ID, and type are shown on hover. The figure is
    rendered inside a horizontally/vertically scrolling container so a
    full 384-well plate is legible.
    """
    if data is None or data.empty or "well" not in data.columns:
        return "<p style='color:#999;'>No plate layout to display.</p>"

    cols_keep = ["well", "sample_name", "well_type"]
    if "sample_id" in data.columns:
        cols_keep.append("sample_id")
    wells = data.drop_duplicates("well")[cols_keep].copy()
    wells["row"] = wells["well"].str[0]
    wells["coln"] = pd.to_numeric(wells["well"].str[1:], errors="coerce")
    wells = wells.dropna(subset=["coln"])
    wells["coln"] = wells["coln"].astype(int)

    # Infer geometry; snap to 96 or 384.
    max_row = max((ord(r) - ord("A") + 1) for r in wells["row"]) if not wells.empty else 8
    max_col = int(wells["coln"].max()) if not wells.empty else 12
    is_384 = max_row > 8 or max_col > 12
    n_rows = 16 if is_384 else 8
    n_cols = 24 if is_384 else 12
    rows = [chr(ord("A") + i) for i in range(n_rows)]

    # Per-type marker style. Shape carries the meaning; colour is a soft
    # secondary cue only.
    type_style = {
        "pc":         dict(symbol="circle",      color="#2c7fb8", size=13, name="PC / standard"),
        "nc":         dict(symbol="x",           color="#d95f02", size=13, name="NC (negative)"),
        "specimen":   dict(symbol="square",      color="#7fbf7b", size=12, name="Specimen"),
        "background": dict(symbol="square-open", color="#95a5a6", size=12, name="Background"),
    }

    def _label(r) -> str:
        sid = getattr(r, "sample_id", None)
        if sid is not None and str(sid).strip() and str(sid).lower() != "nan":
            return str(sid)
        return (r.sample_name or "").strip()

    type_disp = {"pc": "PC (standard)", "nc": "NC (negative)",
                 "specimen": "Specimen", "background": "Background"}

    fig = go.Figure()
    # One scatter trace per well_type (legend + distinct shape).
    for wtype, style in type_style.items():
        sub = wells[wells["well_type"] == wtype]
        if sub.empty:
            continue
        xs, ys, hov = [], [], []
        for r in sub.itertuples(index=False):
            if r.row not in rows or not (1 <= r.coln <= n_cols):
                continue
            xs.append(r.coln)
            ys.append(r.row)
            hov.append(
                f"<b>{r.well}</b><br>Sample: {html.escape(_label(r)) or '—'}"
                f"<br>Type: {type_disp.get(wtype, wtype)}"
            )
        if not xs:
            continue
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers", name=style["name"],
            marker=dict(symbol=style["symbol"], size=style["size"],
                        color=style["color"],
                        line=dict(width=1, color="#34495e") if style["symbol"] != "x" else dict(width=2, color=style["color"])),
            hovertext=hov, hoverinfo="text",
        ))

    # Pixel sizing: ~34px per column / ~30px per row so a 384 plate is
    # legible. The container scrolls if it exceeds the box.
    px_w = max(420, 70 + n_cols * 34)
    px_h = max(280, 96 + n_rows * 30)
    fig.update_layout(
        # Generous top margin hosts the centered legend *above* the column
        # numbers (which sit on the top axis) with a clear gap between them.
        margin=dict(l=40, r=20, t=64, b=16),
        width=px_w, height=px_h,
        plot_bgcolor="#fbfcfd",
        legend=dict(orientation="h", x=0.5, y=1.11, xanchor="center",
                    yanchor="bottom", font=dict(size=11)),
        xaxis=dict(
            side="top", title="", tickmode="array",
            tickvals=list(range(1, n_cols + 1)), tickfont=dict(size=10),
            range=[0.5, n_cols + 0.5], showgrid=True, gridcolor="#eef1f4",
            zeroline=False, constrain="domain",
        ),
        yaxis=dict(
            title="", categoryorder="array", categoryarray=rows[::-1],
            tickfont=dict(size=10), showgrid=True, gridcolor="#eef1f4",
            zeroline=False, scaleanchor="x", scaleratio=1,
        ),
    )
    inner = _plotly_html(fig, "fig-plate-layout", height=px_h, responsive=False)
    # Scrollable container (both axes); the inline-block inner is centered
    # horizontally so the map isn't stranded at the left edge.
    return (
        '<div style="max-width:100%; max-height:600px; overflow:auto; '
        'border:1px solid #e1e4e8; border-radius:4px; padding:4px; text-align:center;">'
        f'<div style="display:inline-block; text-align:left;">{inner}</div></div>'
    )


_NC_CTRL_RE = re.compile(r"(Negative\s*\d+)", re.IGNORECASE)


def _nc_control(sample_name: str) -> str:
    """Extract the NC control label (e.g. 'Negative 0', 'Negative 49')."""
    m = _NC_CTRL_RE.search(str(sample_name or ""))
    return m.group(1).replace("  ", " ").strip() if m else (str(sample_name or "NC").strip() or "NC")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_pool(fits: dict | None) -> dict:
    if not fits:
        return {}
    pools = list(fits.keys())
    return fits[pools[0]] if pools else {}


def _build_pool_selection_summary(fits: dict | None, config: dict | None) -> dict:
    """Summarize the automatic antigen → pool selection for the report banner.

    Returns dict:
        pools:    list of control pool names detected on the plate
        rows:     [{pool, n_antigens}] — how many antigens each pool was
                  chosen to calibrate (sorted by n_antigens desc)
        n_pools:  number of pools
        n_assigned: number of antigens routed to a pool
    """
    if not fits:
        return {"pools": [], "rows": [], "n_pools": 0, "n_assigned": 0}
    pools = list(fits.keys())
    selection = select_pool_per_antigen(fits, antigens=None, config=config)
    counts: dict[str, int] = {p: 0 for p in pools}
    for pool in selection.values():
        counts[pool] = counts.get(pool, 0) + 1
    rows = sorted(
        ({"pool": p, "n_antigens": counts.get(p, 0)} for p in pools),
        key=lambda r: r["n_antigens"], reverse=True,
    )
    return {
        "pools": pools,
        "rows": rows,
        "n_pools": len(pools),
        "n_assigned": len(selection),
    }


def _build_selected_fits(fits: dict | None, config: dict | None) -> dict:
    """Per-antigen fit from its auto-selected calibrating pool.

    Returns ``{analyte: fit}`` shaped like a single-pool dict, with the
    chosen pool name injected as ``fit['pool']``. Antigens with no usable
    fit in any pool fall back to their first-pool entry (so they still
    appear, as NO_FIT).
    """
    if not fits:
        return {}
    pools = list(fits.keys())
    all_antigens = sorted({a for pf in fits.values() for a in pf})
    selection = select_pool_per_antigen(fits, antigens=all_antigens, config=config)
    out: dict = {}
    for a in all_antigens:
        pool = selection.get(a)
        if pool is None:
            # No usable fit anywhere — surface the first pool's entry.
            pool = pools[0]
        fit = dict(fits.get(pool, {}).get(a, {}))
        fit["pool"] = pool
        out[a] = fit
    return out


def _fmt(v, decimals=2) -> str:
    if v is None:
        return "—"
    try:
        if pd.isna(v):
            return "—"
    except (TypeError, ValueError):
        pass
    try:
        return f"{float(v):,.{decimals}f}"
    except (TypeError, ValueError):
        return str(v)


def _fmt_params(params) -> str:
    if not params:
        return "—"
    a, b, c, d = params[0], params[1], params[2], params[3]
    s = f"a={_fmt(a, 1)}, b={_fmt(b, 2)}, c={_fmt(c, 1)}, d={_fmt(d, 1)}"
    if len(params) == 5:
        s += f", g={_fmt(params[4], 2)}"
    return s


def _derive_layout_info(data: pd.DataFrame) -> dict:
    info: dict = {}
    if "box_id" in data.columns:
        boxes = sorted(set(b for b in data["box_id"].dropna().unique() if b))
        if boxes:
            info["box_ids"] = boxes
    if "patient_id" in data.columns:
        spec = data[data["well_type"] == "specimen"]
        if not spec.empty:
            n_with_pid = spec.drop_duplicates("well")["patient_id"].astype(str).str.len().gt(0).sum()
            info["n_with_patient_id"] = int(n_with_pid)
            info["n_specimens"] = int(spec["well"].nunique())
    return info
