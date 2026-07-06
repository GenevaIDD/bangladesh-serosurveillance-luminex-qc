---
editor_options: 
  markdown: 
    wrap: 72
---

# Bangladesh Serosurveillance Luminex QC Tool — Specification

# Version 0.3.0-bangladesh

## Overview

Standalone QC tool for the Bangladesh National Serosurveillance
**202-plex** Luminex immunoassay, run on a Luminex **Intelliflex** in
**High PMT** mode on a **384-well** plate. It parses the xPONENT
plate-result CSV, classifies wells, fits logistic standard curves
(**5PL** by default, or **4PL**; chosen per report) per (control pool ×
antigen), scores specimens against each antigen's calibrating pool, and
renders a self-contained interactive HTML report.
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

A logistic curve (5PL default / 4PL) is fit per (pool × antigen) using that pool's own series. Pools
observed in the pilots: `Anti-OSP & cTxB pool`,
`Anti-OSP & cTxB & HlyE pool`, `Dengue pool`, `Orpal pool`, `HlyE`,
`Cholera High/Low`.

### Antigen → pool scoring (`panel.pool_mode`)

A logistic curve (per `panel.curve_model`) is fit per (pool × antigen) regardless of pool mode. How specimens are
then scored (RAU / range) is set by `panel.pool_mode`:

- **`auto_select` (default)** — each antigen is scored against its
  calibrating pool (`qc_standard_curve.select_pool_per_antigen`):
    1.  Parse the antigen's pathogen category from its name (keyword map
        below).
    2.  Candidate pools = those whose name targets that category's scoring
        group **and** that produced a usable fit for the antigen.
    3.  Tie-break (and fall back when no name match) by **best fit**
        (`params` present → `fit_ok` → highest R²) — so when several pools
        match, exactly one (the best-fitting) is used per antigen. No usable
        fit anywhere → `NO_FIT`.

    Resolution order per antigen: exact override
    (`panel.pool_antigen_overrides`) → user regex rules
    (`panel.pool_assignment_rules`) → keyword match → best-fit fallback.
    All matches are YAML-overridable.

    Antigen → scoring-group map (`_antigen_scoring_groups`): **cholera**
    (`CHO_` prefix, `CtxB`/`Inaba`/`Ogawa`/`cholera`/`vibrio`) → `[cholera]`;
    **typhoid** (`HlyE`/`typhi`) → `[typhoid]`; **dengue** (`DENV`+digit or
    `DENGUE` — the digit avoids matching e.g. "DENVer") → `[dengue]`; **other
    (non-dengue) arboviruses** (`ARB_` prefix) → `[arbovirus]`; **measles /
    diphtheria / rubella / tetanus** VPDs (plus `RES_measles_lysate`) →
    ordered `[vpd_nibsc, arbovirus]`; **all other VPDs** (`VPD_` pertussis /
    bordetella / meningitidis, …) → `[]` (excluded from matching).

    Pool → scoring-group map (`_pool_groups`): a pool named `dengue` →
    `{dengue}`; a **pan-arbovirus** pool named `orpal` / `pasteur` /
    `institut` → `{dengue, arbovirus}`; `osp`/`ctxb`/`cholera` → `{cholera}`;
    `hlye` → `{typhoid}`; `nibsc` → `{vpd_nibsc}`. An antigen is relevant to
    (and featured under) a pool when its group intersects the pool's groups.

    Consequences: **dengue** is fit against both the dedicated **Dengue** pool
    and the pan-arbovirus **Institute Pasteur / Orpal** pool, but **prefers
    the dedicated Dengue pool for scoring** — `select_pool_per_antigen` adds a
    `dedicated` ranking tier (above R², below `params`/`fit_ok`) that
    deprioritizes the pan-arbo pool for `dengue`, so it only falls back there
    if the dedicated fit is unusable. **Other arboviruses** are relevant only
    to the pan-arbo pool. **M/D/R/T** prefer a `NIBSC` pool when present, else
    the pan-arbo reference. **All other VPDs** have no calibrating standard:
    best-fit pool only, never marked relevant / featured (still viewable in
    the Picker and per-pool tables). If a real NIBSC pool name lacks "NIBSC",
    route it with a `pool_assignment_rules` entry.

    **Calibration tier** (`antigen_calibration`, exported per specimen):
    `standard` = cholera/typhoid/dengue, or a NIBSC-matched
    measles/diphtheria/rubella/tetanus; `reference` = a non-dengue arbovirus
    on the pan-arbo pool, or an M/D/R/T VPD on the pan-arbo fallback (no
    NIBSC); `uncalibrated` = no calibrating standard (other VPDs, and any
    antigen with no pathogen match — best-fit RAU kept but flagged, not
    quantitative).
