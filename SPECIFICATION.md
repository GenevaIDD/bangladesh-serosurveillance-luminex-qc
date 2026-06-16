---
editor_options: 
  markdown: 
    wrap: 72
---

# Bangladesh Serosurveillance Luminex QC Tool — Specification

# Version 0.1.0-bangladesh

## Overview

Standalone QC tool for the Bangladesh National Serosurveillance
**202-plex** Luminex immunoassay, run on a Luminex **Intelliflex** in
**High PMT** mode on a **384-well** plate. It parses the xPONENT
plate-result CSV, classifies wells, fits 4PL standard curves per
(control pool × antigen), scores specimens against each antigen's
calibrating pool, and renders a self-contained interactive HTML report.
Distributed as a macOS `.app` / Windows `.exe` (no Python or internet
required).

## Assay panel

Production panel: **202 antigens** (pilot plates ran fewer due to
reagent supply). The panel is **re-derived from the CSV `Median` block
header on every ingest** — the default `src/config.py::ANTIGENS` is a
fallback/display list only. Excluded analytes (soft-flag list) default
to empty and are editable in Settings.

## Plate layout

384-well (rows A–P × columns 1–24). No Intelliflex input file is needed;
wells are classified from the `Sample` name, checked in order
**Background → NC → PC → specimen** (patterns editable in Settings):

| Type          | Default pattern   | Example                               |
|---------------|-------------------|---------------------------------------|
| Background    | `^Background`     | `Background0`                         |
| NC            | `Negative`        | `Pilot Control: Negative 49 , 1:1000` |
| PC / standard | `^Pilot Control:` | `Pilot Control: Dengue pool 1:4000`   |
| Specimen      | (anything else)   | `12602_r3_Serum`                      |

NC is checked before PC because both share the `Pilot Control:` prefix.

## Control pools & dilution parsing

PC samples carry the pool label and dilution in the name.
`classify.py::_parse_pc` extracts:

-   **pool** — name with any descriptive parenthetical stripped (e.g.
    `Dengue pool`).
-   **dilution** — trailing `1:N` (→ N), or `N ng/mL` for HlyE (a
    concentration axis).
-   **single-point** controls (e.g. `Cholera High/Low`) — flagged, not
    fit; shown as reference markers.

A 4PL is fit per (pool × antigen) using that pool's own series. Pools
observed in the pilots: `Anti-OSP & cTxB pool`,
`Anti-OSP & cTxB & HlyE pool`, `Dengue pool`, `Orpal pool`, `HlyE`,
`Cholera High/Low`.

### Antigen → pool scoring (`panel.pool_mode`)

A 4PL is fit per (pool × antigen) regardless of mode. How specimens are
then scored (RAU / range) is set by `panel.pool_mode`:

- **`per_pool` (default)** — "fit every pool × antigen, no matching." RAU
  and range status use a single **scoring pool** (`panel.scoring_pool`, or
  the pool with the most `fit_ok` antigens). No per-antigen pool matching.
  The Summary table and All-Curves Overview show one row/grid per pool.
- **`auto_select`** — each antigen is scored against its calibrating pool
  (`qc_standard_curve.select_pool_per_antigen`):
    1.  Parse the antigen's pathogen group from its name (keyword map
        below).
    2.  Candidate pools = those whose name targets that group **and** that
        produced a usable fit for the antigen.
    3.  Tie-break (and fall back when no name match) by **best fit**
        (`params` present → `fit_ok` → highest R²) — so when several pools
        match, exactly one (the best-fitting) is used per antigen. No usable
        fit anywhere → `NO_FIT`.

    Resolution order per antigen: exact override
    (`panel.pool_antigen_overrides`, config-file only) → user regex rules
    (`panel.pool_assignment_rules`) → keyword match → best-fit fallback.

    Keyword map (antigen-name token → pool-name token):
    dengue (`DENV`/`DENGUE`) → `dengue`/`orpal`;
    cholera (`CHO_` prefix, `CtxB`/`Inaba`/`Ogawa`/`cholera`/`vibrio`) →
    `osp`/`ctxb`/`cholera`; typhoid (`HlyE`/`typhi`) → `hlye`.

In `per_pool` mode the in-report scoring sections (count cards, range
matrix, range-problem tables, Serum-vs-DBS, picker) all use the single
scoring pool; per-pool RAU lives in the master export and specimens CSV.

## 4PL model & fit QC (`qc_standard_curve.py`)

