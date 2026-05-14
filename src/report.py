"""HTML report generation for the Uvira 200-plex Luminex QC tool.

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
5. IN/OUT-of-Range Matrix — antigens × specimens heatmap (binary
   green/red, grey for NO_FIT) plus the OUT_OF_RANGE problem list.
6. Downloads — links to per-plate CSV exports.

Excluded analytes (e.g. ``FLU_B_HA_Maryland_1959``) are kept in every
table but rendered visually muted (light grey) and listed in a banner.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless — never opens a window in the desktop app
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import APP_VERSION, RECOVERY_TOLERANCE
from .settings import get_excluded_analytes, get_qc_thresholds
from .qc_standard_curve import four_pl


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
    history_std: dict | pd.DataFrame | None,
    history_nc: pd.DataFrame | None,
    output_path: Path,
    plate_order: list | None = None,
    config: dict | None = None,
    layout_info: dict | None = None,
    # ---- Legacy keyword-args, kept so older callers don't break. ----
    replicate_qc: dict | None = None,
    nc_levels: pd.DataFrame | None = None,
    kit_controls: dict | None = None,
) -> Path:
    """Render the QC report HTML and write it to ``output_path``."""
    _reset_plotlyjs_embed_flag()
    config = config or {}
    excluded = set(get_excluded_analytes(config))
    qc_thresh = get_qc_thresholds(config) if config else {}
    rec_tol = qc_thresh.get("recovery_tolerance", RECOVERY_TOLERANCE)

    pool_fits = _first_pool(fits)
    plate_id = metadata.get("plate_id", "unknown")

    bead_heatmap_html = _make_bead_heatmap(bead_qc, excluded)
    curve_grid_html = _make_curve_grid(pool_fits, excluded)
    curve_picker_html = _make_curve_picker(pool_fits, excluded)
    range_heatmap_html = _make_in_range_heatmap(in_range, excluded)

    curve_summary = _build_curve_summary(pool_fits, pct_in_range, excluded, rec_tol)
    bead_problems = _format_problem_list(bead_qc.get("problems", pd.DataFrame()))
    range_problems = _format_range_problems(in_range, excluded)

    layout_info = layout_info or _derive_layout_info(data)

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
        bead_thresholds={
            "red_below": bead_qc.get("red_threshold"),
            "yellow_below": bead_qc.get("yellow_threshold"),
        },
        bead_heatmap_html=bead_heatmap_html,
        curve_grid_html=curve_grid_html,
        bead_problems=bead_problems,
        bead_problem_counts=_tier_counts(bead_qc.get("problems", pd.DataFrame())),
        curve_summary=curve_summary,
        curve_picker_html=curve_picker_html,
        range_heatmap_html=range_heatmap_html,
        range_problems=range_problems,
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


def _plotly_html(fig: go.Figure, div_id: str, height: int = 500) -> str:
    """Render a Plotly figure to an HTML <div>.

    The first call per report embeds the matching plotly.js inline so the
    report is fully self-contained (no internet required, no version
    skew between the JSON we emit and the runtime library). Subsequent
    calls reference the already-loaded library.
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
        config={"displaylogo": False, "responsive": True},
    )


def _reset_plotlyjs_embed_flag() -> None:
    """Reset the per-report inline-embed flag. Called once at the top of
    ``generate_report`` so successive calls each get a self-contained file."""
    global _plotlyjs_embedded
    _plotlyjs_embedded = False


def _make_bead_heatmap(bead_qc: dict, excluded: set[str]) -> str:
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
            label = sample_labels.get(w, "")
            count_str = "—" if pd.isna(count) else f"{int(count)}"
            text[i, j] = (
                f"<b>{an}</b><br>Well {w} ({label})<br>Count: {count_str}<br>"
                f"Tier: {tier_matrix.iat[i, j].upper()}"
            )

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=[f"{w} {sample_labels.get(w, '')}".strip() for w in well_cols],
            y=analyte_rows,
            text=text,
            hoverinfo="text",
            colorscale=[
                [0.0, "#e74c3c"], [0.34, "#e74c3c"],
                [0.34, "#f1c40f"], [0.67, "#f1c40f"],
                [0.67, "#27ae60"], [1.0, "#27ae60"],
            ],
            zmin=0, zmax=2, showscale=False, xgap=0.5, ygap=0.5,
        )
    )
    height = max(400, min(20 + 14 * len(analyte_rows), 4500))
    fig.update_layout(
        margin=dict(l=180, r=20, t=20, b=120),
        xaxis=dict(tickangle=-90, tickfont=dict(size=8), side="top"),
        yaxis=dict(tickfont=dict(size=8), autorange="reversed"),
    )
    if excluded:
        fig.update_yaxes(
            ticktext=[f"<i>{a} (excluded)</i>" if a in excluded else a for a in analyte_rows],
            tickvals=list(range(len(analyte_rows))),
        )
    return _plotly_html(fig, "fig-bead-heatmap", height=height)


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