- **`per_pool`** — "fit every pool × antigen, no matching." RAU and range
  status use a single **scoring pool** (`panel.scoring_pool`, or the pool
  with the most `fit_ok` antigens). No per-antigen pool matching. The
  Summary and All-Curves Overview show one table/grid per pool.

In `per_pool` mode the in-report scoring sections (count cards, range
matrix, range-problem tables, Serum-vs-DBS, picker) all use the single
scoring pool; per-pool RAU lives in the master export and specimens CSV.

### Run datetime & chronological ordering

`parse_xponent._canonical_run_datetime` derives one run datetime per plate,
preferring **`BatchStartTime`** (the actual run start) over the export
`Date` stamp, then `BatchStopTime`; stored in `metadata.run_datetime` /
`run_date`. ALL cross-plate ordering — history, legends, and the picker rug
columns — sorts by this parsed datetime, so it is **independent of the
order reports were generated/uploaded** (`_past_plate_ids`). "Past" = run
strictly before the current plate. If no header datetime parses,
`run_datetime_ok` is false and the report shows a visible warning banner;
ordering degrades gracefully rather than crashing.

## Curve model & fit QC (`qc_standard_curve.py`)

Two logistic models, selected per report via `panel.curve_model` (default
`5pl`; the home page sets it per render, Settings sets the default). The home
page exposes **two independent selectors** — one on the **Generate Report** form
and one beside **Regenerate All** — each defaulting to the saved Settings model;
the chosen model is persisted to the plate registry per plate and surfaced as a
**Fit** column in the Past Reports table:

- **5PL** (default): `y = d + (a − d) / (1 + (x/c)^b)^g` — the asymmetry `g`
  (bounded 0.1–10; `g = 1` ≡ 4PL) lets the two ends approach their asymptotes at
  different rates, reducing back-calculation bias near an asymptote.
- **4PL**: `y = d + (a − d) / (1 + (x/c)^b)`.

Both are fit on log10(MFI). A report uses **one model throughout** — there is no
per-antigen fallback; an antigen the chosen model cannot fit is `NO_FIT` for that
report (re-render under the other model to try it). `fit_ok` requires: R² ≥ 0.95,
IC50 within tested range (×3 margin), 0.3 ≤ Hill ≤ 5.0, dynamic range ≥ 3×.
Optional leave-one-out single-outlier retry. `reportable_range` (LLOQ/ULOQ
dilution + MFI) comes from a ±`recovery_tolerance` (default 0.30) Obs/Exp check
and drives the linear-range square and range classification. `curve_eval` /
`curve_invert` dispatch on parameter count (5 → 5PL, else 4PL); the fitted
`model` and `g` are stored per fit and in history, so past-plate overlays are
drawn under the model each plate was generated with.

## Report sections (in order)

A red banner appears at the top of any report whose **run datetime could
not be parsed** (chronological ordering then unreliable — see *Run
datetime & ordering* below).

1.  **Plate Overview** — metadata table (incl. "Run date & time" = the
    parsed run start); an 8-card single row: Total, PC/standard, **one card
    per single-point control** (e.g. Cholera High / Cholera Low PC wells,
    placed between PC/standard and NC), NC, Specimen, Background, Antigens;
    shape-coded 384 plate map (freeze-pane scroll, hover = well/sample/type).
