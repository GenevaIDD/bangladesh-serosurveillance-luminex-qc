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
    four_pl, range_problem_summary, select_pool_per_antigen, default_scoring_pool,
)
from .qc_beads import bead_problem_summary


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

    pool_fits = _first_pool(fits)
    plate_id = metadata.get("plate_id", "unknown")

    # Standard-curve presentation mode.
    pool_mode = config.get("panel", {}).get("pool_mode", "per_pool")
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

    # Priority antigens to *display* in the Summary / All-Curves Overview
    # (curves are still fit for every antigen). Empty setting = all antigens,
    # in panel order from the CSV header.
    panel_order = list(metadata.get("analytes") or list(selected_fits.keys()))
    priority_cfg = list(config.get("panel", {}).get("priority_antigens", []) or [])
    if priority_cfg:
        priority_set = set(priority_cfg)
        priority_antigens = [a for a in panel_order if a in priority_set]
    else:
        priority_antigens = list(panel_order)
    priority_is_all = not priority_cfg

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
    bgw = (data[data["well_type"] == "background"][["analyte", "well", "mfi"]].copy()
           if (not data.empty and "well_type" in data.columns)
           else pd.DataFrame(columns=["analyte", "well", "mfi"]))
    bgw["plate_id"] = cur_pid
    if (isinstance(history_background, pd.DataFrame) and not history_background.empty
            and "mean_mfi" in history_background.columns):
        _hb = history_background[history_background["plate_id"] != cur_pid][
            ["plate_id", "analyte", "mean_mfi"]].dropna(subset=["mean_mfi"]).copy()
        _hb = _hb.rename(columns={"mean_mfi": "mfi"})
        _hb["well"] = "(plate mean)"
        n_prev_bg = int(_hb["plate_id"].nunique())
    else:
        _hb = pd.DataFrame(columns=["plate_id", "analyte", "mfi", "well"])
        n_prev_bg = 0
    bg_hist = pd.concat([bgw, _hb], ignore_index=True)
    bg_overview_html = _cross_plate_mfi_overview(
        bg_hist, panel_order, cur_pid, "Mean Background MFI (log scale)",
        "fig-bg-overview", excluded)
    bg_stats, bg_well_cols = _format_control_stats(bg_hist, panel_order, cur_pid, excluded)
    bg_levels_ctx = {"present": bool(bg_stats), "n_antigens": len(bg_stats),
                     "n_prev_plates": n_prev_bg, "rows": bg_stats, "well_cols": bg_well_cols}

    # ----- Positive Control QC (single-point Cholera High/Low) -----
    # Cross-plate overview + stats per control, modelled on Background QC.
    pc_hist = (history_pc.copy()
               if isinstance(history_pc, pd.DataFrame) and not history_pc.empty
               else pd.DataFrame())
    if not pc_hist.empty and "control_label" in pc_hist.columns:
        pc_hist["control"] = pc_hist["control_label"]
    pc_controls = _control_qc_sections(
        pc_hist, panel_order, metadata.get("plate_id"), excluded,
        "Single-point PC MFI (log scale)", "pc-sp")
    pc_present = bool(pc_controls)

    # ----- Negative Control QC -----
    # One cross-plate overview + stats per NC control (Negative 0/49).
    nc_hist = (history_nc.copy()
               if isinstance(history_nc, pd.DataFrame) and not history_nc.empty
               else pd.DataFrame())
    if not nc_hist.empty and "sample_name" in nc_hist.columns:
        nc_hist["control"] = nc_hist["sample_name"].apply(_nc_control)
    nc_controls = _control_qc_sections(
        nc_hist, panel_order, metadata.get("plate_id"), excluded,
        "NC MFI (log scale)", "nc-ctrl")
    # ----- Standard-Curve Summary + All-Curves Overview -----
    # per_pool (default): a curve for EVERY (pool × antigen) — one grid per
    # pool, summary rows per (pool × antigen); no matching/auto-selection.
    # auto_select: the single matched/best-fit curve per antigen.
    def _pool_fits_for(pool):
        return {a: {**fits[pool][a], "pool": pool}
                for a in priority_antigens if a in fits.get(pool, {})}

    if pool_mode == "per_pool":
        grid_parts, curve_summary = [], []
        for pi, pool in enumerate(pools):
            pf = _pool_fits_for(pool)
            if not pf:
                continue
            grid_parts.append(
                f'<h4 style="margin:18px 0 4px; color:#2c3e50;">Pool: {html.escape(pool)}</h4>'
                + _make_curve_grid(pf, excluded, in_range=in_range,
                                   div_id=f"fig-curve-grid-{pi}")
            )
            # %-in-range is a single-pool scoring metric; omit it per-pool.
            curve_summary += _build_curve_summary(pf, pd.DataFrame(), excluded, rec_tol)
        curve_grid_html = "".join(grid_parts) or "<p style='color:#999;'>No standard curve fits.</p>"
    else:
        priority_fits = {a: selected_fits[a] for a in priority_antigens if a in selected_fits}
        curve_grid_html = _make_curve_grid(priority_fits, excluded, in_range=in_range)
        curve_summary = _build_curve_summary(priority_fits, pct_in_range, excluded, rec_tol)
    layout_info = layout_info or _derive_layout_info(data)
    current_box_ids = layout_info.get("box_ids") or []
    # Picker covers ALL antigens (each via its selected pool's fit) — review tool.
    curve_picker_html = _make_curve_picker(
        selected_fits, excluded,
        in_range=in_range,
        history_specimens=history_specimens,
        history_fit=history_fit,
        current_plate_id=metadata.get("plate_id"),
        current_box_ids=current_box_ids,
    )
    cross_run_html = _make_cross_run_scatter(
        selected_fits, excluded,
        in_range=in_range,
        history_specimens=history_specimens,
        current_plate_id=metadata.get("plate_id"),
        current_box_ids=current_box_ids,
    )
    range_heatmap_html = _make_in_range_heatmap(in_range, excluded)
    serum_dbs_html = _make_serum_dbs_comparison(in_range)

    bead_problems = _format_problem_list(bead_qc.get("problems", pd.DataFrame()))
    range_problems = _format_range_problems(in_range, excluded)
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
        bead_problems=bead_problems,
        bead_problem_counts=_tier_counts(bead_qc.get("problems", pd.DataFrame())),
        curve_summary=curve_summary,
        pool_selection=pool_selection,
        pool_mode=pool_mode,
        scoring_pool=scoring_pool or "",
        n_priority_antigens=len(priority_antigens),
        priority_is_all=priority_is_all,
        n_panel_antigens=len(panel_order),
        curve_picker_html=curve_picker_html,
        cross_run_html=cross_run_html,
        cross_run_present=bool(cross_run_html),
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
        range_summary=_format_range_summary(range_summary),
        bg_levels=bg_levels_ctx,
        bg_overview_html=bg_overview_html,
        bg_overview_present=bool(bg_overview_html),
        problem_threshold_pct=int(round(problem_frac * 100)),
        bg_cv_pct=int(round(bg_cv_thr * 100)),
        bg_max_mfi=int(bg_max_thr),
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
    well_cols = list(matrix.columns)
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

