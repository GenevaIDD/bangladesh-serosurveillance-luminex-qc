"""4-parameter logistic (4PL) curve fitting for PC standard curves."""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

from .config import ANTIGENS, RECOVERY_TOLERANCE
from .settings import get_antigen_names, get_qc_thresholds, load_config


def four_pl(x, a, b, c, d):
    """4PL model: y = d + (a - d) / (1 + (x / c)^b)

    Parameters:
        a: minimum asymptote (response at infinite concentration)
        b: Hill slope
        c: inflection point (IC50)
        d: maximum asymptote (response at zero concentration)
    """
    return d + (a - d) / (1.0 + (x / c) ** b)


def invert_4pl(y, a, b, c, d):
    """Invert the 4PL to get x (dilution) from y (MFI).

    Returns NaN if the value is outside the curve range.
    """
    y = np.asarray(y, dtype=float)
    ratio = (a - d) / (y - d) - 1.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # ratio must be positive for real-valued result
        valid = ratio > 0
        result = np.full_like(y, np.nan)
        result[valid] = c * ratio[valid] ** (1.0 / b)
    return result


def fit_standard_curves(
    df: pd.DataFrame,
    config: dict | None = None,
    antigens: list[str] | None = None,
) -> dict:
    """Fit 4PL curves to PC standard data for each antigen, per pool.

    Args:
        df: DataFrame with columns [well, sample_name, analyte, mfi, well_type, dilution]
            and optionally `pc_pool`.
        config: optional config dict (from settings.load_config)
        antigens: optional list of analytes to fit. If None, derived from
            ``config['panel']['antigens']``. Pass the per-plate panel
            (from ``metadata['analytes']``) to fit only the analytes
            actually present in the CSV.

    Returns dict keyed by pool name, each value is a dict keyed by analyte:
        {"PC": {analyte: {params, fit_ok, std_data, ...}}}

    On Uvira plates a single pool ("PC") is always returned.
    """
    if config is None:
        config = load_config()
    if antigens is None:
        antigens = get_antigen_names(config)
    recovery_tolerance = get_qc_thresholds(config).get("recovery_tolerance", RECOVERY_TOLERANCE)
    drop_outlier = get_qc_thresholds(config).get("drop_outlier", True)

    pc = df[df["well_type"] == "pc"].copy()

    # Discover pools; fall back to a single unnamed pool if pc_pool column missing
    if "pc_pool" in pc.columns:
        pools = sorted(pc["pc_pool"].dropna().unique())
    else:
        pools = ["PC"]

    if not pools:
        # No PC wells at all — return empty structure
        return {"PC": {a: {"params": None, "fit_ok": False, "std_data": pd.DataFrame(),
                           "mean_data": pd.DataFrame(), "error": "No PC data",
                           "qc_warnings": [], "obs_exp": None,
                           "reportable_range": None, "dropped_point": None}
                       for a in antigens}}

    all_fits = {}
    for pool in pools:
        if "pc_pool" in pc.columns:
            pool_data = pc[pc["pc_pool"] == pool]
        else:
            pool_data = pc

        pool_results = {}
        for analyte in antigens:
            adata = pool_data[pool_data["analyte"] == analyte].copy()
            if adata.empty:
                pool_results[analyte] = {
                    "params": None, "fit_ok": False, "std_data": adata,
                    "mean_data": pd.DataFrame(), "error": "No PC data",
                    "qc_warnings": [], "obs_exp": None,
                    "reportable_range": None, "dropped_point": None,
                }
                continue

            # Average replicates at each dilution
            means = adata.groupby("dilution")["mfi"].mean().reset_index()
            means = means.sort_values("dilution")

            x = means["dilution"].values
            y = means["mfi"].values

            params, fit_ok, error, qc_warnings = _fit_one(x, y, x_min=x.min(), x_max=x.max())

            dropped_point = None

            # Try dropping one outlier if enabled and fit failed *because of
            # QC criteria* (not because the input was degenerate). When
            # params is None the curve either had no signal or scipy
            # didn't converge; dropping a point won't rescue it.
            if drop_outlier and params is not None and not fit_ok and len(x) >= 6:
                best = _try_drop_one_outlier(x, y, x_min=x.min(), x_max=x.max())
                if best is not None:
                    params, fit_ok, error, qc_warnings, drop_idx = best
                    dropped_point = {"dilution": x[drop_idx], "mfi": y[drop_idx], "index": int(drop_idx)}
                    keep = np.ones(len(x), dtype=bool)
                    keep[drop_idx] = False
                    means = means.iloc[keep].reset_index(drop=True)
                    x = means["dilution"].values
                    y = means["mfi"].values

            obs_exp = None
            reportable_range = None
            if params is not None:
                obs_exp = _compute_obs_exp(x, y, params, tolerance=recovery_tolerance)
                reportable_range = _compute_reportable_range(x, y, params, tolerance=recovery_tolerance)

            pool_results[analyte] = {
                "params": params,
                "fit_ok": fit_ok,
                "std_data": adata,
                "mean_data": means,
                "error": error,
                "qc_warnings": qc_warnings,
                "obs_exp": obs_exp,
                "reportable_range": reportable_range,
                "dropped_point": dropped_point,
            }

        all_fits[pool] = pool_results

    return all_fits