2.  **Bead Count** — a collapsed **"How the Bead-Count Matrix works"**
    description box above **five summary cards**: wells with ≥ 1 antigen at
    critically-low count (out of the wells run), critically-low (\<
    `bead_count_min`) and low grid-cell counts, and flagged antigens /
    specimens; a mechanics note (hover contents, sticky row/column, group
    separators); freeze-pane antigen × well tier heatmap (RED \<
    `bead_count_min`, YELLOW \< `bead_count_warn`, else GREEN) with **wells
    ordered by plate position (A1 → last)** so re-run wells appended to the CSV
    stay in sequence. Antigen flag denominator = all wells; specimen flag
    denominator = specimen wells.
3.  **Background QC** — info cards (counts of high **intra-plate** %CV and
    high **inter-assay** %CV antigens); a fixed-width, horizontally-scrolling
    cross-plate overview with a **two-view toggle** (see *Control overviews*
    below) and a dashed reference line at `bg_max_mfi`; folded per-antigen
    table (per-well MFIs, SD, %CV, current/previous IQR, a sortable
    intra-plate **High CV** flag, and a **High hist. CV** flag for inter-assay
    /run-to-run drift when the historical %CV exceeds `hist_cv_threshold`;
    antigens with a flagged well-outlier get a `⚠ outlier` badge + row
    highlight); two hidden tables — **background well outliers** (leave-one-out
    flag: a well \> mean + 2·SD of the *other* wells; the literal all-wells
    mean/SD/threshold are shown alongside for comparison) and **specimens with
    negative net MFI** (specimen MFI − mean plate background).
3b. **Positive Control QC** — single-point Cholera High/Low duplicates;
    two-view cross-plate overview + per-antigen stats table (same layout as
    Background).
3c. **Negative Control QC** — per-control (Negative 0/49) two-view
    scrolling overview + stats table with a **duplicate-%CV** flag column,
    plus a focused table listing the flagged antigens with their two well
    MFIs + %CV (or a "✓ none" line) when the wells disagree by \>
    `nc_cv_threshold`.
4.  **Standard-Curve Summary** — count cards; **one sortable fit table per
    standard pool** over **all** antigens, each labelled with the pathogen
    target(s) it calibrates, with the model's params (a, b, c, d, and g for 5PL)
    and LLOQ/ULOQ. A banner states the report's curve model. Each row carries a
    **Relevance** column (checked when that pool is the antigen's designated
    calibrator/reference); relevant rows sort first, and the rest stay visible
    so every antigen × pool fit can be inspected.
5.  **All-Curves Overview** — **featured priority antigens** organized **by
    standard pool** (one section per pool, labelled with its pathogen
    target(s)); each section shows the antigens relevant to that pool, **each
    fit against that pool** — so a dengue antigen appears under both the Dengue
    and the pan-arbo Institute Pasteur / Orpal sections. Each panel overlays
    the antigen's **past-plate fitted curves in light grey** with a **Show all
    / Hide past plates** toggle. Antigens with no calibrating standard are not
    featured. A collapsed block then shows one grid per pool over all antigens
    (a curve is fit for every antigen × every pool regardless). Interactive
    small-multiples when ≤ 48 panels, else static.
6.  **Standard-Curve Picker** — folded; type to inspect any antigen; the panel
    is **titled with the selected antigen × pool**; curve + rug on a shared
    y-range; **X = "Standard dilution (1:x)", Y = "MFI (log scale)"**; rug
    column labels at the **top** (vertical, small), ordered **current →
    nearest-past → oldest**; past-plate rug coloured by range status (higher
    transparency); cross-plate overlays.