# Specimen range-status colours (shared with the picker rug) — Okabe–Ito,
# colour-blind safe.
_STATUS_COLORS = {
    "BELOW_RANGE": "#0072B2", "IN_RANGE": "#009E73",
    "ABOVE_RANGE": "#D55E00", "NO_FIT": "#999999",
}
# Above this many panels the interactive grid gets too heavy, so we fall
# back to the static image. Setting priority antigens keeps it interactive.
_INTERACTIVE_GRID_CAP = 48


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
        y_lo = float(four_pl(np.array([float(lo_d)]), *params)[0])
        y_hi = float(four_pl(np.array([float(hi_d)]), *params)[0])
    except Exception:
        return None
    x0, x1 = sorted((float(lo_d), float(hi_d)))
    y0, y1 = sorted((y_lo, y_hi))
    return x0, x1, y0, y1


def _make_curve_grid(pool_fits: dict, excluded: set[str], cols: int = 6,
                     in_range: pd.DataFrame | None = None,
                     div_id: str = "fig-curve-grid") -> str:
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
        return _make_curve_grid_interactive(pool_fits, excluded, cols, in_range, div_id=div_id)
    return _make_curve_grid_static(pool_fits, excluded, cols=10)


def _make_curve_grid_interactive(pool_fits: dict, excluded: set[str], cols: int,
                                 in_range: pd.DataFrame | None,
                                 div_id: str = "fig-curve-grid") -> str:
    from plotly.subplots import make_subplots

    analytes = list(pool_fits.keys())
    n = len(analytes)
    cols = max(1, min(cols, n))
    rows = (n + cols - 1) // cols

    titles = []
    for an in analytes:
        fit = pool_fits[an]
        color = ("#95a5a6" if an in excluded
                 else _CB_GREEN if fit.get("fit_ok") else _CB_VERMILLION)
        short = an if len(an) <= 22 else an[:20] + "…"
        titles.append(f"<span style='color:{color}'>{short}</span>")

    fig = make_subplots(rows=rows, cols=cols, subplot_titles=titles,
                        horizontal_spacing=0.04,
                        vertical_spacing=max(0.02, min(0.06, 1.5 / max(rows, 1))))

    # Per-antigen current-plate specimen MFIs (for the rug), grouped once.
    spec_by_an: dict[str, pd.DataFrame] = {}
    if in_range is not None and not in_range.empty:
        for an, g in in_range.groupby("analyte"):
            spec_by_an[an] = g

    shown_legend = set()  # only emit each legend entry once
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

        # Out-of-tolerance standard points (red triangles) from obs/exp recovery.
        oe = fit.get("obs_exp") or []
        in_tol = [bool(o.get("in_range")) for o in oe] if oe else [True] * len(xd)
        if len(in_tol) != len(xd):
            in_tol = [True] * len(xd)
        ok_x = [x for x, t in zip(xd, in_tol) if t]
        ok_y = [y for y, t in zip(yd, in_tol) if t]
        bad_x = [x for x, t in zip(xd, in_tol) if not t]
        bad_y = [y for y, t in zip(yd, in_tol) if not t]

        # 4PL curve (red).
        if params is not None:
            xs = np.geomspace(max(xd.min(), 1e-9), xd.max(), 100)
            ys = four_pl(xs, *params)
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines", line=dict(color=_CB_VERMILLION, width=1.4),
                name="4PL fit", legendgroup="fit",
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
    panel_h = 150
    fig.update_layout(
        height=max(260, rows * panel_h + 80),
        margin=dict(l=40, r=20, t=46, b=30),
        plot_bgcolor="#fbfcfd",
        legend=dict(orientation="h", x=0.5, xanchor="center", y=1.02,
                    yanchor="bottom", font=dict(size=10)),
    )
    return _plotly_html(fig, div_id, height=max(260, rows * panel_h + 80))


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
                ax.plot(xs, four_pl(xs, *params), color=_CB_VERMILLION, linewidth=1.2, zorder=2)
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
        out.setdefault(r.analyte, []).append({
            "plate_id": getattr(r, "plate_id", ""),
            "box_ids": getattr(r, "box_ids", ""),
            "params": (float(r.a), float(r.b), float(r.c), float(r.d)),
        })
    return out