def _fit_one(x, y, x_min=None, x_max=None):
    """Fit 4PL to a single analyte's standard curve.

    Returns (params, fit_ok, error, warnings) where:
    - params: (a, b, c, d) tuple or None
    - fit_ok: True only if fit converges AND passes quality checks
    - error: error message if fit failed or quality check failed
    - warnings: list of quality warnings (may be non-empty even if fit_ok)
    """
    # Bail out fast on degenerate input. With ~200 antigens per plate,
    # a few will be all-zero noise (e.g. excluded bead regions); without
    # this guard scipy.curve_fit thrashes for the full maxfev budget.
    y_arr = np.asarray(y, dtype=float)
    y_max = float(np.nanmax(y_arr)) if y_arr.size else 0.0
    y_min = float(np.nanmin(y_arr)) if y_arr.size else 0.0
    if not np.isfinite(y_max) or y_max <= 0:
        return None, False, "All-zero / non-finite MFI — no signal", []
    if y_max < 50:  # well below typical noise floor for IgG MFI
        return None, False, f"Signal floor (max MFI {y_max:.0f} < 50) — no curve", []
    # Dynamic-range pre-check: 4PL needs at least ~3× separation to fit
    if y_min > 0 and (y_max / max(y_min, 1.0)) < 2.0:
        return None, False, f"Flat response (max/min ratio {y_max / max(y_min, 1.0):.1f}x)", []

    # Initial guesses. For descending dilution series:
    #   y = d + (a - d) / (1 + (x/c)^b)
    # At x → 0  (low dilution / high antigen): y → a   (upper plateau)
    # At x → ∞ (high dilution / no antigen):   y → d   (lower plateau / noise floor)
    a_init = y_max  # upper plateau
    d_init = y_min  # lower plateau / noise floor
    c_init = float(np.median(x))  # inflection point (IC50)
    b_init = 1.0  # Hill slope

    p0 = [a_init, b_init, c_init, d_init]
    bounds = (
        [0, 0.1, 1, 0],            # lower bounds (a, b, c, d)
        [np.inf, 10, 1e6, np.inf]  # upper bounds
    )

    # Fit on log10(MFI) so that the noise floor and the high-signal upper
    # plateau contribute comparably to the residuals. A linear-residual
    # fit lets the upper plateau (~10⁵ MFI) dominate, so the optimizer
    # ignores points at the tail (~10² MFI) and lands at d=0 instead of
    # the true noise floor (~10²). Log-residual fitting is the standard
    # immunoassay approach and gives a sensible lower plateau.
    Y_FLOOR = 1.0  # MFI floor to keep log defined for occasional zeros
    log_y = np.log10(np.maximum(y, Y_FLOOR))

    def _four_pl_log(xx, a_, b_, c_, d_):
        return np.log10(np.maximum(four_pl(xx, a_, b_, c_, d_), Y_FLOOR))

    try:
        popt, _ = curve_fit(
            _four_pl_log, x, log_y, p0=p0, bounds=bounds, maxfev=10000
        )
    except Exception as e:
        return None, False, str(e), []

    a, b, c, d = popt

    # --- Fit quality checks ---
    qc_warnings = []

    # 1. R² (goodness of fit) — computed in log space, matching the
    # objective the optimizer actually minimized.
    log_y_pred = _four_pl_log(x, *popt)
    ss_res = np.sum((log_y - log_y_pred) ** 2)
    ss_tot = np.sum((log_y - np.mean(log_y)) ** 2)
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    if r_squared < 0.95:
        qc_warnings.append(f"R²={r_squared:.3f} (< 0.95, log scale)")

    # 2. IC50 within the tested dilution range (with some margin)
    ic50_lo = (x_min or x.min()) / 3.0
    ic50_hi = (x_max or x.max()) * 3.0
    if c < ic50_lo or c > ic50_hi:
        qc_warnings.append(f"IC50={c:.1f} outside range [{ic50_lo:.0f}, {ic50_hi:.0f}]")

    # 3. Hill slope in reasonable range
    if b < 0.3 or b > 5.0:
        qc_warnings.append(f"Hill slope={b:.2f} outside range [0.3, 5.0]")

    # 4. Dynamic range (ratio of upper to lower asymptote)
    upper = max(a, d)
    lower = max(min(a, d), 1.0)  # floor at 1 to avoid division by zero
    dynamic_range = upper / lower
    if dynamic_range < 3.0:
        qc_warnings.append(f"Dynamic range={dynamic_range:.1f}x (< 3x)")

    fit_ok = len(qc_warnings) == 0
    error = "; ".join(qc_warnings) if qc_warnings else None

    return tuple(popt), fit_ok, error, qc_warnings


