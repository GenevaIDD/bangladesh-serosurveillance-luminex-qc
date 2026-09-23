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
(**5PL** by default, or **4PL**; chosen per report) per (standard ×
antigen), scores specimens against each antigen's calibrating standard,
and renders a self-contained interactive HTML report with three tabs
(Plate Report · Quality Assurance & Control · Background Correction
Comparison). Distributed as a macOS `.app` / Windows `.exe` (no Python or
internet required).

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

| Type          | Default patterns  | Example                               |
|---------------|-------------------|---------------------------------------|
| Background    | `^Background`     | `Background0`, `Background`           |
| NC            | `Negative`        | `Pilot Control: Negative 49 , 1:1000`, `Negative 0` |
| PC / standard | `^Pilot Control:` **plus** `^mAb Mix`, `^Measles`, `^Diphtheria`, `^Rubella`, `^Tetanus`, `^Dengue`, `^Cholera Pool` | `Pilot Control: Dengue pool 1:4000`, `Measles 1:125`, `mAb Mix 3 (…)` |
| Specimen      | (anything else)   | `BA6208_1:1000_IgG`, `12602_r3_Serum` |

NC is checked before PC because both share the `Pilot Control:` prefix. The
new-machine PC patterns are `^`-anchored so they never catch specimens like
`BA6208_1:1000_IgG`. The defaults recognize **both** naming conventions with no
config change.

## Standards & dilution parsing

PC samples carry the standard label and dilution in the name.
`classify.py::_parse_pc` extracts:

-   **pool** — name with any descriptive parenthetical stripped (e.g.
    `Dengue pool`, `Measles`, `mAb Mix`).
-   **dilution** — trailing `1:N` (→ N); `N ng/mL` for the pilot HlyE
    concentration axis; or, for the new machine's combined cholera/typhoid
    `mAb Mix N` standard, a **relative dilution** `4^(N-1)` (4-fold serial,
    all eight points collapse to one `mAb Mix` pool).
-   **single-point** controls (`Cholera High/Low`, `Cholera Pool
    High/Low`) — flagged, not fit; shown as reference markers and used as
    the cholera control for plate concordance.
-   **reference standards with a provenance descriptor** after the dilution,
    e.g. `Measles 1:125_Multipathogen_Plate1_NIBSC_SERUM` (a NIBSC reference
    serum re-run to check the standards) — the dilution is parsed (1:125) and
    the **full descriptor is kept as the pool label**, so the reference is its
    own distinct standard entity (not merged into the plain `Measles` standard)
    and can be tracked/compared across plates by name.

A curve grid is not rendered for a standard that produced **no** usable fit on a
plate (e.g. a standard with too few dilution points); a short note is shown
instead and its MFIs remain in the standard-curve data / QA Standard-curve
check. This also keeps standards-only "test plate" renders fast.

A logistic curve (5PL default / 4PL) is fit per (standard × antigen) using that
standard's own series. New-machine standards: `mAb Mix` (cholera + typhoid),
`Dengue`, `Measles`, `Diphtheria`, `Rubella`, `Tetanus`, plus the single-point
`Cholera Pool High/Low`. Pilot standards (`Anti-OSP & cTxB pool`,
`Anti-OSP & cTxB & HlyE pool`, `Dengue pool`, `HlyE`, `Cholera High/Low`, and a
legacy pan-arbovirus reference pool) are still recognized for back-compat.

### Antigen → standard scoring (`panel.pool_mode`)

A logistic curve (per `panel.curve_model`) is fit per (standard × antigen)
regardless of pool mode. How specimens are then scored (AU / range) is set by
`panel.pool_mode`:

- **`auto_select` (default)** — each antigen is scored against its
  calibrating standard:
    1.  Parse the antigen's pathogen category from its name (keyword map
        below).
    2.  Candidate standards = those whose name targets that category's scoring
        group **and** that produced a usable fit for the antigen.
    3.  Tie-break (and fall back when no name match) by **best fit**
        (`params` present → `fit_ok` → highest R²). No usable fit anywhere →
        `NO_FIT`.

    Resolution order per antigen: exact override
    (`panel.pool_antigen_overrides`) → user regex rules
    (`panel.pool_assignment_rules`) → keyword match → best-fit fallback.
    All matches are YAML-overridable.

    Antigen → scoring-group map (`_antigen_scoring_groups`): **cholera**
    (`CHO_` prefix, `CtxB`/`Inaba`/`Ogawa`/`cholera`/`vibrio`) → `[cholera]`;
    **typhoid** (`HlyE`/`typhi`) → `[typhoid]`; **dengue** (`DENV`+digit or
    `DENGUE`) → `[dengue]`; **other (non-dengue) arboviruses** (`ARB_` prefix)
    → `[arbovirus]`; **measles / diphtheria / rubella / tetanus** VPDs (plus
    `RES_measles_lysate`) → ordered `[<disease>, vpd_nibsc, arbovirus]`; **all
    other VPDs** (`VPD_` pertussis / bordetella / meningitidis, …) → `[]`
    (excluded from matching).

    Standard → scoring-group map (`_pool_groups`): a standard named `dengue` →
    `{dengue}`; `osp`/`ctxb`/`cholera` or `mab mix` → `{cholera}`; `hlye` or
    `mab mix` → `{typhoid}`; a combined `nibsc` pool → `{vpd_nibsc}`; a
    disease-named NIBSC standard (`measles`/`diphtheria`/`rubella`/`tetanus`) →
    that disease group. An antigen is relevant to (and featured under) a
    standard when its group intersects the standard's groups.

    Consequences: **cholera & typhoid** → mAb Mix; **dengue** → the dedicated
    **Dengue** standard; **M/D/R/T** → their dedicated NIBSC dilution series.
    **Non-dengue arboviruses and all other VPDs** have no calibrating standard:
    best-fit curve only, never marked relevant / featured (still viewable in the
    Picker and per-standard tables).

- **`per_pool`** — "fit every standard × antigen, no matching." A single
  **scoring pool** (`panel.scoring_pool`, or the pool with the most `fit_ok`
  antigens) is used for the in-report scoring sections. The downloadable
  **results** table is identical in either mode (see *Results table*).

### Run datetime & chronological ordering

`parse_xponent._canonical_run_datetime` derives one run datetime per plate,
preferring **`BatchStartTime`** over the export `Date` stamp, then
`BatchStopTime`; stored in `metadata.run_datetime` / `run_date`. ALL cross-plate
ordering sorts by this parsed datetime, so it is **independent of the order
reports were generated/uploaded**. If no header datetime parses,
`run_datetime_ok` is false and the report shows a visible warning banner.

**Plate labels** (`_label_plates`): a plate whose filename/id carries a "Plate N"
(e.g. `Multipathogen_plate2_…`) keeps that number; a plate without one (e.g. a
named test/QC plate like `NIBSC test plate_15.9.26`) is labelled by its own id
rather than taking a chronological number slot — so a test plate never shifts the
survey plates' numbers (previously it could renumber `Plate 3` to `Plate 4`).
When every plate is numbered, those numbers are used; when none is, all are
numbered by run order.

## Curve model & fit QC (`qc_standard_curve.py`)

Two logistic models, selected per report via `panel.curve_model` (default
`5pl`; the home page sets it per render, Settings sets the default). The home
page exposes **two independent selectors** — one on **Generate Report** and one
beside **Regenerate All** — each defaulting to the saved Settings model; the
chosen model is persisted per plate and surfaced as a **Fit** column in the Past
Reports table:

- **5PL** (default): `y = d + (a − d) / (1 + (x/c)^b)^g` — the asymmetry `g`
  (bounded 0.1–10; `g = 1` ≡ 4PL) lets the two ends approach their asymptotes at
  different rates, reducing back-calculation bias near an asymptote.
- **4PL**: `y = d + (a − d) / (1 + (x/c)^b)`.