def _make_curve_picker(
    pool_fits: dict,
    excluded: set[str],
    in_range: pd.DataFrame | None = None,
    history_specimens: pd.DataFrame | None = None,
    history_fit: dict | pd.DataFrame | None = None,
    current_plate_id: str | None = None,
    current_box_ids: list[str] | None = None,
) -> str:
    """Curve + per-status rug subplot, with cross-plate overlays.

    Two-column figure:
        col 1 — standards + current 4PL + greyed historical curves
                (log-log; one curve per past plate, legend-toggleable)
        col 2 — rug panel with five categorical x-positions:
                  [BELOW, IN, ABOVE, NO FIT] for the current plate
                  +  [Past] for grey historical specimens from every
                            visible past plate (each past plate is its
                            own trace so the legend toggle works).
                Above each of the four status columns sits a layout
                annotation reading "count (pct%)" for the current plate
                / current antigen. The annotations are swapped via
                ``Plotly.relayout`` when the typeahead changes antigen.

    Slot layout per analyte (typeahead visibility array stays dense):
        [0 .. P-1]                — historical 4PL curves (col 1)
        [P .. 2P-1]               — historical specimens rugs (col 2)
        2P                        — current standards (col 1)
        2P+1                      — current 4PL fit (col 1)
        [2P+2 .. 2P+5]            — current specimen rugs by status
                                    (col 2; BELOW / IN / ABOVE / NO_FIT)

    Each historical trace gets ``legendgroup="plate:<plate_id>"`` so
    one legend click hides every overlay for that plate across every
    antigen. ``current_box_ids`` lets us label the current plate's
    legend entry / title as ``PLATE_…RUN000 · Box1``.
    """
    if not pool_fits:
        return "<p style='color:#999;'>No standard curve fits.</p>"

    STATUS_ORDER = ["BELOW_RANGE", "IN_RANGE", "ABOVE_RANGE", "NO_FIT"]
    STATUS_LABEL = {"BELOW_RANGE": "BELOW", "IN_RANGE": "IN",
                    "ABOVE_RANGE": "ABOVE", "NO_FIT": "NO FIT"}
    STATUS_RUG_COLOR = dict(_STATUS_COLORS)
    HIST_GREY = "#b0b6bd"
    # Rug x-positions in the second subplot. Current-plate specimens
    # stack in a single column at x=0 (colour-coded by status). Each
    # past plate gets its own column at x=1, 2, …, P so the user can
    # scan horizontally across "This run" vs every past run and read
    # any sample's MFI in context.
    RUG_X = {"BELOW_RANGE": 0, "IN_RANGE": 0, "ABOVE_RANGE": 0, "NO_FIT": 0}

    analytes = list(pool_fits.keys())
    current_label = _plate_label(current_plate_id, current_box_ids)
    current_short = _short_plate_label(current_plate_id, current_box_ids)

    # ----- Per-analyte slices -----
    cur_specs_by_an: dict[str, pd.DataFrame] = {}
    if in_range is not None and not in_range.empty:
        cur_specs_by_an = {an: g for an, g in in_range.groupby("analyte", sort=False)}

    hist_specs_df = None
    if history_specimens is not None and isinstance(history_specimens, pd.DataFrame) and not history_specimens.empty:
        hist_specs_df = history_specimens
        if current_plate_id and "plate_id" in hist_specs_df.columns:
            hist_specs_df = hist_specs_df[hist_specs_df["plate_id"] != current_plate_id]
        if hist_specs_df.empty:
            hist_specs_df = None

    hist_fits_by_an: dict[str, list[dict]] = _hist_fits_by_analyte(history_fit, current_plate_id)

    # ----- Past-plate roster (stable order) -----
    plate_set: set[str] = set()
    box_by_plate: dict[str, str] = {}
    if hist_specs_df is not None:
        plate_set.update(hist_specs_df["plate_id"].dropna().astype(str).unique())
        if "box_id" in hist_specs_df.columns:
            for p, g in hist_specs_df.groupby("plate_id"):
                boxes = sorted({str(b) for b in g["box_id"].dropna().unique() if str(b).strip()})
                if boxes:
                    box_by_plate[str(p)] = ",".join(boxes)
    for rows in hist_fits_by_an.values():
        for r in rows:
            pid = str(r.get("plate_id", ""))
            plate_set.add(pid)
            box_by_plate.setdefault(pid, str(r.get("box_ids", "")))
    plate_set.discard("")
    if current_plate_id:
        plate_set.discard(current_plate_id)

    if hist_specs_df is not None and "run_date" in hist_specs_df.columns:
        date_by_plate = (
            hist_specs_df.groupby("plate_id")["run_date"]
            .agg(lambda s: s.dropna().iloc[0] if s.dropna().size else "")
        )
        past_plates = sorted(plate_set, key=lambda p: (date_by_plate.get(p, ""), p))
    else:
        past_plates = sorted(plate_set)

    P = len(past_plates)
    hist_specs_lookup: dict[tuple[str, str], pd.DataFrame] = {}
    if hist_specs_df is not None and P:
        for (plate, an), g in hist_specs_df.groupby(["plate_id", "analyte"], sort=False):
            hist_specs_lookup[(str(plate), an)] = g
    hist_fit_lookup: dict[tuple[str, str], tuple[float, float, float, float]] = {}
    for an, rows in hist_fits_by_an.items():
        for r in rows:
            hist_fit_lookup[(str(r["plate_id"]), an)] = r["params"]

    # ----- Subplot scaffold -----
    # Rug subplot width scales with the number of plate columns (one
    # for "This run" + one per past plate). 0.08 of figure width per
    # column, capped at 0.42 so the curve panel never collapses
    # below ~58% of the figure even with a long plate history.
    n_rug_cols = 1 + P
    rug_width = min(0.08 * n_rug_cols + 0.04, 0.42)
    curve_width = 1.0 - rug_width
    fig = make_subplots(
        rows=1, cols=2,
        column_widths=[curve_width, rug_width],
        shared_yaxes=True,
        horizontal_spacing=0.015,
    )

    # Helper: build (a) a single multi-line status-summary annotation
    # pinned to the top-left of the curve panel, and (b) the two
    # one-line column headers above the rug subplot ("This plate",
    # "Past"). Annotations are swapped per antigen via Plotly.relayout.
    def _rug_annotations(an: str) -> list[dict]:
        cur = cur_specs_by_an.get(an)
        total = int(len(cur)) if cur is not None else 0
        counts = cur["status"].value_counts().to_dict() if cur is not None else {}

        # Status-summary block: one row per status, count + percent.
        rows = [f"<b>This plate · {total} specimen{'s' if total != 1 else ''}</b>"]
        for status in STATUS_ORDER:
            n = int(counts.get(status, 0))
            pct = (n / total * 100.0) if total else 0.0
            color = STATUS_RUG_COLOR[status]
            label = STATUS_LABEL[status]
            count_str = f"{n}&nbsp;({pct:.0f}%)" if total else "—"
            rows.append(
                f"<span style='color:{color}; font-weight:600;'>{label}</span>"
                f" &nbsp; {count_str}"
            )
        summary_text = "<br>".join(rows)

        anns: list[dict] = [dict(
            # Paper coords — pinned to the upper-right of the curve
            # subplot. xanchor="right" anchors the box's right edge
            # just inside the curve subplot's right boundary; the box
            # extends leftward into empty curve space without crossing
            # into the rug panel.
            x=curve_width - 0.01, y=0.99, xref="paper", yref="paper",
            xanchor="right", yanchor="top",
            text=summary_text,
            showarrow=False, align="left",
            font=dict(size=11, family="ui-monospace, Menlo, Consolas, monospace"),
            bgcolor="rgba(255,255,255,0.92)",
            bordercolor="#d0d7de", borderwidth=1,
            borderpad=6,
        )]

        # Rug column headers — one per column (This run + each past plate).
        anns.append(dict(
            x=0, y=1.03, xref="x2", yref="paper",
            xanchor="center", yanchor="bottom",
            text="<b>This run</b>", showarrow=False,
            font=dict(size=10),
        ))
        for plate_idx, plate in enumerate(past_plates):
            ps = _short_plate_label(plate, box_by_plate.get(plate, ""))
            # Date only (left half of the short label) keeps headers tight.
            short_head = ps.split(" · ")[0] if " · " in ps else ps
            anns.append(dict(
                x=1 + plate_idx, y=1.03, xref="x2", yref="paper",
                xanchor="center", yanchor="bottom",
                text=(f"<span style='color:#7f8c8d;'>{short_head}</span>"),
                showarrow=False, font=dict(size=9),
            ))
        return anns

    # ----- Build figure (per analyte) -----
    for ai, an in enumerate(analytes):
        fit = pool_fits[an]
        std = fit.get("mean_data")
        params = fit.get("params")
        x_min = float(std["dilution"].min()) if std is not None and not std.empty else 1.0
        x_max = float(std["dilution"].max()) if std is not None and not std.empty else 1.0
        vis = (ai == 0)

        # --- col 1, back layer: historical curves ---
        # NB: showlegend=False on every per-antigen trace. The per-plate
        # legend entries are anchored to dedicated "legend-anchor"
        # traces added AFTER the per-antigen loop. This makes the
        # legend entries persist across antigen switches; without the
        # anchor, the legend traces were tied to the first antigen's
        # copy and would vanish (or do nothing on click) when the user
        # typeaheaded to a different antigen.
        for plate in past_plates:
            plate_full = _plate_label(plate, box_by_plate.get(plate, ""))
            params_hist = hist_fit_lookup.get((plate, an))
            if params_hist is not None:
                hxs = np.geomspace(x_min, x_max, 60)
                hys = four_pl(hxs, *params_hist)
                fig.add_trace(go.Scatter(
                    x=hxs, y=hys, mode="lines",
                    line=dict(color=HIST_GREY, width=1.2, dash="dot"),
                    name="", legendgroup=f"plate:{plate}",
                    showlegend=False,
                    hovertemplate=(
                        f"<b>{plate_full}</b><br>"
                        "Dilution 1:%{x:.0f}<br>MFI %{y:.0f}<extra></extra>"
                    ),
                    visible=vis,
                ), row=1, col=1)
            else:
                fig.add_trace(go.Scatter(
                    x=[], y=[], mode="lines",
                    line=dict(color=HIST_GREY, width=1.2, dash="dot"),
                    name="", legendgroup=f"plate:{plate}",
                    showlegend=False, visible=vis,
                ), row=1, col=1)

        # --- col 2, back layer: historical specimen rugs (one column per past plate) ---
        for plate_idx, plate in enumerate(past_plates):
            plate_full = _plate_label(plate, box_by_plate.get(plate, ""))
            x_pos = 1 + plate_idx  # past plates start at x=1 (this plate is x=0)
            sub = hist_specs_lookup.get((plate, an))
            if sub is not None and not sub.empty:
                # Hover fields: sample_name (barcode for specimens),
                # patient_id (when known), well, MFI, plus the plate label.
                sample_lbl  = sub.get("sample_name", pd.Series([""] * len(sub))).fillna("").astype(str)
                well_lbl    = sub.get("well", pd.Series([""] * len(sub))).fillna("").astype(str)
                patient_lbl = sub.get("patient_id", pd.Series([""] * len(sub))).fillna("").astype(str)
                customdata = list(zip(
                    [plate_full] * len(sub), sample_lbl, well_lbl, patient_lbl,
                ))
                fig.add_trace(go.Scatter(
                    x=[x_pos] * len(sub), y=sub["mfi"],
                    mode="markers",
                    marker=dict(symbol="line-ew-open", size=12, color=HIST_GREY,
                                line=dict(width=2, color=HIST_GREY)),
                    name="", legendgroup=f"plate:{plate}",
                    showlegend=False,
                    customdata=customdata,
                    hovertemplate=(
                        "<b>%{customdata[0]}</b><br>"
                        "Sample: %{customdata[1]}"
                        "  (well %{customdata[2]})<br>"
                        "Patient ID: %{customdata[3]}<br>"
                        "MFI %{y:.0f}<extra></extra>"
                    ),
                    visible=vis,
                ), row=1, col=2)
            else:
                fig.add_trace(go.Scatter(
                    x=[], y=[], mode="markers",
                    marker=dict(symbol="line-ew-open", size=12, color=HIST_GREY),
                    name="", legendgroup=f"plate:{plate}",
                    showlegend=False, visible=vis,
                ), row=1, col=2)

        # --- col 1, front layer: current standards ---
        # showlegend=False on every per-antigen copy; the legend
        # entries for "Standards" and "This plate (…)" are anchored on
        # dedicated always-visible traces appended after the loop.
        if std is not None and not std.empty:
            fig.add_trace(go.Scatter(
                x=std["dilution"], y=std["mfi"], mode="markers",
                name="", legendgroup="current",
                showlegend=False,
                marker=dict(size=10, color="#2c3e50"),
                hovertemplate="Dilution 1:%{x:.0f}<br>MFI %{y:.0f}<extra></extra>",
                visible=vis,
            ), row=1, col=1)
        else:
            fig.add_trace(go.Scatter(
                x=[], y=[], mode="markers",
                name="", legendgroup="current",
                showlegend=False, visible=vis,
            ), row=1, col=1)

        # --- col 1, front layer: current 4PL fit ---
        if params is not None and std is not None and not std.empty:
            xs = np.geomspace(x_min, x_max, 80)
            ys = four_pl(xs, *params)
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines",
                name="", legendgroup="current",
                showlegend=False,
                line=dict(color="#3498db", width=2),
                hovertemplate="Dilution 1:%{x:.0f}<br>MFI %{y:.0f}<extra></extra>",
                visible=vis,
            ), row=1, col=1)
        else:
            fig.add_trace(go.Scatter(
                x=[], y=[], mode="lines",
                name="", legendgroup="current",
                showlegend=False,
                line=dict(color="#3498db", width=2), visible=vis,
            ), row=1, col=1)

        # --- col 2, front layer: current specimen rugs (one per status) ---
        cur = cur_specs_by_an.get(an)
        for status in STATUS_ORDER:
            color = STATUS_RUG_COLOR[status]
            x_pos = RUG_X[status]
            if cur is not None and not cur.empty:
                sub = cur[cur["status"] == status]
                if not sub.empty:
                    sample_lbl  = sub.get("sample_name", pd.Series([""] * len(sub))).fillna("").astype(str)
                    well_lbl    = sub.get("well", pd.Series([""] * len(sub))).fillna("").astype(str)
                    patient_lbl = sub.get("patient_id", pd.Series([""] * len(sub))).fillna("").astype(str)
                    customdata = list(zip(sample_lbl, well_lbl, patient_lbl))
                    fig.add_trace(go.Scatter(
                        x=[x_pos] * len(sub), y=sub["mfi"],
                        mode="markers",
                        marker=dict(symbol="line-ew-open", size=14,
                                    color=color,
                                    line=dict(width=2, color=color)),
                        name=f"{STATUS_LABEL[status]} (this plate)",
                        legendgroup="current", showlegend=False,
                        customdata=customdata,
                        hovertemplate=(
                            f"<b>{STATUS_LABEL[status]}</b><br>"
                            "Sample: %{customdata[0]}"
                            "  (well %{customdata[1]})<br>"
                            "Patient ID: %{customdata[2]}<br>"
                            "MFI %{y:.0f}<extra></extra>"
                        ),
                        visible=vis,
                    ), row=1, col=2)
                    continue
            fig.add_trace(go.Scatter(
                x=[], y=[], mode="markers",
                name=f"{STATUS_LABEL[status]} (this plate)",
                legendgroup="current", showlegend=False,
                marker=dict(symbol="line-ew-open", size=14, color=color),
                visible=vis,
            ), row=1, col=2)

        # --- col 1: linear / reportable-range rectangle (drawn as a filled
        # trace so it reliably renders and toggles with the antigen). One
        # trace per antigen (empty when the antigen has no reportable range)
        # to keep n_per_analyte constant. ---
        box = _linear_range_box(fit)
        if box is not None:
            rx0, rx1, ry0, ry1 = box
            fig.add_trace(go.Scatter(
                x=[rx0, rx1, rx1, rx0, rx0], y=[ry0, ry0, ry1, ry1, ry0],
                mode="lines", fill="toself", fillcolor="rgba(39,174,96,0.14)",
                line=dict(color=_CB_GREEN, width=1.2, dash="dash"),
                name="Linear range", legendgroup="current", showlegend=False,
                hoverinfo="skip", visible=vis,
            ), row=1, col=1)
        else:
            fig.add_trace(go.Scatter(
                x=[], y=[], mode="lines", fill="toself",
                line=dict(color=_CB_GREEN, width=1.2, dash="dash"),
                name="Linear range", legendgroup="current",
                showlegend=False, hoverinfo="skip", visible=vis,
            ), row=1, col=1)

    # ----- Legend-anchor traces -----
    # Always-visible, no-data placeholder traces that host the legend
    # entries. They live OUTSIDE the per-antigen slot scheme so the
    # legend stays the same regardless of which antigen the user has
    # typeaheaded to. Two current-plate anchors (Standards + 4PL fit)
    # plus one per past plate.
    #
    # Past-plate clicks are intercepted by the JS shim below which
    # manages a hiddenPlates set and overrides Plotly's default toggle
    # behaviour. Current-plate anchors use legendgroup="current" so
    # toggling them hides all per-antigen Standards / 4PL / rug traces
    # via Plotly's default behaviour (no special handling needed; users
    # rarely toggle these but the entries make sense to display).

    # Current-plate anchors
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode="markers",
        name="Standards", legendgroup="current",
        showlegend=True, visible=True,
        marker=dict(size=10, color="#2c3e50"),
        hoverinfo="skip",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode="lines",
        name=f"This plate ({current_short})" if current_short else "This plate",
        legendgroup="current",
        showlegend=True, visible=True,
        line=dict(color="#3498db", width=2),
        hoverinfo="skip",
    ), row=1, col=1)

    # Past-plate anchors
    for plate in past_plates:
        plate_short = _short_plate_label(plate, box_by_plate.get(plate, ""))
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="lines",
            line=dict(color=HIST_GREY, width=1.2, dash="dot"),
            name=plate_short,
            legendgroup=f"plate:{plate}",
            showlegend=True, visible=True,
            hoverinfo="skip",
        ), row=1, col=1)

    # ----- Layout -----
    # 2P historical (curve + rug) + 1 std + 1 4PL + 4 status rugs + 1
    # linear-range rectangle = 2P + 7 traces per antigen.
    n_per_analyte = 2 * P + 7
    n_traces = len(analytes) * n_per_analyte
    # +2 for the current-plate anchors (Standards, 4PL fit), +P for past plates.
    n_anchor_current = 2
    n_total_traces = n_traces + n_anchor_current + P

    # Per-trace plate map. ``null`` for current-plate traces (legend toggle
    # not handled per-plate); plate_id string for traces whose
    # visibility should be controlled by the per-plate legend toggle
    # (i.e. past-plate curves + rugs + their anchors).
    trace_plate_map: list[str | None] = []
    for ai in range(len(analytes)):
        for slot in range(n_per_analyte):
            if slot < P:
                trace_plate_map.append(past_plates[slot])
            elif slot < 2 * P:
                trace_plate_map.append(past_plates[slot - P])
            else:
                trace_plate_map.append(None)
    # current-plate anchors
    trace_plate_map.append(None)  # Standards anchor
    trace_plate_map.append(None)  # 4PL fit anchor
    # past-plate anchors
    for plate in past_plates:
        trace_plate_map.append(plate)
    assert len(trace_plate_map) == n_total_traces

    # X-range for curve (col 1) — pad lightly so the leftmost / rightmost
    # standard points aren't flush against the axis.
    first_std = pool_fits[analytes[0]].get("mean_data")
    if first_std is not None and not first_std.empty:
        x_max_panel = float(first_std["dilution"].max())
        x_min_panel = float(first_std["dilution"].min())
    else:
        x_max_panel = 1.0
        x_min_panel = 1.0
    pad_lo = np.log10(max(x_min_panel * 0.85, 1e-6))
    pad_hi = np.log10(x_max_panel * 1.4)

    first_label_an = ("⚠ " if analytes[0] in excluded else "") + analytes[0]
    first_fit = pool_fits[analytes[0]]
    legend_layout = dict(
        title=dict(text="Plates · click to toggle" if P else "",
                   font=dict(size=10, color="#7f8c8d")),
        orientation="v",
        x=1.01, xanchor="left", y=1.0, yanchor="top",
        bgcolor="rgba(255,255,255,0.85)",
        bordercolor="#d0d7de", borderwidth=1,
        font=dict(size=10),
        itemsizing="constant",
        tracegroupgap=2,
    )
    fig.update_layout(
        title=dict(text=(
            f"<b>{first_label_an}</b> &nbsp;·&nbsp; "
            f"fit_ok={first_fit.get('fit_ok')} &nbsp;·&nbsp; "
            f"params={_fmt_params(first_fit.get('params'))}"
        )),
        margin=dict(l=70, r=180, t=110, b=60),
        height=560,
        showlegend=True,
        legend=legend_layout,
        annotations=list(fig.layout.annotations or []) + _rug_annotations(analytes[0]),
    )
    fig.update_xaxes(type="log", title="Dilution factor (1 : x)",
                     range=[pad_lo, pad_hi], row=1, col=1)
    # Rug subplot's bottom x-axis is redundant with the per-column
    # header annotations above each tick. Hide it entirely; the
    # categorical positions still drive the trace x-values. One
    # column for "This run" at x=0 and one column per past plate at
    # x=1..P. Tight half-step padding on either side.
    rug_x_range = [-0.5, 0.5 + P]
    fig.update_xaxes(
        range=rug_x_range,
        showticklabels=False, showgrid=False, showline=False, zeroline=False,
        ticks="", title="", row=1, col=2,
    )
    # Both y-axes must be ``log`` so MFI values land at the same visual
    # position in the curve panel and in the rug panel. ``matches='y'``
    # (set by ``shared_yaxes=True``) propagates the *range* between the
    # two axes but Plotly does not reliably propagate the scale type;
    # if one is log and the other linear, the rug ticks sit at
    # different visual positions than the same MFI value on the curve.
    fig.update_yaxes(type="log", title="MFI", row=1, col=1)
    fig.update_yaxes(type="log", showgrid=True, row=1, col=2)

    import math as _math

    def _y_range_for(an: str) -> list[float] | None:
        """Common log10 MFI range covering this antigen's standards, current-
        plate specimens, and historical specimens — applied to BOTH the curve
        and rug panels so a given MFI lands at the same height in each."""
        vals: list[float] = []
        std = pool_fits.get(an, {}).get("mean_data")
        if std is not None and not std.empty:
            vals += [float(v) for v in std["mfi"].dropna().tolist()]
        cur = cur_specs_by_an.get(an)
        if cur is not None and not cur.empty:
            vals += [float(v) for v in cur["mfi"].dropna().tolist()]
        for plate in past_plates:
            h = hist_specs_lookup.get((plate, an))
            if h is not None and not h.empty:
                vals += [float(v) for v in h["mfi"].dropna().tolist()]
        vals = [v for v in vals if v and v > 0]
        if not vals:
            return None
        lo, hi = min(vals), max(vals)
        lo_l, hi_l = _math.log10(lo), _math.log10(hi)
        pad = max(0.1, 0.06 * (hi_l - lo_l))
        return [lo_l - pad, hi_l + pad]

    # Pin BOTH panels to the same explicit y-range for the first antigen so
    # the rug and curve are aligned on load (refreshed per antigen on pick).
    _first_yr = _y_range_for(analytes[0])
    if _first_yr:
        fig.update_yaxes(range=_first_yr, row=1, col=1)
        fig.update_yaxes(range=_first_yr, row=1, col=2)

    # Vertical separators between adjacent rug columns: one between
    # "This run" and the first past plate (heavier line so the
    # current vs past distinction reads at a glance), then one between
    # each pair of past plates.
    for col_boundary in range(P):
        is_first = col_boundary == 0
        fig.add_shape(
            type="line", xref="x2", yref="paper",
            x0=0.5 + col_boundary, x1=0.5 + col_boundary, y0=0, y1=1.05,
            line=dict(color="#d0d7de", width=1.6 if is_first else 0.8, dash="dot"),
            opacity=0.95 if is_first else 0.6, layer="above",
        )

    fig_html = _plotly_html(fig, "fig-curve-picker", height=600)

    # ----- Typeahead lookup (visibility + title + annotations) -----
    # Each antigen's ``vis`` array has length n_total_traces. Per-antigen
    # slots (the first n_traces entries) flip on/off based on which
    # antigen is selected. The anchor traces (last 2+P entries) are
    # always ``True`` here — the JS shim below will downgrade them to
    # ``"legendonly"`` for any plate the user has hidden via legend
    # click.
    lookup: dict[str, dict] = {}
    for ai, an in enumerate(analytes):
        vis: list = [False] * n_total_traces
        base = ai * n_per_analyte
        for k in range(n_per_analyte):
            vis[base + k] = True
        # Anchors at the tail — always visible by default.
        for idx in range(n_traces, n_total_traces):
            vis[idx] = True
        label = f"⚠ {an} (excluded)" if an in excluded else an
        fit = pool_fits[an]
        title = (
            f"<b>{label}</b> &nbsp;·&nbsp; "
            f"fit_ok={fit.get('fit_ok')} &nbsp;·&nbsp; "
            f"params={_fmt_params(fit.get('params'))}"
        )
        lookup[an] = {"vis": vis, "title": title,
                      "annotations": _rug_annotations(an), "yrange": _y_range_for(an)}

    lookup_js = json.dumps(lookup).replace("</", "<\\/")
    trace_plate_map_js = json.dumps(trace_plate_map).replace("</", "<\\/")
    past_plates_js = json.dumps(past_plates).replace("</", "<\\/")
    options_html = "\n".join(f'<option value="{html.escape(a)}">' for a in analytes)
    first_antigen_js = json.dumps(analytes[0])
    typeahead_html = f"""
<div style="display:flex; gap:10px; align-items:center; margin: 0 0 8px;">
  <label for="curve-picker-input" style="font-size:13px; color:#34495e; font-weight:600;">
    Search antigen:
  </label>
  <input id="curve-picker-input" list="curve-picker-list"
         placeholder="start typing… e.g. RES_Ade3"
         autocomplete="off"
         style="flex:1; max-width:340px; padding:6px 10px; font-size:13px;
                border:1px solid #d0d7de; border-radius:4px;">
  <datalist id="curve-picker-list">
    {options_html}
  </datalist>
  <span id="curve-picker-status" style="font-size:12px; color:#7f8c8d;"></span>
</div>
<script>
(function () {{
  var DIV = "fig-curve-picker";
  var lookup = {lookup_js};
  var tracePlateMap = {trace_plate_map_js};
  var pastPlates = {past_plates_js};
  var input  = document.getElementById("curve-picker-input");
  var status = document.getElementById("curve-picker-status");
  if (!input) return;

  // State: which past plates has the user hidden via legend click?
  // Persists across antigen typeahead switches so the user's choice
  // sticks when they navigate to a different antigen.
  var hiddenPlates = {{}};   // {{ plateId: true }} — using object as a Set
  var currentEntry = lookup[{first_antigen_js}];

  // Merge per-antigen visibility with hidden-plates state and push
  // to Plotly via restyle. Visible traces belonging to a hidden
  // plate become "legendonly" so the legend entry stays visible (and
  // greyed) but the data is hidden from the plot.
  function applyVisibility(entry) {{
    if (!entry) return;
    var vis = entry.vis.slice();
    for (var i = 0; i < vis.length; i++) {{
      var plate = tracePlateMap[i];
      if (plate && hiddenPlates[plate]) {{
        vis[i] = "legendonly";
      }}
    }}
    Plotly.restyle(DIV, {{visible: vis}});
  }}

  // Legend click — intercept Plotly's default toggle. We toggle our
  // own hiddenPlates state and re-apply the merged visibility. Only
  // applies to past-plate legend entries (the "current" group click
  // falls through to Plotly's default behaviour, which is fine).
  function wireLegend() {{
    var graphDiv = document.getElementById(DIV);
    if (!graphDiv || !graphDiv.on) return;
    graphDiv.on('plotly_legendclick', function (eventData) {{
      var traceIdx = eventData.curveNumber;
      var plate = tracePlateMap[traceIdx];
      if (!plate) return true;  // "current" legendgroup — let Plotly handle.
      if (hiddenPlates[plate]) delete hiddenPlates[plate];
      else hiddenPlates[plate] = true;
      applyVisibility(currentEntry);
      return false;  // prevent default toggle
    }});
    graphDiv.on('plotly_legenddoubleclick', function (eventData) {{
      var traceIdx = eventData.curveNumber;
      var plate = tracePlateMap[traceIdx];
      if (!plate) return true;
      // Toggle isolate: if only this plate is shown, restore all;
      // otherwise hide all others.
      var allOthers = pastPlates.filter(function (p) {{ return p !== plate; }});
      var allHidden = allOthers.every(function (p) {{ return hiddenPlates[p]; }});
      if (allHidden && !hiddenPlates[plate]) {{
        hiddenPlates = {{}};
      }} else {{
        hiddenPlates = {{}};
        allOthers.forEach(function (p) {{ hiddenPlates[p] = true; }});
      }}
      applyVisibility(currentEntry);
      return false;
    }});
  }}

  function pick(name) {{
    var entry = lookup[name];
    if (!entry) {{
      status.textContent = name ? "no match" : "";
      return;
    }}
    status.textContent = "";
    currentEntry = entry;
    applyVisibility(entry);
    // 3-arg relayout — Plotly replaces the array wholesale, which is
    // what makes the per-antigen summary text refresh on every pick.
    Plotly.relayout(DIV, "title.text", entry.title);
    Plotly.relayout(DIV, "annotations", entry.annotations);
    if (entry.yrange) {{
      // Pin both panels to the same y-range so the rug stays aligned to the curve.
      Plotly.relayout(DIV, {{"yaxis.range": entry.yrange, "yaxis2.range": entry.yrange}});
    }}
  }}

  input.addEventListener("change", function () {{ pick(input.value.trim()); }});
  input.addEventListener("input",  function () {{
    if (lookup[input.value.trim()]) pick(input.value.trim());
  }});

  // The Plotly chart may not be drawn yet when this script runs —
  // wait for it before wiring the legend handler.
  if (document.getElementById(DIV)) wireLegend();
  else window.addEventListener("load", wireLegend);
}})();
</script>
"""
    return typeahead_html + fig_html


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
         placeholder="start typing… e.g. RES_Ade3"
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
    y_ticktext = [f"<i>{a} (excluded)</i>" if a in excluded else a for a in analyte_rows]

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