def _try_drop_one_outlier(x, y, x_min=None, x_max=None):
    """Try dropping each point one at a time to see if fit improves.

    Returns (params, fit_ok, error, qc_warnings, drop_idx) for the best
    single-point removal, or None if no single removal produces a passing fit.
    If multiple removals pass, pick the one with highest R².
    """
    n = len(x)
    best_result = None
    best_r2 = -np.inf

    for i in range(n):
        mask = np.ones(n, dtype=bool)
        mask[i] = False
        x_sub = x[mask]
        y_sub = y[mask]

        params, fit_ok, error, qc_warnings = _fit_one(
            x_sub, y_sub, x_min=x_min, x_max=x_max
        )

        if params is not None and fit_ok:
            # Compute R² in log space, matching the optimizer's objective.
            log_y_sub = np.log10(np.maximum(y_sub, 1.0))
            log_pred = np.log10(np.maximum(four_pl(x_sub, *params), 1.0))
            ss_res = np.sum((log_y_sub - log_pred) ** 2)
            ss_tot = np.sum((log_y_sub - np.mean(log_y_sub)) ** 2)
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

            if r2 > best_r2:
                best_r2 = r2
                # Add note about which point was dropped
                drop_note = f"Dropped 1 outlier (1:{x[i]:.0f}, MFI={y[i]:.0f})"
                if qc_warnings:
                    qc_warnings = qc_warnings + [drop_note]
                else:
                    qc_warnings = [drop_note]
                best_result = (params, fit_ok, error, qc_warnings, i)

    return best_result


def _compute_obs_exp(x_expected, y_observed, params, tolerance=0.30):
    """Backcalculate concentrations from MFI and compute Obs/Exp recovery %.

    For each standard point, invert the 4PL to get the "observed" dilution
    from the measured MFI, then compare to the expected (known) dilution.

    Returns a list of dicts with keys: dilution, mfi, obs_dilution, recovery_pct, in_range.
    """
    lo = (1.0 - tolerance) * 100.0
    hi = (1.0 + tolerance) * 100.0
    a, b, c, d = params
    obs_dilution = invert_4pl(y_observed, a, b, c, d)
    results = []
    for i in range(len(x_expected)):
        expected = x_expected[i]
        observed = obs_dilution[i]
        if np.isnan(observed) or expected == 0:
            recovery = np.nan
        else:
            recovery = (observed / expected) * 100.0
        in_range = not np.isnan(recovery) and lo <= recovery <= hi
        results.append({
            "dilution": expected,
            "mfi": y_observed[i],
            "obs_dilution": observed if not np.isnan(observed) else None,
            "recovery_pct": round(recovery, 1) if not np.isnan(recovery) else None,
            "in_range": in_range,
        })
    return results