`y = d + (a − d) / (1 + (x/c)^b)`, fit on log10(MFI). `fit_ok` requires:
R² ≥ 0.95, IC50 within tested range (×3 margin), 0.3 ≤ Hill ≤ 5.0,
dynamic range ≥ 3×. Optional leave-one-out single-outlier retry.
`reportable_range` (LLOQ/ULOQ dilution + MFI) comes from a
±`recovery_tolerance` (default 0.30) Obs/Exp check and drives the
linear-range square and range classification.

## Report sections (in order)

1.  **Plate Overview** — metadata table; count cards; shape-coded 384
    plate map (freeze-pane scroll, hover = well/sample/type).
2.  **Bead Count** — freeze-pane antigen × well tier heatmap (RED \<
    `bead_count_min`, YELLOW \< `bead_count_warn`, else GREEN);
    flagged-antigen/specimen cards.
3.  **Background QC** — info cards; cross-plate overview (dots \< 3
    plates; previous-plate IQR bar + current dot ≥ 3 plates, out-of-IQR
    flagged); folded per-antigen table (individual MFIs, SD, %CV,
    current/previous IQR).
4.  **Standard-Curve Summary** — count cards (below/above flags, scored
    against the scoring pool in `per_pool`); curve table — one row per
    (pool × antigen) in `per_pool`, or per antigen with its selected Pool
    in `auto_select` — with 4PL params, LLOQ/ULOQ, % in range. Plus PC
    replicate-variability (%CV between duplicate standard wells, per
    pool × antigen × dilution).
5.  **All-Curves Overview** — one grid per pool (`per_pool`) or the
    selected-pool curve per antigen (`auto_select`); interactive
    small-multiples (hover, current-plate rug, green linear-range
    square, red out-of-tolerance standards, ✕ dropped point) when ≤ 48
    panels, else a static grid. Non-converged (pool × antigen) pairs
    appear as observed points only — no curve or range square.
6.  **Standard-Curve Picker** — folded; type to inspect any antigen;
    curve + rug pinned to a shared y-range; linear-range square;
    cross-plate overlays.
7.  **Standard-Curve Range Matrix** — freeze-pane specimen × antigen
    status; folded **Serum-vs-DBS** scatter (paired per person ×
    antigen).
8.  **Negative Control QC** — per-antigen NC MFI across plates (controls
    kept separate; current plate ringed); folded NC details (grouped
    bar + Well / Control / Analyte / MFI table).
9.  **Downloads**.

## Outputs

Per plate (in `reports/`, plus `specimens/specimens_*.csv`):
`results_*.csv` (clean master; shape follows `panel.pool_mode` — see
below), `in_range_*.csv`,
`pct_in_range_*.csv`, `bead_problems_*.csv`,
`bead_problem_{antigens,samples}_*.csv`,
`range_problem_{antigens,samples}_*.csv`, `background_qc_*.csv`,
`nc_levels_*.csv`. Cross-plate history JSON per pool/metric in
`history/`.

The clean master (`results_*.csv` and the workbook `results` sheet)
follows `panel.pool_mode`. In **per_pool** (default — "fit every pool ×
antigen, no auto-selecting") it is one row per (well × antigen) with a
`RAU (<pool>)` + `status (<pool>)` column pair for **every** control
pool; an antigen a pool never calibrated reads `NO_FIT`. In
**auto_select** it is a tidy single-pool table (plate, well, sample_id,
matrix, analyte, `pool`, mfi, RAU, status, censored). Per-pool RAU is
always also available, wide, in the `specimens` sheet.

Master **Export All (.xlsx)**: `results`, `specimens`,
`standard_curve_params`, `standard_curve_data`, `nc_levels`.

## Settings (`config.yaml`)

Well-classification patterns; priority antigens (blank = all); excluded
analytes; `bead_count_min` / `bead_count_warn`;
`problem_fraction_threshold`; `bg_cv_threshold`; `bg_max_mfi` (default
300, reference); `recovery_tolerance`; `drop_outlier`.

## Module map

-   `parse_xponent.py` — xPONENT CSV → metadata + long-format MFI/count
    (A–P × 1–24).
-   `classify.py` — well classification + pool/dilution parsing.
-   `qc_beads.py` — bead-count tiers + problem summaries.
-   `qc_background.py` — per-antigen background spread + IQR.
-   `qc_standard_curve.py` — 4PL fit, pool selection, RAU, range table.
-   `qc_nc.py` — NC well levels.
-   `qc_history.py` / `pipeline.py` — cross-plate history +
    orchestration.
-   `report.py` / `templates/report.html` — HTML report.
-   `app.py` / `templates/web/` — Flask UI, settings, downloads, master
    export.

## Deferred / in development

Formal Background pass/fail flagging; deeper NC-level QC (thresholds,
drift); PC replicate variability; full-panel picker performance;
confirmation of the exact pool → priority-antigen mapping by the lab
team.