def _make_in_range_heatmap(in_range: pd.DataFrame, excluded: set[str]) -> str:
    if in_range is None or in_range.empty:
        return "<p style='color:#999;'>No in-range data.</p>"

    # Four-state classification with a colorblind-friendly scheme:
    #   BELOW_RANGE = blue, IN_RANGE = teal, ABOVE_RANGE = orange, NO_FIT = yellow.
    status_to_int = {"BELOW_RANGE": 0, "IN_RANGE": 1, "ABOVE_RANGE": 2, "NO_FIT": 3}
    pivot = in_range.pivot_table(
        index="analyte", columns="well", values="status", aggfunc="first",
    )
    analyte_order = list(in_range.drop_duplicates("analyte")["analyte"])
    well_order = list(in_range.drop_duplicates("well")["well"])
    pivot = pivot.reindex(index=analyte_order, columns=well_order)

    z = np.vectorize(lambda s: status_to_int.get(s, 3))(pivot.values)
    # Prefer an explicit sample_id when present, else the sample_name.
    id_col = "sample_id" if "sample_id" in in_range.columns else "sample_name"
    sample_labels = (
        in_range.drop_duplicates("well").set_index("well")[id_col].astype(str).to_dict()
    )
    status_disp = {"BELOW_RANGE": "Below range", "IN_RANGE": "In range",
                   "ABOVE_RANGE": "Above range", "NO_FIT": "No fit"}
    text = np.empty(z.shape, dtype=object)
    for i, an in enumerate(analyte_order):
        for j, w in enumerate(well_order):
            status = pivot.iat[i, j]
            sid = sample_labels.get(w, "") or "—"
            text[i, j] = (f"<b>{an}</b><br>Well: {w}<br>Sample: {sid}<br>"
                          f"Status: {status_disp.get(status, status)}")

    colorscale = [
        [0.00, "#4477AA"], [0.25, "#4477AA"],   # BELOW_RANGE — blue
        [0.25, "#44AA99"], [0.50, "#44AA99"],   # IN_RANGE — teal
        [0.50, "#EE7733"], [0.75, "#EE7733"],   # ABOVE_RANGE — orange
        [0.75, "#CCBB44"], [1.00, "#CCBB44"],   # NO_FIT — yellow
    ]
    return _freeze_pane_heatmap(
        analyte_order, well_order, z, text, colorscale, 0, 3, excluded, "fig-range",
    )


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
        a, b, c, d = params
        rr = fit.get("reportable_range") or {}
        pct = pct_lookup.get(an)
        rows.append({
            "analyte": an,
            "pool": fit.get("pool", "—"),
            "excluded": an in excluded,
            "fit_ok": bool(fit.get("fit_ok")),
            "n_points": len(fit.get("mean_data", [])) if fit.get("mean_data") is not None else 0,
            "a": _fmt(a, 1),
            "b": _fmt(b, 2),
            "c_ic50": _fmt(c, 1),
            "d": _fmt(d, 1),
            "lloq_dilution": _fmt(rr.get("lloq_dilution"), 1),
            "uloq_dilution": _fmt(rr.get("uloq_dilution"), 1),
            "pct_in_range": _fmt(pct, 1),
            "qc_warnings": "; ".join(fit.get("qc_warnings") or []) or "—",
            "dropped_point": fit.get("dropped_point"),
        })
    return rows


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
        return {"red": 0, "yellow": 0}
    counts = problems["tier"].value_counts().to_dict()
    return {"red": int(counts.get("red", 0)), "yellow": int(counts.get("yellow", 0))}