def _compute_reportable_range(x, y, params, tolerance=0.30):
    """Determine the reportable range (LLOQ to ULOQ) based on Obs/Exp recovery.

    The reportable range is the dilution range where backcalculated recovery
    is within ±tolerance of the expected value.

    Returns dict with lloq, uloq (as AU values using the same anchor scale),
    lloq_dilution, uloq_dilution.
    """
    AU_ANCHOR = 1000.0
    a, b, c, d = params
    obs_exp = _compute_obs_exp(x, y, params, tolerance=tolerance)

    # Find dilutions where recovery is within range
    valid_dilutions = [
        r["dilution"] for r in obs_exp
        if r["recovery_pct"] is not None and (100 - tolerance * 100) <= r["recovery_pct"] <= (100 + tolerance * 100)
    ]

    if not valid_dilutions:
        return {"lloq": None, "uloq": None, "lloq_dilution": None, "uloq_dilution": None}

    # First dilution used in the standard curve (for AU scaling)
    first_dilution = min(x) if len(x) > 0 else 1.0

    lloq_dilution = max(valid_dilutions)  # highest dilution = lowest AU = LLOQ
    uloq_dilution = min(valid_dilutions)  # lowest dilution = highest AU = ULOQ

    return {
        "lloq": (first_dilution / lloq_dilution) * AU_ANCHOR if lloq_dilution > 0 else None,
        "uloq": (first_dilution / uloq_dilution) * AU_ANCHOR if uloq_dilution > 0 else None,
        "lloq_dilution": lloq_dilution,
        "uloq_dilution": uloq_dilution,
    }


def _pool_slug(pool_name: str) -> str:
    """Convert pool name to a safe column suffix, e.g. 'ITM PC2' → 'ITM_PC2'."""
    return pool_name.replace(" ", "_")


def compute_concentrations(df: pd.DataFrame, fits: dict) -> pd.DataFrame:
    """Apply 4PL inversion to compute AU (Arbitrary Units) for specimen wells.

    The AU scale is anchored so that the first (lowest) standard dilution
    equals 1000 AU.  For example, if the standard starts at 1:100 then a
    specimen whose interpolated dilution equiv is 100 gets AU = 1000, one at
    300 gets AU ≈ 333, and one at 72900 gets AU ≈ 1.37.

    Formula:  AU = (first_dilution / dilution_equiv) * 1000

    Args:
        df: full DataFrame with well_type column
        fits: dict[pool_name -> dict[analyte -> fit_result]]

    When only one pool is present, columns are named 'rau', 'extrapolated',
    'below_lloq', 'above_uloq' (backward compatible).
    When multiple pools are present, per-pool columns are added:
    'rau_{slug}', 'extrapolated_{slug}', 'below_lloq_{slug}', 'above_uloq_{slug}'
    plus 'rau' etc. as copies of the first pool (default).
    """
    AU_ANCHOR = 1000.0

    specimens = df[df["well_type"] == "specimen"].copy()

    pools = list(fits.keys())
    multi_pool = len(pools) > 1

    for pool_name in pools:
        pool_fits = fits[pool_name]
        slug = _pool_slug(pool_name)

        # Column names: per-pool when multi, plain when single
        rau_col = f"rau_{slug}" if multi_pool else "rau"
        extrap_col = f"extrapolated_{slug}" if multi_pool else "extrapolated"
        lloq_col = f"below_lloq_{slug}" if multi_pool else "below_lloq"
        uloq_col = f"above_uloq_{slug}" if multi_pool else "above_uloq"

        specimens[rau_col] = np.nan
        specimens[extrap_col] = False
        specimens[lloq_col] = False
        specimens[uloq_col] = False

        for analyte, fit_result in pool_fits.items():
            if fit_result.get("params") is None:
                continue
            a, b, c, d = fit_result["params"]
            mask = specimens["analyte"] == analyte
            mfi_vals = specimens.loc[mask, "mfi"].values
            dilution_equiv = invert_4pl(mfi_vals, a, b, c, d)

            std_data = fit_result.get("mean_data")
            if std_data is not None and not std_data.empty:
                first_dilution = std_data["dilution"].min()
            else:
                first_dilution = 1.0

            rau_vals = (first_dilution / dilution_equiv) * AU_ANCHOR
            specimens.loc[mask, rau_col] = rau_vals

            if std_data is not None and not std_data.empty:
                mfi_lo = std_data["mfi"].min()
                mfi_hi = std_data["mfi"].max()
                specimens.loc[mask, extrap_col] = (mfi_vals < mfi_lo) | (mfi_vals > mfi_hi)

            rr = fit_result.get("reportable_range")
            if rr and rr["lloq"] is not None and rr["uloq"] is not None:
                specimens.loc[mask, lloq_col] = rau_vals < rr["lloq"]
                specimens.loc[mask, uloq_col] = rau_vals > rr["uloq"]

    # For multi-pool: also set the plain 'rau' etc. from the first pool as default
    if multi_pool:
        first_slug = _pool_slug(pools[0])
        specimens["rau"] = specimens[f"rau_{first_slug}"]
        specimens["extrapolated"] = specimens[f"extrapolated_{first_slug}"]
        specimens["below_lloq"] = specimens[f"below_lloq_{first_slug}"]
        specimens["above_uloq"] = specimens[f"above_uloq_{first_slug}"]

    return specimens


