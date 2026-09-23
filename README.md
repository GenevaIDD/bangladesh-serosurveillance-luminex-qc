---
editor_options: 
  markdown: 
    wrap: 72
---

# Bangladesh Serosurveillance Luminex QC Tool

<p align="center">

<img src="gdd_antibody_square_tighter.png" alt="Bangladesh Serosurveillance Luminex QC" width="128"/>

</p>

<p align="center">

<strong>Automated quality control for the 202-plex Luminex immunoassay
(Intelliflex, 384-well, High PMT) — Bangladesh National
Serosurveillance</strong><br> <em>Geneva Disease Dynamics Group ·
University of Geneva</em>

</p>

<p align="center">

<a href="SPECIFICATION.md">Full Specification</a>

</p>

------------------------------------------------------------------------

## Overview

Standalone desktop tool for QC of the Bangladesh National
Serosurveillance **202-plex** Luminex immunoassay, run on a Luminex
**Intelliflex** instrument in **High PMT** mode on a **384-well** plate.
Upload one or more xPONENT plate-result CSVs and get back a
self-contained interactive HTML report organised into **three tabs**:

### 1 · Plate Report

- **Plate metadata & count cards** — Plate ID, Batch, **Run date & time**
  (the parsed run start), Operator, Instrument, Operating mode, CSV file;
  a single row of count cards (total / PC / **each single-point control,
  e.g. Cholera Pool High / Cholera Pool Low** / NC / specimen / background
  wells, antigens); and a **shape-coded 384-well plate map**.
- **Bead Count** — a freeze-pane antigen × well tier heatmap (red < 30,
  yellow 30–49, green ≥ 50) ordered by plate position (A1 → last), a
  "how it works" box, and five summary cards.
- **Background QC** — per-antigen spread of the blank wells (per-well
  MFIs, SD, %CV, an intra-plate **High CV** flag, an inter-assay
  **High hist. CV** flag for run-to-run drift, and a `⚠ outlier` badge on
  antigens with a leave-one-out well outlier), plus a cross-plate overview
  with a **Median ± IQR / Per-plate data points** toggle.
- **Positive & Negative Control QC** — the same cross-plate overview for
  the single-point Cholera controls and the NC controls, plus an NC
  **duplicate-%CV** flag table.
- **Standard-Curve Summary + All-Curves Overview** — a logistic curve is
  fit for **every antigen against every control standard**, using the
  **5PL** (five-parameter, default) or **4PL** model, chosen per report on
  the home page. One sortable fit table per standard over all antigens
  (with a **Relevance** column), and **featured priority antigens**
  organised by standard, **one curve per row**. Each panel overlays **every
  other plate** (independent of run order) — its fitted curve in light grey
  **and its raw standard points as grey × markers**, so a plate whose standard
  is only a couple of dilutions and can't be fit (e.g. a NIBSC test plate) still
  compares point-to-point against the survey plates, both ways. When an **age
  file** is loaded, each featured curve shows an **age-stratified range-status
  bar chart** beside it.
- **Standard-Curve Picker** — type to inspect any antigen's curve, rug,
  and cross-plate overlays.

### 2 · Quality Assurance & Control

- **Plate Concordance** — a plate × plate heatmap of **Lin's concordance
  correlation coefficient (CCC)** on log₁₀ MFI. Each cell is the **mean of
  four controls' CCCs** — Negative 0 and Negative 49 across all antigens,
  and Cholera High and Cholera Low across the cholera antigens — green ≈
  1.0, red below the threshold; hover shows the four individual CCCs.
- **Flag summaries** — four tables for rerun decisions: **Sample check**
  (specimen wells with ≥ 1 QC flag), **Antigen check** (recurring
  problems), **Plate check** (per-plate overall / negative / cholera-pool
  concordance), and **Standard curve check** (starting-dilution %CV and
  cross-plate concordance per standard × antigen). **Every table has an
  Export CSV button** so flagged samples / antigens / plates / curves can
  be pulled out for closer examination.

### 3 · Background Correction Comparison

- Cross-plate concordance of the per-antigen mean **specimen** MFI under
  three background treatments — **Raw**, **Background-subtracted**, and
  **Background-divided** — on a linear scale, with **bootstrap 95 % CIs**,
  so you can see how each correction affects between-plate agreement.

No Python installation or internet connection required — runs as a
self-contained macOS `.app` or Windows `.exe`.

## Download & install