def _format_range_problems(in_range: pd.DataFrame, excluded: set[str]) -> list[dict]:
    if in_range is None or in_range.empty:
        return []
    out = in_range[in_range["status"].isin(["BELOW_RANGE", "ABOVE_RANGE"])]
    rows = []
    for r in out.itertuples(index=False):
        rows.append({
            "well": r.well,
            "sample_name": r.sample_name,
            "analyte": r.analyte,
            "mfi": _fmt(r.mfi, 1),
            "mfi_lloq": _fmt(r.mfi_lloq, 1),
            "mfi_uloq": _fmt(r.mfi_uloq, 1),
            "status": r.status,
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


def _format_range_summary(range_summary: dict) -> dict:
    ant = range_summary.get("antigen_summary", pd.DataFrame())
    smp = range_summary.get("sample_summary", pd.DataFrame())

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
            else:
                row["excluded"] = bool(getattr(r, "excluded", False))
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


def _cross_plate_mfi_overview(
    hist: pd.DataFrame,
    antigens: list[str] | None,
    current_plate_id: str | None,
    value_label: str,
    div_id: str,
    excluded: set[str] | None = None,
) -> str:
    """Cross-plate MFI overview for one control (Background, PC, or NC).

    x = antigen (panel order), y = MFI (log scale). The historical reference is
    built from each *past* plate's mean for the control:

    - **≥ 3 past plates** — a grey bar spans the historical Q1–Q3 (IQR) with a
      median tick; this plate's mean is a dot, coloured **blue within the IQR**
      and **red (diamond) above/below it** as a provisional flag.
    - **< 3 past plates** — each past plate's mean is a faint grey dot (no IQR
      yet) and this plate's mean is a neutral blue dot.

    The current dot's hover lists this plate's individual well MFIs. (Per-plate
    historical points are intentionally omitted from the plot — the per-antigen
    numbers are in the stats table below.)
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

    cur = df[df["plate_id"] == current_plate_id]
    past = df[df["plate_id"] != current_plate_id]
    past_means = (past.groupby(["plate_id", "analyte"])["mfi"].mean().reset_index()
                  if not past.empty else pd.DataFrame(columns=["plate_id", "analyte", "mfi"]))
    n_past_plates = int(past["plate_id"].nunique()) if not past.empty else 0
    iqr_mode = n_past_plates >= 3

    def _floor(v):
        return max(float(v), 0.1)

    iqr_x, iqr_y = [], []
    med_x, med_y, med_t = [], [], []
    pastdot_x, pastdot_y, pastdot_t = [], [], []   # past-plate means (only when < 3 plates)
    in_x, in_y, in_t = [], [], []     # current mean within IQR
    out_x, out_y, out_t = [], [], []  # current mean outside IQR (flag)
    neu_x, neu_y, neu_t = [], [], []  # current mean, no IQR yet (neutral)

    cur_groups = cur.groupby("analyte") if not cur.empty else None
    for a in order_keys:
        i = an_index[a]
        pm = (past_means.loc[past_means["analyte"] == a, "mfi"].dropna().astype(float)
              if not past_means.empty else pd.Series(dtype=float))
        q1r = q3r = None  # raw Q1/Q3 (match the stats table exactly)
        if iqr_mode and pm.size >= 1:
            q1r = float(np.percentile(pm.values, 25))
            q3r = float(np.percentile(pm.values, 75))
            medr = float(np.percentile(pm.values, 50))
            iqr_x += [i, i, None]
            iqr_y += [_floor(q1r), _floor(q3r), None]
            # Invisible hover-carrier at the median (no visible tick — the bar
            # already conveys the spread); hover gives the standardized stats.
            med_x.append(i); med_y.append(_floor(medr))
            med_t.append(f"<b>{a}</b><br>Historical IQR ({pm.size} plates):<br>"
                         f"Q1: {q1r:.1f}; Median: {medr:.1f}; Q3: {q3r:.1f}")
        elif not iqr_mode:
            for v in pm.values:
                pastdot_x.append(i); pastdot_y.append(_floor(v))
                pastdot_t.append(f"<b>{a}</b><br>Previous plate mean: {v:.1f}")
        if cur_groups is not None and a in cur_groups.groups:
            wells = cur_groups.get_group(a)["mfi"].dropna().astype(float).values
            if len(wells) == 0:
                continue
            m = float(np.mean(wells))
            reps = ", ".join(f"{v:.1f}" for v in wells)
            head = (f"<b>{a}</b><br>This plate — mean MFI: {m:.1f} "
                    f"(wells: {reps})")
            if q1r is not None and q3r is not None:
                if m > q3r:
                    pos = "above historical Q3"
                elif m < q1r:
                    pos = "below historical Q1"
                else:
                    pos = "within historical IQR"
                lbl = (f"{head}<br>Historical IQR: {q1r:.1f}–{q3r:.1f}<br>"
                       f"Position: {pos}")
                if q1r <= m <= q3r:
                    in_x.append(i); in_y.append(_floor(m)); in_t.append(lbl)
                else:
                    out_x.append(i); out_y.append(_floor(m)); out_t.append(lbl)
            else:
                neu_x.append(i); neu_y.append(_floor(m))
                neu_t.append(f"{head}<br>Historical IQR: not yet (need ≥ 3 plates)")

    # Colour-blind-safe palette (Okabe–Ito): neutral grey history, blue = within
    # IQR, vermillion + diamond shape = outside IQR (shape gives a non-colour cue).
    fig = go.Figure()
    if iqr_x:
        fig.add_trace(go.Scatter(
            x=iqr_x, y=iqr_y, mode="lines", line=dict(color=_CB_GREY, width=4),
            opacity=0.7, name="Previous plates IQR (Q1–Q3)", hoverinfo="skip"))
        # Invisible hover target over the bar — no visible median tick (the bar
        # conveys the spread); the standardized stats live in the hover.
        fig.add_trace(go.Scatter(
            x=med_x, y=med_y, mode="markers",
            marker=dict(size=14, color="rgba(0,0,0,0)"),
            name="Historical IQR", hovertext=med_t, hoverinfo="text", showlegend=False))
    if pastdot_x:
        fig.add_trace(go.Scatter(
            x=pastdot_x, y=pastdot_y, mode="markers",
            marker=dict(size=5, color=_CB_GREY, opacity=0.7),
            name="Previous plates (mean)", hovertext=pastdot_t, hoverinfo="text"))
    if in_x:
        fig.add_trace(go.Scatter(
            x=in_x, y=in_y, mode="markers", name="This plate (within IQR)",
            marker=dict(size=6, color=_CB_BLUE, line=dict(width=0.5, color="#04395e")),
            hovertext=in_t, hoverinfo="text"))
    if out_x:
        fig.add_trace(go.Scatter(
            x=out_x, y=out_y, mode="markers", name="This plate (outside IQR — review)",
            marker=dict(size=7, color=_CB_VERMILLION, symbol="diamond",
                        line=dict(width=0.5, color="#7a3500")),
            hovertext=out_t, hoverinfo="text"))
    if neu_x:
        fig.add_trace(go.Scatter(
            x=neu_x, y=neu_y, mode="markers", name="This plate (mean of wells)",
            marker=dict(size=6, color=_CB_BLUE, line=dict(width=0.5, color="#04395e")),
            hovertext=neu_t, hoverinfo="text"))

    n_an = len(order_keys)
    fig.update_layout(
        margin=dict(l=60, r=30, t=80, b=200), height=520,
        xaxis=dict(
            title="Antigen (panel order from xPONENT CSV header)",
            tickmode="array", tickvals=list(range(n_an)),
            ticktext=[(f"<i>{a}</i>" if a in excluded else a) for a in order_keys],
            tickangle=-90, tickfont=dict(size=6), showgrid=False, automargin=False),
        yaxis=dict(title=value_label, type="log", gridcolor="#eef1f4"),
        legend=dict(orientation="h", x=0, xanchor="left", y=1.06, yanchor="bottom",
                    bgcolor="rgba(255,255,255,0.85)", bordercolor="#d0d7de",
                    borderwidth=1, font=dict(size=10)),
    )
    return _plotly_html(fig, div_id, height=540)


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
    excluded: set[str] | None = None,
) -> tuple[list[dict], list[str]]:
    """Per-antigen cross-plate stats rows + the current-plate well columns.

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
    past = df[df["plate_id"] != current_plate_id]
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
        rows.append({
            "analyte": a,
            "excluded": a in excluded,
            "flag": flag,
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


def _control_qc_sections(
    hist: pd.DataFrame,
    antigens: list[str] | None,
    current_plate_id: str | None,
    excluded: set[str] | None,
    value_label: str,
    id_prefix: str,
) -> list[dict]:
    """Build one {control, plot_html, stats, well_cols, n_past_plates} block
    per control.

    ``hist`` must carry a ``control`` column (display label). Controls are
    rendered in sorted order; each gets a cross-plate overview + stats table.
    """
    if (hist is None or not isinstance(hist, pd.DataFrame) or hist.empty
            or "control" not in hist.columns):
        return []
    out = []
    controls = sorted(c for c in hist["control"].dropna().drop_duplicates())
    for idx, ctrl in enumerate(controls):
        sub = hist[hist["control"] == ctrl]
        plot = _cross_plate_mfi_overview(
            sub, antigens, current_plate_id, value_label, f"fig-{id_prefix}-{idx}", excluded)
        stats, well_cols = _format_control_stats(sub, antigens, current_plate_id, excluded)
        past = sub[sub["plate_id"] != current_plate_id]
        n_past = int(past["plate_id"].nunique()) if not past.empty else 0
        out.append({"control": ctrl, "plot_html": plot, "stats": stats,
                    "well_cols": well_cols, "n_past_plates": n_past})
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
# Distinct NC controls are coloured consistently; unknowns fall back to grey.
_NC_CTRL_PALETTE = ["#2c7fb8", "#d95f02", "#1b9e77", "#7570b3", "#e7298a"]


def _nc_control(sample_name: str) -> str:
    """Extract the NC control label (e.g. 'Negative 0', 'Negative 49')."""
    m = _NC_CTRL_RE.search(str(sample_name or ""))
    return m.group(1).replace("  ", " ").strip() if m else (str(sample_name or "NC").strip() or "NC")


def _nc_control_colors(controls: list[str]) -> dict:
    return {c: _NC_CTRL_PALETTE[i % len(_NC_CTRL_PALETTE)] for i, c in enumerate(controls)}


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
    a, b, c, d = params
    return f"a={_fmt(a, 1)}, b={_fmt(b, 2)}, c={_fmt(c, 1)}, d={_fmt(d, 1)}"


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