def _make_curve_picker(pool_fits: dict, excluded: set[str]) -> str:
    """All 4PL curves rendered as visibility-toggled traces with a dropdown."""
    if not pool_fits:
        return "<p style='color:#999;'>No standard curve fits.</p>"

    analytes = list(pool_fits.keys())
    fig = go.Figure()
    n_per_analyte = 2  # points trace + curve trace

    for ai, an in enumerate(analytes):
        fit = pool_fits[an]
        std = fit.get("mean_data")
        if std is not None and not std.empty:
            fig.add_trace(go.Scatter(
                x=std["dilution"], y=std["mfi"], mode="markers", name="Standards",
                marker=dict(size=10, color="#2c3e50"),
                visible=(ai == 0),
            ))
        else:
            fig.add_trace(go.Scatter(x=[], y=[], mode="markers", visible=(ai == 0)))
        params = fit.get("params")
        if params is not None and std is not None and not std.empty:
            xs = np.geomspace(std["dilution"].min(), std["dilution"].max(), 80)
            ys = four_pl(xs, *params)
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines", name="4PL fit",
                line=dict(color="#3498db", width=2),
                visible=(ai == 0),
            ))
        else:
            fig.add_trace(go.Scatter(x=[], y=[], mode="lines", visible=(ai == 0)))

    n_traces = len(analytes) * n_per_analyte
    buttons = []
    for ai, an in enumerate(analytes):
        vis = [False] * n_traces
        vis[ai * n_per_analyte] = True
        vis[ai * n_per_analyte + 1] = True
        label = f"⚠ {an} (excluded)" if an in excluded else an
        fit = pool_fits[an]
        title = (
            f"<b>{label}</b> &nbsp;·&nbsp; "
            f"fit_ok={fit.get('fit_ok')} &nbsp;·&nbsp; "
            f"params={_fmt_params(fit.get('params'))}"
        )
        buttons.append(dict(
            label=label[:60],
            method="update",
            args=[{"visible": vis}, {"title.text": title}],
        ))

    first_label = ("⚠ " if analytes[0] in excluded else "") + analytes[0]
    first_fit = pool_fits[analytes[0]]
    fig.update_layout(
        title=dict(text=(
            f"<b>{first_label}</b> &nbsp;·&nbsp; "
            f"fit_ok={first_fit.get('fit_ok')} &nbsp;·&nbsp; "
            f"params={_fmt_params(first_fit.get('params'))}"
        )),
        xaxis=dict(type="log", title="Dilution factor (1 : x)"),
        yaxis=dict(type="log", title="MFI"),
        updatemenus=[dict(
            buttons=buttons, direction="down",
            x=0, xanchor="left", y=1.16, yanchor="top",
            showactive=True,
        )],
        margin=dict(l=70, r=30, t=110, b=60),
        height=500,
    )
    return _plotly_html(fig, "fig-curve-picker", height=540)


def _make_in_range_heatmap(in_range: pd.DataFrame, excluded: set[str]) -> str:
    if in_range is None or in_range.empty:
        return "<p style='color:#999;'>No in-range data.</p>"

    status_to_int = {"OUT_OF_RANGE": 0, "NO_FIT": 1, "IN_RANGE": 2}
    pivot = in_range.pivot_table(
        index="analyte", columns="well", values="status", aggfunc="first",
    )
    analyte_order = list(in_range.drop_duplicates("analyte")["analyte"])
    well_order = list(in_range.drop_duplicates("well")["well"])
    pivot = pivot.reindex(index=analyte_order, columns=well_order)

    z = np.vectorize(lambda s: status_to_int.get(s, 1))(pivot.values)
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
                [0.0, "#e74c3c"], [0.34, "#e74c3c"],
                [0.34, "#bdc3c7"], [0.67, "#bdc3c7"],
                [0.67, "#27ae60"], [1.0, "#27ae60"],
            ],
            zmin=0, zmax=2, showscale=False, xgap=0.5, ygap=0.5,
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
    out = in_range[in_range["status"] == "OUT_OF_RANGE"]
    rows = []
    for r in out.itertuples(index=False):
        rows.append({
            "well": r.well,
            "sample_name": r.sample_name,
            "analyte": r.analyte,
            "mfi": _fmt(r.mfi, 1),
            "mfi_lloq": _fmt(r.mfi_lloq, 1),
            "mfi_uloq": _fmt(r.mfi_uloq, 1),
            "excluded": r.analyte in excluded,
        })
    return rows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_pool(fits: dict | None) -> dict:
    if not fits:
        return {}
    pools = list(fits.keys())
    return fits[pools[0]] if pools else {}


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