Both are fit with **scipy `curve_fit`** (Trust Region Reflective, bounded
parameters, `maxfev = 10000`) on **log10(MFI)** — so the noise floor and the
high-signal plateau contribute comparably to the residuals. Initial guesses come
from the data (a = max MFI, d = min MFI, c = median dilution, b = 1, g = 1); a
degenerate-input guard skips all-zero / flat / no-signal beads before the
optimiser. A report uses **one model throughout** — there is no per-antigen
fallback; an antigen the chosen model cannot fit is `NO_FIT` for that report.
`fit_ok` requires: R² ≥ 0.95 (log), IC50 within tested range (×3 margin),
0.3 ≤ Hill ≤ 5.0, dynamic range ≥ 3×. An optional leave-one-out single-outlier
retry runs when a fit converges but fails QC. `reportable_range` (LLOQ/ULOQ
dilution + MFI) comes from a ±`recovery_tolerance` (default 0.30) Obs/Exp check
and drives the linear-range square and range classification. The independent
per-antigen fits are dispatched **across CPU cores** (with a serial fallback);
results are numerically identical to serial. `curve_eval` / `curve_invert`
dispatch on parameter count (5 → 5PL, else 4PL); the fitted `model` and `g` are
stored per fit and in history.

## AU (Arbitrary Units)

`compute_concentrations` inverts each specimen's MFI through its standard curve
to a dilution-equivalent, then `AU = (first_dilution / dilution_equiv) × 1000`,
anchored so the standard's lowest (most concentrated) dilution = 1000 AU. AU is
computed for **every** (standard × antigen) that produced a fit, so a specimen's
value against every standard is available.

## Report sections

The report has a sticky tab bar with three tabs. A red banner appears at the top
of any report whose **run datetime could not be parsed**.

### Tab 1 — Plate Report

1.  **Plate metadata** table (incl. "Run date & time" = the parsed run start);
    an 8-card single row: Total, PC/standard, **one card per single-point
    control** (Cholera Pool High / Low), NC, Specimen, Background, Antigens;
    shape-coded 384 plate map (freeze-pane scroll, hover = well/sample/type).
2.  **Bead Count** — a collapsed description box, five summary cards, and a
    freeze-pane antigen × well tier heatmap (RED < `bead_count_min`, YELLOW <
    `bead_count_warn`, else GREEN) with **wells ordered by plate position**.
3.  **Background QC** — info cards; a two-view cross-plate overview (see *Control
    overviews*) with a dashed reference line at `bg_max_mfi`; the **background
    well outliers** table (leave-one-out) presented **first**, then the full
    per-antigen table (per-well MFIs, SD, %CV, IQR, intra-plate **High CV** and
    inter-assay **High hist. CV** flags), then a **negative net MFI** table.
3b. **Positive Control QC** — single-point Cholera Pool High/Low duplicates;
    two-view overview + stats table, cholera-specific antigens **bold at the
    top** with the rest greyed for context.
3c. **Negative Control QC** — per-control (Negative 0/49) two-view overview +
    stats table with a **duplicate-%CV** flag column and a focused flag table.
4.  **Standard-Curve Summary** — count cards; **one sortable fit table per
    standard** over all antigens (params a, b, c, d, and g for 5PL; LLOQ/ULOQ),
    each row carrying a **Relevance** column; a banner states the report's model.
    A **per-standard Range-problem specimens** subsection gives **each dedicated
    standard its own table** (mAb Mix, Dengue, Measles, Diphtheria, Rubella,
    Tetanus): a well is flagged when ≥ `problem_fraction_threshold` of that
    standard's **dedicated** antigens read out of range. Every dedicated standard
    gets a block — one with none flagged shows a "none flagged" note, one whose
    curve did not fit shows a "cannot assess" note.
