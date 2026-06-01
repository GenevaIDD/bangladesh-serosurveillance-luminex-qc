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
from .qc_standard_curve import four_pl, range_problem_summary, select_pool_per_antigen
from .qc_beads import bead_problem_summary
from .qc_background import qc_background_levels


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
    output_path: Path | None = None,
    plate_order: list | None = None,
    config: dict | None = None,
    layout_info: dict | None = None,
    # ---- Legacy keyword-args, kept so older callers don't break. ----
    replicate_qc: dict | None = None,
    kit_controls: dict | None = None,
) -> Path:
    """Render the QC report HTML and write it to ``output_path``."""
    _reset_plotlyjs_embed_flag()
    config = config or {}
    excluded = set(get_excluded_analytes(config))
    qc_thresh = get_qc_thresholds(config) if config else {}
    rec_tol = qc_thresh.get("recovery_tolerance", RECOVERY_TOLERANCE)
    problem_frac = float(qc_thresh.get("problem_fraction_threshold", 0.20))
    bg_cv_thr = float(qc_thresh.get("bg_cv_threshold", 0.25))
    bg_max_thr = float(qc_thresh.get("bg_max_mfi", 100))

    pool_fits = _first_pool(fits)
    plate_id = metadata.get("plate_id", "unknown")

    # Multi-pool auto-selection summary, for the report's explanatory banner:
    # which control pools were detected, and how many antigens each pool was
    # chosen to calibrate (by pathogen-name match, tie-broken by best fit).
    pool_selection = _build_pool_selection_summary(fits, config)

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
    bg_overview_html = _make_background_overview_plot(
        history_background, current_plate_id=metadata.get("plate_id"), excluded=excluded
    )
    nc_history_html = _make_nc_history_plot(history_nc, current_plate_id=metadata.get("plate_id"))
    nc_history_present = bool(nc_history_html)
    curve_grid_html = _make_curve_grid(pool_fits, excluded)
    layout_info = layout_info or _derive_layout_info(data)
    current_box_ids = layout_info.get("box_ids") or []
    curve_picker_html = _make_curve_picker(
        pool_fits, excluded,
        in_range=in_range,
        history_specimens=history_specimens,
        history_fit=history_fit,
        current_plate_id=metadata.get("plate_id"),
        current_box_ids=current_box_ids,
    )
    cross_run_html = _make_cross_run_scatter(
        pool_fits, excluded,
        in_range=in_range,
        history_specimens=history_specimens,
        current_plate_id=metadata.get("plate_id"),
        current_box_ids=current_box_ids,
    )
    range_heatmap_html = _make_in_range_heatmap(in_range, excluded)
    nc_heatmap_html = _make_nc_heatmap(nc_levels, excluded)

    curve_summary = _build_curve_summary(pool_fits, pct_in_range, excluded, rec_tol)
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
    bg_levels = qc_background_levels(
        data,
        cv_threshold=bg_cv_thr,
        max_mfi_threshold=bg_max_thr,
        excluded_analytes=excluded,
    )

    base_dir = Path(__file__).parent.parent
    env = Environment(
        loader=FileSystemLoader(str(base_dir / "templates")),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("report.html")

    html = template.render(
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
        curve_picker_html=curve_picker_html,
        cross_run_html=cross_run_html,
        cross_run_present=bool(cross_run_html),
        range_heatmap_html=range_heatmap_html,
        range_problems=range_problems,
        nc_heatmap_html=nc_heatmap_html,
        nc_history_html=nc_history_html,
        nc_history_present=nc_history_present,
        nc_present=nc_present,
        n_nc_wells=n_nc_wells,
        bead_summary=_format_bead_summary(bead_summary),
        range_summary=_format_range_summary(range_summary),
        bg_levels=_format_bg_levels(bg_levels),
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
    output_path.write_text(html, encoding="utf-8")
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
            text[i, j] = (
                f"<b>{an}</b><br>Well: {w}<br>Sample: {label}<br>"
                f"Bead count: {count_str}<br>Tier: {tier_matrix.iat[i, j].upper()}"
            )

    # --- Geometry. Antigens (rows) stay frozen on the left; the wells
    # (columns) scroll horizontally. Both panes share the same per-row pixel
    # height + top/bottom margins so their rows line up, and they live in a
    # shared vertical-scroll container. ---
    n_rows = len(analyte_rows)
    n_well_cols = len(well_cols)
    ROW_PX = 10          # per-antigen row height (tight)
    COL_PX = 9           # per-well column width (tight)
    TOP, BOT = 60, 12    # identical on both panes → rows align
    # Frozen label pane: nearly all width is the left margin that holds the
    # antigen names; the (empty) data column is a thin sliver hugging the
    # heatmap, so there's almost no gap between the names and the cells.
    LABEL_MARGIN = 150   # px reserved for the antigen text
    label_w = LABEL_MARGIN + 8
    plot_h = TOP + n_rows * ROW_PX + BOT

    y_ticktext = [f"<i>{a} (excluded)</i>" if a in excluded else a for a in analyte_rows]

    # Right pane: the heatmap itself (y tick labels hidden — they live in the
    # frozen left pane). X axis = well location only; sample ID is in hover.
    heat = go.Figure(
        data=go.Heatmap(
            z=z, x=well_cols, y=analyte_rows, text=text, hoverinfo="text",
            colorscale=[
                [0.0, "#e74c3c"], [0.34, "#e74c3c"],
                [0.34, "#f1c40f"], [0.67, "#f1c40f"],
                [0.67, "#27ae60"], [1.0, "#27ae60"],
            ],
            zmin=0, zmax=2, showscale=False, xgap=0.5, ygap=0.5,
        )
    )
    heat.update_layout(
        margin=dict(l=2, r=16, t=TOP, b=BOT),
        width=2 + n_well_cols * COL_PX + 16, height=plot_h,
        plot_bgcolor="white",
        xaxis=dict(tickangle=-90, tickfont=dict(size=7), side="top",
                   tickmode="array", tickvals=list(range(n_well_cols)),
                   ticktext=[str(w) for w in well_cols]),
        yaxis=dict(showticklabels=False, autorange="reversed",
                   range=[n_rows - 0.5, -0.5]),
    )
    # Dotted separators between well-type groups (PC / Background / NC /
    # specimen) so groups are visually distinct across the wide matrix.
    if well_types:
        for idx, _left, _right in _group_boundaries(well_cols, well_types):
            heat.add_shape(
                type="line", xref="x", yref="paper",
                x0=idx - 0.5, x1=idx - 0.5, y0=0, y1=1.04,
                line=dict(color="#2c3e50", width=1.2, dash="dot"),
                opacity=0.7, layer="above",
            )

    # Left pane: frozen antigen labels only. Same height/margins/row order so
    # it stays row-aligned with the heatmap as the outer box scrolls vertically.
    labels = go.Figure(
        data=go.Heatmap(
            z=[[None]] * n_rows, x=[""], y=analyte_rows,
            showscale=False, hoverinfo="skip",
        )
    )
    labels.update_layout(
        margin=dict(l=LABEL_MARGIN, r=2, t=TOP, b=BOT),
        width=label_w, height=plot_h, plot_bgcolor="white",
        xaxis=dict(visible=False, fixedrange=True),
        yaxis=dict(side="left", tickfont=dict(size=7), autorange="reversed",
                   range=[n_rows - 0.5, -0.5], tickmode="array",
                   tickvals=list(range(n_rows)), ticktext=y_ticktext,
                   fixedrange=True),
    )

    labels_html = _plotly_html(labels, "fig-bead-labels", height=plot_h, responsive=False)
    heat_html = _plotly_html(heat, "fig-bead-heatmap", height=plot_h, responsive=False)

    # Outer box scrolls vertically (both panes together). The right pane
    # scrolls horizontally on its own; the left label pane stays frozen.
    return (
        '<div style="max-width:100%; max-height:680px; overflow-y:auto; '
        'border:1px solid #e1e4e8; border-radius:4px;">'
        '<div style="display:flex; flex-wrap:nowrap; align-items:flex-start;">'
        f'<div style="flex:0 0 auto;">{labels_html}</div>'
        f'<div style="flex:1 1 0; min-width:0; overflow-x:auto;">{heat_html}</div>'
        '</div></div>'
    )


def _make_curve_grid(pool_fits: dict, excluded: set[str], cols: int = 10) -> str:
    """Small-multiples grid of every 4PL fit, embedded as inline base64 PNG.

    Each panel: log-log scatter of the standard points + the fitted curve
    (when present). The panel title shows the analyte name, colour-coded:
        green   = fit_ok
        red     = fit failed
        grey    = soft-flagged / excluded
    Static image (matplotlib → PNG); the interactive picker below this
    grid is the place to drill into a single curve.
    """
    if not pool_fits:
        return "<p style='color:#999;'>No standard curve fits.</p>"

    analytes = list(pool_fits.keys())
    n = len(analytes)
    rows = (n + cols - 1) // cols

    panel_w = 1.6  # inches
    panel_h = 1.05
    fig, axes = plt.subplots(
        rows, cols,
        figsize=(cols * panel_w, rows * panel_h),
        squeeze=False,
    )

    for i, an in enumerate(analytes):
        r, c = divmod(i, cols)
        ax = axes[r][c]
        fit = pool_fits[an]
        std = fit.get("mean_data")
        params = fit.get("params")
        is_excluded = an in excluded
        if is_excluded:
            title_color = "#95a5a6"
        elif fit.get("fit_ok"):
            title_color = "#27ae60"
        else:
            title_color = "#e74c3c"

        if std is not None and not std.empty:
            ax.scatter(std["dilution"], std["mfi"], s=10, color="#2c3e50", zorder=3)
            if params is not None:
                xs = np.geomspace(std["dilution"].min(), std["dilution"].max(), 80)
                ys = four_pl(xs, *params)
                ax.plot(xs, ys, color="#3498db", linewidth=1.2)
            ax.set_xscale("log")
            ax.set_yscale("log")
        ax.tick_params(labelsize=5, length=2, pad=1)
        # Truncate long analyte names so titles don't overlap
        title = an if len(an) <= 20 else an[:18] + "…"
        ax.set_title(title, fontsize=6.5, color=title_color, pad=2)

    # Hide unused axes
    for j in range(n, rows * cols):
        r, c = divmod(j, cols)
        axes[r][c].axis("off")

    plt.tight_layout(pad=0.4, h_pad=0.6, w_pad=0.4)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return (
        f'<img src="data:image/png;base64,{b64}" '
        f'alt="All {n} standard curves" '
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
    STATUS_RUG_COLOR = {
        "BELOW_RANGE": "#4477AA",
        "IN_RANGE":    "#44AA99",
        "ABOVE_RANGE": "#EE7733",
        "NO_FIT":      "#CCBB44",
    }
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
    n_per_analyte = 2 * P + 6
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

    # Vertical separators between adjacent rug columns: one between
    # "This run" and the first past plate (heavier line so the
    # current vs past distinction reads at a glance), then one between
    # each pair of past plates.
    for col_boundary in range(P):
        is_first = col_boundary == 0
        fig.add_shape(
            type="line", xref="x2", yref="paper",
            x0=0.5 + col_boundary, x1=0.5 + col_boundary, y0=0, y1=1.05,
            line=dict(color="#d0d7de", width=1.6 if is_first else 0.8,
                      dash="dot" if is_first else "dot"),
            opacity=0.95 if is_first else 0.6,
            layer="above",
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
        lookup[an] = {"vis": vis, "title": title, "annotations": _rug_annotations(an)}

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


def _make_in_range_heatmap(in_range: pd.DataFrame, excluded: set[str]) -> str:
    if in_range is None or in_range.empty:
        return "<p style='color:#999;'>No in-range data.</p>"

    # Four-state classification with a colorblind-friendly diverging scheme:
    #   BELOW_RANGE = blue, ABOVE_RANGE = orange, IN_RANGE = pale neutral,
    #   NO_FIT = grey.  Avoids the red/green pair entirely.
    status_to_int = {"BELOW_RANGE": 0, "IN_RANGE": 1, "ABOVE_RANGE": 2, "NO_FIT": 3}
    pivot = in_range.pivot_table(
        index="analyte", columns="well", values="status", aggfunc="first",
    )
    analyte_order = list(in_range.drop_duplicates("analyte")["analyte"])
    well_order = list(in_range.drop_duplicates("well")["well"])
    pivot = pivot.reindex(index=analyte_order, columns=well_order)

    z = np.vectorize(lambda s: status_to_int.get(s, 3))(pivot.values)
    sample_labels = (
        in_range.drop_duplicates("well").set_index("well")["sample_name"].to_dict()
    )
    text = np.empty(z.shape, dtype=object)
    for i, an in enumerate(analyte_order):
        for j, w in enumerate(well_order):
            status = pivot.iat[i, j]
            text[i, j] = f"<b>{an}</b><br>Well {w} ({sample_labels.get(w, '')})<br>{status}"

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=[f"{w} {sample_labels.get(w, '')}".strip() for w in well_order],
            y=analyte_order,
            text=text,
            hoverinfo="text",
            colorscale=[
                # Colour-blind-safe palette (Paul Tol / Okabe-Ito).
                # Grey is intentionally avoided — it's reserved for the
                # cross-plate historical overlays in the curve picker.
                [0.00, "#4477AA"], [0.25, "#4477AA"],   # BELOW_RANGE — blue
                [0.25, "#44AA99"], [0.50, "#44AA99"],   # IN_RANGE — teal
                [0.50, "#EE7733"], [0.75, "#EE7733"],   # ABOVE_RANGE — orange
                [0.75, "#CCBB44"], [1.00, "#CCBB44"],   # NO_FIT — yellow
            ],
            zmin=0, zmax=3, showscale=False, xgap=0.5, ygap=0.5,
        )
    )
    height = max(400, min(20 + 14 * len(analyte_order), 4500))
    fig.update_layout(
        margin=dict(l=180, r=20, t=20, b=120),
        xaxis=dict(tickangle=-90, tickfont=dict(size=8), side="top"),
        yaxis=dict(tickfont=dict(size=8), autorange="reversed"),
    )
    if excluded:
        fig.update_yaxes(
            ticktext=[f"<i>{a} (excluded)</i>" if a in excluded else a for a in analyte_order],
            tickvals=list(range(len(analyte_order))),
        )
    return _plotly_html(fig, "fig-range-heatmap", height=height)


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


def _format_bg_levels(bg: pd.DataFrame) -> dict:
    if bg is None or bg.empty:
        return {"rows": [], "n_cv_flag": 0, "n_max_flag": 0, "present": False}
    rows = []
    for r in bg.itertuples(index=False):
        rows.append({
            "analyte": r.analyte,
            "n_wells": int(r.n_wells),
            "mean_mfi": _fmt(r.mean_mfi, 1),
            "sd_mfi": _fmt(r.sd_mfi, 1),
            "cv_pct": _fmt(r.cv * 100 if pd.notna(r.cv) else None, 1),
            "max_mfi": _fmt(r.max_mfi, 1),
            "cv_flag": bool(r.cv_flag),
            "max_flag": bool(r.max_flag),
            "excluded": bool(r.excluded),
        })
    return {
        "rows": rows,
        "n_cv_flag": int(bg["cv_flag"].sum()),
        "n_max_flag": int(bg["max_flag"].sum()),
        "present": True,
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


def _make_background_overview_plot(
    history_background: pd.DataFrame | None,
    current_plate_id: str | None = None,
    excluded: set[str] | None = None,
) -> str:
    """Scatter of mean Background MFI per antigen, coloured by plate.

    Antigens on the x-axis (sorted by max mean MFI across plates,
    descending — so the consistently-high antigens sit on the left).
    One trace per plate; the current plate is rendered with larger,
    fully opaque markers to draw the eye.

    Empty string when history is empty; caller hides the section.
    """
    if (history_background is None
            or not isinstance(history_background, pd.DataFrame)
            or history_background.empty
            or "mean_mfi" not in history_background.columns):
        return ""

    excluded = set(excluded or [])
    df = history_background.dropna(subset=["mean_mfi"]).copy()
    if df.empty:
        return ""

    # Antigen order = panel order from the most recently-processed
    # plate's xPONENT CSV header. Preserves the layout the user sees
    # on the instrument; no sorting by signal magnitude. Falls back to
    # first-seen order in history if the current plate isn't in the
    # frame yet.
    if current_plate_id and (df["plate_id"] == current_plate_id).any():
        ordered = df[df["plate_id"] == current_plate_id]["analyte"].drop_duplicates().tolist()
    else:
        ordered = df["analyte"].drop_duplicates().tolist()
    # Append any analytes that only show up on past plates, in their
    # first-seen order, so they still appear on the axis.
    all_analytes = df["analyte"].drop_duplicates().tolist()
    for a in all_analytes:
        if a not in ordered:
            ordered.append(a)
    order_keys = ordered
    an_index = {a: i for i, a in enumerate(order_keys)}

    # Plate order: chronological by run_date when available.
    if "run_date" in df.columns:
        rd_by_plate = (
            df.groupby("plate_id")["run_date"]
            .agg(lambda s: s.dropna().iloc[0] if s.dropna().size else "")
        )
        plates = sorted(rd_by_plate.index, key=lambda p: (rd_by_plate.get(p, ""), p))
    else:
        plates = sorted(df["plate_id"].dropna().astype(str).unique())

    fig = go.Figure()
    # Colour palette — Plotly Set2-ish, CB-friendly.
    palette = ["#4477AA", "#EE7733", "#44AA99", "#CCBB44",
               "#AA3377", "#66CCEE", "#7f8c8d", "#228833"]
    for i, plate in enumerate(plates):
        sub = df[df["plate_id"] == plate]
        if sub.empty:
            continue
        xs = [an_index[a] for a in sub["analyte"] if a in an_index]
        ys = [m for a, m in zip(sub["analyte"], sub["mean_mfi"]) if a in an_index]
        if not xs:
            continue
        is_current = (plate == current_plate_id)
        color = palette[i % len(palette)]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers",
            name=plate + (" (current)" if is_current else ""),
            marker=dict(
                size=6 if is_current else 5,
                color=color,
                opacity=0.95 if is_current else 0.55,
                line=dict(width=0.5, color="#2c3e50") if is_current else dict(width=0),
            ),
            customdata=list(zip(sub["analyte"], [plate] * len(sub))),
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Plate %{customdata[1]}<br>"
                "Mean Background MFI: %{y:.1f}<extra></extra>"
            ),
        ))

    n_an = len(order_keys)
    # Static, responsive figure — no explicit width, no scrollable
    # wrapper. With ~200 antigens the tick labels are tiny (6 pt)
    # rotated -90°; some adjacent labels will still touch but skipping
    # every Nth label hides information, so we accept it.
    fig.update_layout(
        margin=dict(l=60, r=30, t=80, b=200),
        height=560,
        xaxis=dict(
            title="Antigen (panel order from xPONENT CSV header)",
            tickmode="array",
            tickvals=list(range(n_an)),
            ticktext=[
                (f"<i>{a}</i>" if a in excluded else a) for a in order_keys
            ],
            tickangle=-90, tickfont=dict(size=6),
            showgrid=False,
            automargin=False,
        ),
        yaxis=dict(
            title="Mean Background MFI (log scale)",
            type="log",
            gridcolor="#eef1f4",
        ),
        # Horizontal legend along the top — keeps every pixel of the
        # main panel for the antigen ticks. Plates listed left → right.
        legend=dict(
            title=dict(text="Plate (click to toggle):",
                       font=dict(size=10, color="#7f8c8d")),
            orientation="h",
            x=0, xanchor="left", y=1.06, yanchor="bottom",
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#d0d7de", borderwidth=1,
            font=dict(size=10),
        ),
    )
    return _plotly_html(fig, "fig-bg-overview", height=580)


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