Download the latest build from the
[**Releases**](https://github.com/GenevaIDD/bangladesh-serosurveillance-luminex-qc/releases)
page (no Python or internet connection needed to run it).

**macOS** — download `Bangladesh-Serosurveillance-Luminex-QC-macOS.zip`:

1. Double-click the zip to unzip; you'll get **Bangladesh Serosurveillance
   Luminex QC.app**. Move it to `Applications` (optional).
2. The app is ad-hoc signed, so on first launch macOS will warn it's from an
   unidentified developer. **Right-click the app → Open → Open** (only needed
   the first time). If it's still blocked, open Terminal and run:
   ```bash
   xattr -cr "/Applications/Bangladesh Serosurveillance Luminex QC.app"
   open "/Applications/Bangladesh Serosurveillance Luminex QC.app"
   ```
3. Your browser opens automatically at the upload page.

**Windows** — download `Bangladesh-Serosurveillance-Luminex-QC-Windows.zip`:

1. Right-click the zip → **Extract All** to a folder.
2. Open the extracted `Bangladesh-Serosurveillance-Luminex-QC` folder and
   double-click **Bangladesh-Serosurveillance-Luminex-QC.exe**.
3. On first run, Windows SmartScreen may show "Windows protected your PC" —
   click **More info → Run anyway** (only needed the first time).
4. Your browser opens automatically at the upload page.

**Using it:** on the upload page, select one or more xPONENT plate-result CSVs
and click **Generate Report**. Optionally attach an **Individual age data CSV**
(see [Age stratification](#age-stratification)) — it is saved once and reused
for every plate. Reports and CSVs are saved under
`~/bangladesh-serosurveillance-luminex-qc-results/` (see [Output](#output)).
To quit, use the **Quit Application** button on the home page.

> If the Releases page is empty, no build has been published yet — see
> [Development](#development) to build locally, or push a `vX.Y.Z` tag to
> trigger the automated build/release workflow.

## Assay panel

The production panel is **202 antigens** (pilot plates ran fewer beads
because some bead-antigen reagents were in short supply). The panel is
**re-derived from the `Median` block header of each xPONENT CSV on every
ingest**, so the per-plate panel is always authoritative; the default
list in `src/config.py` is a display/fallback only. Families include
`ARB_`, `FLU_`, `HCoV_`/`SARS_`, `HEP_`, `HHV_`, `MAL_`, `NTD_`, `POX_`,
`RES_`, `STI_`, `TBD_`, `VPD_`, `CHO_`, `BAC_`, `ENT_`, `HAN_`, `OTH_`,
`TOXO_`, `CTRL_`.

## Plate layout & controls

384-well plate (rows A–P × columns 1–24). Wells are classified from the
`Sample` name in the CSV (no Intelliflex input file is required):

| Type | Sample name | Notes |
|------------------------|------------------------|------------------------|
| Background | `Background0` / `Background` | Plate blanks |
| Negative control (NC) | `Pilot Control: Negative 0 / 49 , 1:1000` · `Negative 0` / `Negative 49` | Pooled pre-2019 North American plasma; two controls, each in duplicate |
| PC / standard | `Pilot Control: <pool> <dilution>` · new machine names below | Multiple pooled controls, each its own dilution series |
| Specimen | `{id}_1:1000_IgG` · `{id}_r3_{Serum\|DBS}` | The newer machine runs a single IgG dilution; pilot ran each person as Serum + DBS |

**Two naming conventions are supported out of the box** (no config change
needed). The pilot prefixed every standard with `Pilot Control:`; the newer
machine names each standard by its target instead:

| Standard | Pilot name | New-machine name |
|---|---|---|
| Cholera + typhoid | `Anti-OSP & cTxB (± HlyE) pool 1:N`, `HlyE N ng/mL` | `mAb Mix N (CTXb.. / OSP.. / HlyE.. ng/mL)` |
| Dengue | `Dengue pool 1:N` | `Dengue 1:N` |
| VPDs (M/D/R/T) | `NIBSC pool 1:N` (combined) | `Measles` / `Diphtheria` / `Rubella` / `Tetanus 1:N` (one series each) |
| Cholera range markers | `Cholera High / Low` | `Cholera Pool High / Low` |

The `mAb Mix 1…8` series is a 4-fold serial dilution and is scored as a
relative dilution (point *N* → `4^(N-1)`), keeping cholera/typhoid on the same
relative (AU) footing as every other standard.

**Standards** each carry their dilution in the sample name (`1:N`, `N ng/mL`
for pilot HlyE, or the `mAb Mix N` relative series) and calibrate specific
pathogens:

-   **mAb Mix** → cholera (OSP / CtxB) and typhoid (HlyE), combined in one
    relative-dilution series (the pilot ran these as separate Anti-OSP & cTxB
    and HlyE series)
-   **Dengue** → dedicated dengue standard (DENV antigens)
-   **Measles / Diphtheria / Rubella / Tetanus** — dedicated NIBSC dilution
    series (or a pilot combined **NIBSC** pool) → those four VPDs
-   **Cholera Pool High / Low** — single-point range markers (not fit); also
    used as the cholera control for plate concordance

### Antigen → standard scoring (`pool_mode`, set in Settings)

A logistic curve (5PL by default, or 4PL — chosen per report) is fit for every
(standard × antigen). Two modes control how specimens are then scored:

-   **auto_select (default)** — each antigen is scored against the standard
    meant to calibrate it, parsed from the antigen name:
    -   **Cholera** (`CHO_` / CtxB / Inaba / Ogawa) → **mAb Mix**.
    -   **Typhoid** (`HlyE` / typhi) → **mAb Mix**.
    -   **Dengue** (`DENV1–4` / dengue) → the **dedicated Dengue** standard.
    -   **Measles / diphtheria / rubella / tetanus** VPDs (plus
        `RES_measles_lysate`) → their **dedicated NIBSC** dilution series (or a
        combined NIBSC series).
    -   **Non-dengue arboviruses** (`ARB_`), **all other VPDs** (`VPD_`
        pertussis / bordetella / meningitidis, …) and any antigen with no
        pathogen match have **no calibrating standard**: they are scored on a
        best-fitting curve only (viewable in the Picker and per-standard tables)
        and are never featured.

    The matched standard is chosen by pathogen name and is **independent of
    whether that curve fit on this run** (see *Results table* below). Refine
    the matching with a regex rules field and exact per-antigen overrides in
    Settings (or the YAML).
-   **per_pool** — "fit every standard × antigen, no matching." Every antigen
    is scored against a single **scoring pool** (by default the pool with the
    most passing fits; set `scoring_pool` to override). The downloadable
    **results** table is identical in either mode.

## QC checks

### Bead counts

`bead_count_min` (red below, default 30) and `bead_count_warn` (yellow
below / green at-or-above, default 50). The heatmap is antigens × wells,
with wells ordered by plate position (A1 → last). Five summary cards report
**wells with ≥ 1 critically-low antigen**, the number of **critically low**
(< 30) and **low** (30–49) grid cells, and the **antigens** and **specimens**
flagged when ≥ `problem_fraction_threshold` (default 20 %) of their cells are
red or yellow.

### Standard-curve fit quality

Each antigen's fit (5PL or 4PL) is `fit_ok` only when all of: R² ≥ 0.95
(log10), IC50 inside the tested dilution range (×3 margin), Hill slope 0.3–5.0,
dynamic range ≥ 3× (the 5PL asymmetry `g` is bounded to 0.1–10 during the fit).
A failing fit can retry by dropping a single outlier point (configurable). The
Summary's Fit-OK column has three states: **OK**, **FAIL** (a curve was fit but
failed a criterion), and **NO_FIT** (no curve could be fit at all). Each report
uses one model throughout — there is no per-antigen fallback.

### Range classification

Per (specimen × antigen): `IN_RANGE` / `BELOW_RANGE` / `ABOVE_RANGE` /
`NO_FIT`, from the specimen MFI against the standard curve's reportable-range
MFI bounds. LLOQ / ULOQ come from a ±30 % (configurable) Obs/Exp recovery
check. The **per-standard Range-problem specimens** subsection flags a well
for a standard when ≥ `problem_fraction_threshold` of that standard's
**dedicated** antigens read out of range.

### Background QC

Per-antigen SD / %CV across the blank wells, the individual MFIs, and the
current-plate vs previous-plate IQR. Rows are flagged for high **intra-plate
%CV** (> `bg_cv_threshold`), high **inter-assay %CV** (> `hist_cv_threshold`,
run-to-run drift), and a **single-well outlier** (leave-one-out). The max-MFI
(default 300, dashed line) and %CV thresholds are reference values — **formal
Background pass/fail flagging is still in development**.

### Negative control

NC wells (matching `Negative`) are tracked per antigen across plates, each
control kept separate. Because each control has only two wells, disagreement is
flagged by **duplicate %CV** (> `nc_cv_threshold`, default 25 %).

### Plate & standard-curve concordance (QA tab)

Cross-plate agreement is measured with **Lin's CCC** on log₁₀ MFI and needs
**≥ 2 plates**. The combined heatmap cell is the mean of the four controls'
CCCs; the **Plate check** table breaks this into overall / negative /
cholera-pool columns (flagged below `concordance_threshold`). The **Standard
curve check** flags each standard × antigen curve whose starting-dilution MFI
%CV or cross-plate CCC crosses its threshold.

## Age stratification

An optional **Individual age data CSV** (uploaded once on the home page) is a
participant form with one row per individual: a **blood-sample collection id**
and an **age in years**. Specimens are matched to it by the leading token of
the sample name (`DH1867` in `DH1867_1:1000_IgG`). When present, each featured
standard curve in the All-Curves Overview shows a horizontal **range-status by
age group** bar chart beside it (age groups: 6 mo–2 y, 3–4 y, 5–14 y, 15+).
The file is saved to `results/age_data.csv` and reused for every plate; upload
it on its own and click **Regenerate All** to add age bars to existing reports.

## Output

All persistent data is stored under
`~/bangladesh-serosurveillance-luminex-qc-results/`:

```         
  reports/
    QC_<plate_id>.html              # interactive report (3 tabs)
    results_<plate_id>.csv          # canonical results table (wide by standard)
    in_range_<plate_id>.csv         # IN/BELOW/ABOVE/NO_FIT per (specimen × antigen)
    pct_in_range_<plate_id>.csv     # per-antigen %-in-range
    bead_problems_*.csv / bead_problem_{antigens,samples}_*.csv
    range_problem_{antigens,samples}_*.csv
    background_qc_<plate_id>.csv
    pc_single_point_<plate_id>.csv
    nc_levels_<plate_id>.csv
  history/                          # cross-plate JSON (per-standard fit/curve, background, specimen, NC)
  uploads/                          # uploaded CSVs kept for Regenerate All
  age_data.csv                      # the individual age form (if uploaded)
  config.yaml                       # user settings overrides
```

### The canonical results table

`results_<plate_id>.csv` is the single, analysis-ready results
representation — one row per **(specimen well × antigen)**, **wide by
standard**. The same table is served by the per-plate **Download CSV**
button and the **Export All** ZIP, so downloads never disagree. Columns:

`plate_id, well, sample_id, analyte, mfi, net_mfi, result_type,
reporting_standard`, then, for **every** standard on the plate,
`AU_<standard>` and `status_<standard>` (underscore-only names, valid
identifiers in R / pandas).

- **Every antigen × standard AU is shown**, regardless of whether that
  standard is the antigen's dedicated one — nothing is hidden.
- **`reporting_standard`** points to the standard the antigen is *designed*
  to report against (its dedicated calibrator, matched by pathogen name),
  **independent of whether that curve fit this run** — read the value from
  the matching `AU_<standard>` / `status_<standard>` columns (which read
  `NO_FIT` when the fit failed). Blank only for antigens with no dedicated
  standard.
- **`result_type`** is the reliability tier: `quantitative` (dedicated
  standard), `semi-quantitative` (legacy shared reference pool — pilot data
  only), or `qualitative` (no calibrator; best-fit AU only).
- Empty AU cells are left blank (R reads them as `NA`).

### Export All Processed Data (.zip)

The home-page **Export All Processed Data (.zip)** button bundles **one CSV
per table, combined across all plates**, into a single ZIP: `results`, the QC
tables (`in_range`, `pct_in_range`, `range_problem_antigens/samples`,
`background_qc`, `bead_problem_antigens/samples`, `bead_problems`,
`pc_single_point`), `standard_curve_params`, `standard_curve_data`, and
`nc_levels`. CSVs are instant to build, have no Excel-engine dependency, and
load directly in R / pandas (or Excel, one file at a time). Older per-plate
result CSVs written by a previous app version are skipped from the combined
`results` table — **Regenerate All** to bring every plate onto the current
schema.

## Settings

Editable on the Settings page (persisted to `config.yaml`):
well-classification patterns, the **standard-curve model** (5PL default / 4PL),
the **pool mode** (auto_select / per_pool) with scoring pool, regex rules and
per-antigen overrides, excluded analytes, bead-count thresholds, problem-fraction
threshold, background **intra-assay %CV**, **inter-assay %CV**, and max-MFI
reference thresholds, the **PC/NC intra-assay %CV** threshold, recovery tolerance,
the single-outlier drop toggle, and the (informational-only) specimen dilution.
Every threshold shown in the report is read from these settings.

## Development

``` bash
git clone https://github.com/GenevaIDD/bangladesh-serosurveillance-luminex-qc.git
cd bangladesh-serosurveillance-luminex-qc
uv sync
uv run python -m src.main          # dev server
```

Build standalone apps:

``` bash
# macOS
uv run python -m PyInstaller bangladesh-serosurveillance-luminex-qc.spec --clean -y
codesign --force --deep --sign - "dist/Bangladesh Serosurveillance Luminex QC.app"
# Windows
python -m PyInstaller bangladesh-serosurveillance-luminex-qc-win.spec --clean -y
```

## Tech stack

pandas, scipy (`curve_fit` on log10 MFI; curve fits run in parallel across CPU
cores), plotly + matplotlib, Flask, Jinja2, PyYAML, openpyxl, PyInstaller.

## Contact

**Andrew Azman** —
[andrew.azman\@unige.ch](mailto:andrew.azman@unige.ch) Geneva Disease
Dynamics Group, Institute of Global Health, University of Geneva

## License

Developed for internal use by the Geneva Disease Dynamics Group (and
friends).