5.  **All-Curves Overview** — **featured priority antigens** organised by
    standard, **one curve per row**, each fit against its standard. Each panel
    overlays **every other plate** — its fitted curve in light grey **and its raw
    standard points as grey × markers** (Show all / Hide other plates). Overlays
    are **not** limited to earlier-run plates (`_other_plate_ids`), so a plate and
    a reference/test plate compare mutually regardless of recorded run order, and
    a point-only standard that never fits a curve (e.g. a 2-dilution NIBSC test
    standard) still contributes its points to every plate's panel. The other-plate
    list is taken from every history (`_pl_run`), so a **standards-only plate with
    no specimens** is included. When an **age file** is loaded, each panel shows a
    horizontal **range-status by age group** bar chart beside the curve (4 groups:
    6 mo–2 y, 3–4 y, 5–14 y, 15+). A collapsed block then shows one grid per
    standard over all antigens (interactive when ≤ 48 panels, else static PNG);
    that collapsed grid is skipped (with a note) for a standard that produced no
    usable fit, since every panel would be empty.
6.  **Standard-Curve Picker** — folded; type to inspect any antigen; the panel is
    **titled with the selected antigen × standard**; curve + rug on a shared
    y-range, overlaying all other plates (current column first, then the others
    chronologically).

(The report itself has **no Downloads section** — all downloads are on the home
page: the per-plate **Download CSV** and the **Export All** ZIP.)

### Tab 2 — Quality Assurance & Control

- **Plate Concordance** — a plate × plate heatmap; each cell is the **mean of
  four controls' Lin's CCCs** on log₁₀ MFI: Negative 0 and Negative 49 across
  all antigens, and Cholera High and Cholera Low across the **cholera** antigens.
  Green ≈ 1.0, red below `concordance_threshold`; hover shows the four
  individual CCCs. Cholera controls are detected by **content** (any control
  label containing "cholera" + "high"/"low"), covering both the pilot
  (`Cholera High/Low`) and new-machine (`Cholera Pool High/Low`) names. Lin's
  CCC needs ≥ 3 shared antigens (the panel's 3 cholera antigens — `CHO_CtxB`,
  `CHO_Inaba_OSP`, `CHO_Ogawa_OSP`) and ≥ 2 plates.