def _make_nc_history_plot(history_nc, current_plate_id: str | None = None) -> str:
    """Cross-plate NC MFI heatmap (plate rows × antigen columns).

    Empty / no-history → empty string (template hides the section).
    For each (plate, antigen) the value is the mean MFI across that
    plate's NC wells. Plates ordered by ``run_date`` when present.
    The current plate is highlighted with a `(current)` suffix.
    """
    if history_nc is None:
        return ""
    if isinstance(history_nc, pd.DataFrame):
        df = history_nc
    else:
        return ""
    if df.empty:
        return ""

    # Aggregate to (plate × analyte) — mean MFI across NC wells.
    agg = (
        df.groupby(["plate_id", "analyte"], sort=False)["mfi"]
        .mean()
        .reset_index()
    )
    if agg.empty:
        return ""

    plate_order = list(agg["plate_id"].drop_duplicates())
    if "run_date" in df.columns:
        # Sort plates chronologically when run_date is present.
        ranked = (
            df.groupby("plate_id")["run_date"]
            .agg(lambda s: s.dropna().iloc[0] if s.dropna().size else "")
            .sort_values()
        )
        if not ranked.empty:
            plate_order = [p for p in ranked.index if p in set(plate_order)]
    analyte_order = list(agg["analyte"].drop_duplicates())

    pivot = agg.pivot_table(
        index="plate_id", columns="analyte", values="mfi", aggfunc="mean",
    ).reindex(index=plate_order, columns=analyte_order)

    z = pivot.values.astype(float)
    text = np.empty(z.shape, dtype=object)
    for i, p in enumerate(plate_order):
        for j, an in enumerate(analyte_order):
            v = z[i, j]
            mfi_str = "—" if np.isnan(v) else f"{v:.0f}"
            text[i, j] = f"<b>{an}</b><br>Plate {p}<br>Mean NC MFI: {mfi_str}"

    y_labels = [
        f"{p} (current)" if p == current_plate_id else p for p in plate_order
    ]
    fig = go.Figure(
        data=go.Heatmap(
            z=z, x=analyte_order, y=y_labels,
            text=text, hoverinfo="text",
            colorscale="Purples",
            colorbar=dict(title="Mean MFI", thickness=12),
            xgap=0.5, ygap=2.0,
        )
    )
    height = max(220, 32 * len(plate_order) + 160)
    fig.update_layout(
        margin=dict(l=180, r=80, t=20, b=140),
        xaxis=dict(tickangle=-90, tickfont=dict(size=8), side="top"),
        yaxis=dict(tickfont=dict(size=10), autorange="reversed"),
    )
    return _plotly_html(fig, "fig-nc-history", height=height)