def compute_net_mfi(df: pd.DataFrame) -> pd.DataFrame:
    """Add net_mfi column: analyte MFI minus same-well NC bead MFI, floored at 0.

    The NC bead in each well captures non-specific binding. Subtracting it
    gives a background-corrected signal. Only applied to specimen wells.
    """
    # Mean NC bead MFI per well (NC bead analyte name is "NC")
    nc_mfi_by_well = (
        df[df["analyte"] == "NC"]
        .groupby("well")["mfi"]
        .mean()
        .rename("nc_mfi_well")
    )

    result = df.copy()
    result["net_mfi"] = np.nan

    spec_mask = result["well_type"] == "specimen"
    if spec_mask.any():
        result = result.join(nc_mfi_by_well, on="well")
        nc_col = result["nc_mfi_well"].fillna(0.0)
        net = result.loc[spec_mask, "mfi"] - nc_col[spec_mask]
        result.loc[spec_mask, "net_mfi"] = net.clip(lower=0.0)
        result = result.drop(columns=["nc_mfi_well"])

    return result


# ---------------------------------------------------------------------------
# Section 3 — per-(antigen × sample) range table & summary metric.
# A specimen MFI is "in range" if it falls between the LLOQ MFI and ULOQ
# MFI of that antigen's standard curve.  Out-of-range specimens are split
# into BELOW_RANGE (MFI < LLOQ-MFI) and ABOVE_RANGE (MFI > ULOQ-MFI) so
# users can tell which tail of the curve they're falling off.
# ---------------------------------------------------------------------------


def _mfi_bounds_for_fit(fit_result: dict) -> tuple[float | None, float | None]:
    """Return (mfi_lloq, mfi_uloq) for an antigen's fit, or (None, None).

    LLOQ corresponds to the highest dilution that passed Obs/Exp recovery
    (lowest MFI in the reportable range); ULOQ corresponds to the lowest
    dilution (highest MFI). Bounds are evaluated by passing those
    dilutions through the fitted 4PL.
    """
    if fit_result.get("params") is None:
        return None, None
    rr = fit_result.get("reportable_range") or {}
    lloq_d = rr.get("lloq_dilution")
    uloq_d = rr.get("uloq_dilution")
    if lloq_d is None or uloq_d is None:
        return None, None
    a, b, c, d = fit_result["params"]
    mfi_lloq = float(four_pl(np.array([float(lloq_d)]), a, b, c, d)[0])
    mfi_uloq = float(four_pl(np.array([float(uloq_d)]), a, b, c, d)[0])
    # Defensive: ensure ordering (lower MFI bound first)
    lo, hi = sorted((mfi_lloq, mfi_uloq))
    return lo, hi