7.  **Standard-Curve Range Matrix** — freeze-pane specimen × antigen status;
    each cell is the specimen's status vs **its antigen's matched standard**
    (dengue vs the dedicated Dengue pool; uncalibrated antigens vs a best-fit
    pool), and the **cell hover names that calibrating pool + tier** (making
    the best-fit / "no calibrating standard" cases explicit); antigen rows
    grouped and colour-labelled by pathogen (dotted separators + legend). The
    folded **Range-problem antigens** table carries a **Standard** column
    (matched pool + tier). The **Range-problem specimens** table is computed
    **per standard pool** — a well is flagged for a pool when ≥
    `problem_fraction_threshold` of that pool's **dedicated** antigens read out
    of range (reference antigens shown as context only). An **Out-of-range
    detail list** gives every out-of-range cell (MFI vs LLOQ/ULOQ) with its
    Standard. Folded **Serum-vs-DBS** scatter.
8.  **Downloads**.

### Control overviews (Background / PC / NC) — two views

Each cross-plate overview has a toggle (buttons top-left, under the legend;
`margin.autoexpand=False` keeps them from shifting when toggled):

- **Median ± IQR** (default once ≥ 3 past plates): grey IQR band of each
  antigen's historical per-plate mean; this plate's mean is a dot, blue
  within the IQR / orange ♦ outside.
- **Per-plate data points** (default with < 3 past plates): every plate as
  its own dot — current plate **red**, past plates on a chronological
  blue→green gradient (oldest faded, newest bold). Legend toggles individual
  plates; Show all / Hide past plates for bulk control.

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
follows `panel.pool_mode`. In **auto_select** (default) it is a tidy
single-pool table (plate, well, sample_id, matrix, analyte, `pool`,
`calibration`, mfi, RAU, status, censored) — one matched pool per antigen,
with `calibration` = standard / reference / uncalibrated (see *Calibration
tier* above). In **per_pool** it is one row per (well × antigen) with a
`RAU (<pool>)` + `status (<pool>)` column pair for **every** control pool;
an antigen a pool never calibrated reads `NO_FIT`. Per-pool RAU is always
also available, wide, in the `specimens` sheet.

Master **Export All (.xlsx)**: `results`, `specimens`,
`standard_curve_params`, `standard_curve_data`, `nc_levels`.

## Settings (`config.yaml`)

Well-classification patterns; `panel.curve_model` (5pl default / 4pl);
`panel.pool_mode` / `scoring_pool` / `pool_assignment_rules` /
`pool_antigen_overrides`; excluded analytes; `bead_count_min` /
`bead_count_warn`; `problem_fraction_threshold`; `bg_cv_threshold`;
`bg_max_mfi` (default 300, dashed reference line); `nc_cv_threshold`
(default 0.25, NC duplicate-well disagreement); `hist_cv_threshold`
(default 0.30, inter-assay/between-plate %CV drift flag); `recovery_tolerance`;
`drop_outlier`; `specimens.default_dilution` (informational only — not
used in the RAU calculation).

## Module map

-   `parse_xponent.py` — xPONENT CSV → metadata + long-format MFI/count
    (A–P × 1–24).
-   `classify.py` — well classification + pool/dilution parsing.
-   `qc_beads.py` — bead-count tiers + problem summaries.
-   `qc_background.py` — per-antigen background spread + IQR.
-   `qc_standard_curve.py` — 5PL/4PL fit, pool selection, RAU, range table.
-   `qc_nc.py` — NC well levels.
-   `qc_history.py` / `pipeline.py` — cross-plate history +
    orchestration.
-   `report.py` / `templates/report.html` — HTML report.
-   `app.py` / `templates/web/` — Flask UI, settings, downloads, master
    export.

## Deferred / in development

Formal Background / PC / NC pass/fail flagging; deeper NC-level QC (thresholds,
drift); full-panel picker performance; cross-plate sample-ID matching (needs a
master list). (The **5PL curve model** is now implemented — default, with a 4PL
option, per report — see *Curve model & fit QC* above. The pool →
relevant-antigen mapping is fixed: dedicated Dengue pool vs pan-arbovirus
Institute Pasteur / Orpal reference; NIBSC for measles / diphtheria / rubella /
tetanus with a pan-arbo fallback; other VPDs uncalibrated.)