- **Flag summaries** — four tables, **each with an Export CSV button** (a
  client-side table→CSV download that also works on a saved report file):
  **Sample check** (specimen wells with ≥ 1 flag: low bead count / negative net
  MFI / outside LOD), **Antigen check** (flagged in > 1 sample / high background
  / high inter-plate %CV), **Plate check** (per-plate overall / negative /
  cholera-pool concordance vs `concordance_threshold`), and **Standard curve
  check** (starting-dilution MFI %CV and cross-plate CCC per standard × antigen;
  needs ≥ 2 plates). Sample check and Antigen check each carry a **# flags**
  column = the number of flag *types* that fired for that row (distinct from the
  per-antigen "flagged in > 1 sample" *sample* count). The Standard curve check
  shows concordance as **`n/a`** when the curve has < 3 shared dilution points
  across plates (Lin's CCC is undefined), so a row can appear on the
  starting-%CV flag alone.

### Tab 3 — Background Correction Comparison

Cross-plate concordance of the per-antigen mean **specimen** MFI under three
background treatments — **Raw**, **Background-subtracted**, and
**Background-divided** — compared between plates on a **linear** scale, with
**bootstrap 95 % CIs**, to show how each correction affects between-plate
agreement.

### Control overviews (Background / PC / NC) — two views

Each cross-plate overview has a toggle:

- **Median ± IQR** (default once ≥ 3 past plates): grey IQR band of each
  antigen's historical per-plate mean; this plate's mean is a dot, blue within
  the IQR / orange ♦ outside.
- **Per-plate data points** (default with < 3 past plates): every plate as its
  own dot — current plate **red**, past plates on a chronological blue→green
  gradient.

## Outputs

Per plate, written to `reports/`: `results_*.csv` (the canonical results
table — see below), `in_range_*.csv`, `pct_in_range_*.csv`,
`bead_problems_*.csv`, `bead_problem_{antigens,samples}_*.csv`,
`range_problem_{antigens,samples}_*.csv`, `background_qc_*.csv`,
`pc_single_point_*.csv`, `nc_levels_*.csv`. Cross-plate history JSON per
standard/metric in `history/`. The individual age form (if uploaded) is
`age_data.csv`.

### Results table (`results_*.csv`)

The single canonical results representation — one row per (specimen well ×
antigen), **wide by standard**, identical whichever `panel.pool_mode` is set.
Columns:

`plate_id, well, sample_id, analyte, mfi, net_mfi, result_type,
reporting_standard`, then, for **every** standard on the plate,
`AU_<standard>` and `status_<standard>`.

- Every antigen × standard AU is shown, regardless of dedication.
- **`reporting_standard`** = the antigen's *intended* dedicated calibrator,
  matched by pathogen name among the standards present, **independent of
  whether that curve fit this run** (`pipeline._build_clean_results` →
  `_intended_standard`). Read the headline value from the matching
  `AU_<standard>` / `status_<standard>` columns (`NO_FIT` when the fit failed).
  Blank only when the antigen has no dedicated standard on the plate.
- **`result_type`** (`antigen_calibration` → tier): `quantitative`
  (dedicated standard), `semi-quantitative` (legacy shared reference pool —
  pilot data only), `qualitative` (no calibrator). Describes assay design, not
  run outcome.
- `status_<standard>` ∈ {IN_RANGE, BELOW_RANGE, ABOVE_RANGE, NO_FIT}, from the
  specimen MFI vs that standard's reportable-range MFI bounds. Empty AU cells
  are left blank (read as `NA` in R).

### Export All (`/export/all`) → ZIP of CSVs

A single ZIP with one CSV per table, each combined across all plates:
`results`, `in_range`, `pct_in_range`, `range_problem_antigens/samples`,
`background_qc`, `bead_problem_antigens/samples`, `bead_problems`,
`pc_single_point`, `standard_curve_params`, `standard_curve_data`, `nc_levels`.
The combined `results` table only includes per-plate CSVs written in the current
schema (identified by `result_type` + `reporting_standard`); stale older-schema
files are skipped — Regenerate All to include them. There is no Excel workbook
(CSVs are instant to build, engine-independent, and R-friendly).

## Settings (`config.yaml`)

Well-classification patterns; `panel.curve_model` (5pl default / 4pl);
`panel.pool_mode` / `scoring_pool` / `pool_assignment_rules` /
`pool_antigen_overrides`; excluded analytes; `bead_count_min` /
`bead_count_warn`; `problem_fraction_threshold`; `bg_cv_threshold`;
`bg_max_mfi` (default 300, dashed reference line); `nc_cv_threshold`
(default 0.25); `hist_cv_threshold` (default 0.30, inter-assay %CV drift);
`recovery_tolerance`; `drop_outlier`; `specimens.default_dilution`
(informational only). Every field is read by its consumer, and every
threshold shown in the report comes from these settings.

## Module map

-   `parse_xponent.py` — xPONENT CSV → metadata + long-format MFI/count.
-   `classify.py` — well classification + standard/dilution parsing.
-   `qc_beads.py` — bead-count tiers + problem summaries.
-   `qc_background.py` — per-antigen background spread + IQR.
-   `qc_standard_curve.py` — 5PL/4PL fit (parallel), standard selection, AU,
    range table.
-   `qc_nc.py` / `qc_pc_single_point.py` — NC well levels; single-point controls.
-   `age.py` — participant age form → age-group map for the age-stratified bars.
-   `qc_history.py` / `pipeline.py` — cross-plate history + orchestration +
    the canonical results table.
-   `report.py` / `templates/report.html` — HTML report (3 tabs, concordance,
    background-correction comparison, per-table CSV export).
-   `app.py` / `templates/web/` — Flask UI, settings, per-plate download, ZIP
    export.

## Deferred / in development

Formal Background / PC / NC pass/fail flagging; deeper NC-level QC; full-panel
picker performance; cross-plate sample-ID matching (needs a master list).