def compute_in_range_table(
    df: pd.DataFrame,
    fits: dict,
    excluded_analytes: list[str] | None = None,
) -> pd.DataFrame:
    """Per-(specimen well × antigen) IN_RANGE / OUT_OF_RANGE table.

    Args:
        df: long-format data with columns [well, sample_name, analyte, mfi, well_type]
            and optionally [sample_id, patient_id, barcode].
        fits: dict[pool -> dict[analyte -> fit_result]] from fit_standard_curves
        excluded_analytes: analyte names to soft-flag (kept in output, with
            ``excluded=True``). Defaults to empty.

    Returns DataFrame with columns:
        well, sample_name, analyte, mfi, mfi_lloq, mfi_uloq, status, excluded

    Where ``status`` ∈ {"IN_RANGE", "BELOW_RANGE", "ABOVE_RANGE",
    "NO_FIT"}. NO_FIT occurs when the antigen's standard curve had no
    usable reportable range; BELOW_RANGE means the specimen MFI is
    under the LLOQ-MFI; ABOVE_RANGE means it sits above the ULOQ-MFI.
    Optional sample-id columns (``sample_id``, ``patient_id``,
    ``barcode``, ``box_id``) are forwarded when present in ``df``.
    """
    excluded = set(excluded_analytes or [])
    pools = list(fits.keys())
    if not pools:
        return pd.DataFrame(
            columns=["well", "sample_name", "analyte", "mfi", "mfi_lloq",
                     "mfi_uloq", "status", "excluded"]
        )
    # Single-pool assumption for Uvira; if multi-pool present (legacy),
    # use the first pool.
    pool_fits = fits[pools[0]]

    specimens = df[df["well_type"] == "specimen"].copy()
    if specimens.empty:
        return specimens.assign(
            mfi_lloq=np.nan, mfi_uloq=np.nan, status="", excluded=False
        )[["well", "sample_name", "analyte", "mfi", "mfi_lloq", "mfi_uloq",
           "status", "excluded"]]

    # Pre-compute MFI bounds per analyte
    bounds: dict[str, tuple[float | None, float | None]] = {
        analyte: _mfi_bounds_for_fit(fit) for analyte, fit in pool_fits.items()
    }

    rows = []
    optional_cols = [c for c in ("sample_id", "patient_id", "barcode", "box_id")
                     if c in specimens.columns]
    for r in specimens.itertuples(index=False):
        analyte = r.analyte
        mfi = float(r.mfi) if pd.notna(r.mfi) else np.nan
        lo, hi = bounds.get(analyte, (None, None))
        if lo is None or hi is None or np.isnan(mfi):
            status = "NO_FIT"
        elif mfi < lo:
            status = "BELOW_RANGE"
        elif mfi > hi:
            status = "ABOVE_RANGE"
        else:
            status = "IN_RANGE"
        row = {
            "well": r.well,
            "sample_name": r.sample_name,
            "analyte": analyte,
            "mfi": mfi,
            "mfi_lloq": lo if lo is not None else np.nan,
            "mfi_uloq": hi if hi is not None else np.nan,
            "status": status,
            "excluded": analyte in excluded,
        }
        for c in optional_cols:
            row[c] = getattr(r, c)
        rows.append(row)
    return pd.DataFrame(rows)


def compute_pct_in_range_per_antigen(
    in_range: pd.DataFrame,
    excluded_analytes: list[str] | None = None,
) -> pd.DataFrame:
    """Summarize the IN/OUT table to one row per antigen.

    Returns DataFrame with columns:
        analyte, n_samples, n_in_range, n_below_range, n_above_range,
        n_no_fit, pct_in_range, excluded

    ``pct_in_range`` is ``n_in_range / n_samples * 100`` (0 if no
    samples). NO_FIT samples are counted in ``n_samples`` denominator.
    Excluded analytes are still tabulated; the report layer mutes them.
    """
    excluded = set(excluded_analytes or [])
    cols = [
        "analyte", "n_samples", "n_in_range", "n_below_range",
        "n_above_range", "n_no_fit", "pct_in_range", "excluded",
    ]
    if in_range.empty:
        return pd.DataFrame(columns=cols)

    grouped = in_range.groupby("analyte", sort=False)["status"].value_counts().unstack(fill_value=0)
    for col in ("IN_RANGE", "BELOW_RANGE", "ABOVE_RANGE", "NO_FIT"):
        if col not in grouped.columns:
            grouped[col] = 0
    summary = pd.DataFrame({
        "analyte": grouped.index,
        "n_in_range": grouped["IN_RANGE"].astype(int).values,
        "n_below_range": grouped["BELOW_RANGE"].astype(int).values,
        "n_above_range": grouped["ABOVE_RANGE"].astype(int).values,
        "n_no_fit": grouped["NO_FIT"].astype(int).values,
    }).reset_index(drop=True)
    summary["n_samples"] = (
        summary["n_in_range"]
        + summary["n_below_range"]
        + summary["n_above_range"]
        + summary["n_no_fit"]
    )
    summary["pct_in_range"] = np.where(
        summary["n_samples"] > 0,
        100.0 * summary["n_in_range"] / summary["n_samples"],
        0.0,
    ).round(1)
    summary["excluded"] = summary["analyte"].isin(excluded)
    return summary[cols]