def _make_nc_heatmap(nc_levels: pd.DataFrame | None, excluded: set[str]) -> str:
    """Heatmap of NC well MFI per antigen.

    Empty plates return an empty string; the template renders an
    informational banner in that case.
    """
    if nc_levels is None or nc_levels.empty:
        return ""

    pivot = nc_levels.pivot_table(
        index="analyte", columns="well", values="mfi", aggfunc="mean",
    )
    analyte_order = list(nc_levels.drop_duplicates("analyte")["analyte"])
    well_order = list(nc_levels.drop_duplicates("well")["well"])
    pivot = pivot.reindex(index=analyte_order, columns=well_order)

    sample_labels = (
        nc_levels.drop_duplicates("well").set_index("well")["sample_name"].to_dict()
    )
    z = pivot.values.astype(float)
    text = np.empty(z.shape, dtype=object)
    for i, an in enumerate(analyte_order):
        for j, w in enumerate(well_order):
            v = z[i, j]
            mfi_str = "—" if np.isnan(v) else f"{v:.0f}"
            text[i, j] = (
                f"<b>{an}</b><br>Well {w} ({sample_labels.get(w, '')})<br>"
                f"MFI: {mfi_str}"
            )

    # MFI heatmap on a log scale-ish single-hue ramp. Higher MFI = darker
    # purple. NCs should be uniformly pale; any saturated cell is a flag
    # for the user to investigate.
    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=[f"{w} {sample_labels.get(w, '')}".strip() for w in well_order],
            y=analyte_order,
            text=text,
            hoverinfo="text",
            colorscale="Purples",
            colorbar=dict(title="MFI", thickness=12),
            xgap=0.5, ygap=0.5,
        )
    )
    height = max(400, min(20 + 14 * len(analyte_order), 4500))
    fig.update_layout(
        margin=dict(l=180, r=80, t=20, b=120),
        xaxis=dict(tickangle=-90, tickfont=dict(size=9), side="top"),
        yaxis=dict(tickfont=dict(size=8), autorange="reversed"),
    )
    if excluded:
        fig.update_yaxes(
            ticktext=[f"<i>{a} (excluded)</i>" if a in excluded else a for a in analyte_order],
            tickvals=list(range(len(analyte_order))),
        )
    return _plotly_html(fig, "fig-nc-heatmap", height=height)


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