def range_problem_summary(
    in_range: pd.DataFrame,
    fraction_threshold: float = 0.20,
    excluded_analytes: list[str] | None = None,
) -> dict:
    """Per-antigen / per-sample summary of BELOW_RANGE and ABOVE_RANGE.

    An antigen is "below-range problem" when ≥ ``fraction_threshold`` of
    its specimens are BELOW_RANGE; same logic for above-range. Samples
    are evaluated against their antigen-level results (NO_FIT cells are
    counted in the denominator).

    Returns dict with:
        antigen_summary: one row per analyte with n_below / n_above /
            frac_below / frac_above / below_flag / above_flag /
            problem_wells_below / problem_wells_above / excluded.
        sample_summary: one row per specimen well with n_below /
            n_above / frac_below / frac_above / below_flag /
            above_flag / problem_analytes_below / problem_analytes_above.
        n_below_antigens / n_above_antigens / n_below_samples /
            n_above_samples: scalar counts.
        threshold: the fraction used.
    """
    excluded = set(excluded_analytes or [])
    empty = pd.DataFrame()
    base = {
        "antigen_summary": empty, "sample_summary": empty,
        "n_below_antigens": 0, "n_above_antigens": 0,
        "n_below_samples": 0, "n_above_samples": 0,
        "threshold": fraction_threshold,
    }
    if in_range is None or in_range.empty:
        return base

    # Per antigen
    ag = (
        in_range.groupby("analyte", sort=False)
        .agg(
            n_samples=("well", "nunique"),
            n_below=("status", lambda s: int((s == "BELOW_RANGE").sum())),
            n_above=("status", lambda s: int((s == "ABOVE_RANGE").sum())),
        )
        .reset_index()
    )
    ag["frac_below"] = (ag["n_below"] / ag["n_samples"]).round(4)
    ag["frac_above"] = (ag["n_above"] / ag["n_samples"]).round(4)
    ag["below_flag"] = ag["frac_below"] >= fraction_threshold
    ag["above_flag"] = ag["frac_above"] >= fraction_threshold
    ag["excluded"] = ag["analyte"].isin(excluded)

    # Detail strings ("FD123 (B1);FD124 (B2);…") per analyte
    detail_below: dict[str, list[str]] = {}
    detail_above: dict[str, list[str]] = {}
    for r in in_range.itertuples(index=False):
        if r.status == "BELOW_RANGE":
            detail_below.setdefault(r.analyte, []).append(
                f"{getattr(r, 'sample_name', '')} ({r.well})".strip()
            )
        elif r.status == "ABOVE_RANGE":
            detail_above.setdefault(r.analyte, []).append(
                f"{getattr(r, 'sample_name', '')} ({r.well})".strip()
            )
    ag["problem_samples_below"] = ag["analyte"].map(lambda a: ";".join(detail_below.get(a, [])))
    ag["problem_samples_above"] = ag["analyte"].map(lambda a: ";".join(detail_above.get(a, [])))

    # Per sample (well)
    sm = (
        in_range.groupby(["well"], sort=False)
        .agg(
            sample_name=("sample_name", "first"),
            n_analytes=("analyte", "nunique"),
            n_below=("status", lambda s: int((s == "BELOW_RANGE").sum())),
            n_above=("status", lambda s: int((s == "ABOVE_RANGE").sum())),
        )
        .reset_index()
    )
    sm["frac_below"] = (sm["n_below"] / sm["n_analytes"]).round(4)
    sm["frac_above"] = (sm["n_above"] / sm["n_analytes"]).round(4)
    sm["below_flag"] = sm["frac_below"] >= fraction_threshold
    sm["above_flag"] = sm["frac_above"] >= fraction_threshold

    sample_detail_below: dict[str, list[str]] = {}
    sample_detail_above: dict[str, list[str]] = {}
    for r in in_range.itertuples(index=False):
        if r.status == "BELOW_RANGE":
            sample_detail_below.setdefault(r.well, []).append(r.analyte)
        elif r.status == "ABOVE_RANGE":
            sample_detail_above.setdefault(r.well, []).append(r.analyte)
    sm["problem_analytes_below"] = sm["well"].map(lambda w: ";".join(sample_detail_below.get(w, [])))
    sm["problem_analytes_above"] = sm["well"].map(lambda w: ";".join(sample_detail_above.get(w, [])))

    return {
        "antigen_summary": ag,
        "sample_summary": sm,
        "n_below_antigens": int(ag["below_flag"].sum()),
        "n_above_antigens": int(ag["above_flag"].sum()),
        "n_below_samples": int(sm["below_flag"].sum()),
        "n_above_samples": int(sm["above_flag"].sum()),
        "threshold": fraction_threshold,
    }
