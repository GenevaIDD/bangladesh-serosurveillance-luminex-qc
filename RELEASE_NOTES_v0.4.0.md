# v0.4.0 — Bangladesh Serosurveillance Luminex QC Tool

Focused on the going-forward (new-machine) workflow: a single, consistent
results export, a dedicated Quality Assurance & Control tab, cross-plate
standard comparison, and support for new plate types.

## Highlights

- **One canonical results table.** The per-plate CSV, the per-report download,
  and the "Export All" bundle now serve the **same** table — one row per
  specimen × antigen, **wide by standard**: `plate_id, well, sample_id, analyte,
  mfi, net_mfi, result_type, reporting_standard`, then `AU_<standard>` and
  `status_<standard>` for **every** standard. Every antigen × standard value is
  shown; `reporting_standard` points to the antigen's intended calibrator and
  `result_type` is its reliability tier (quantitative / semi-quantitative /
  qualitative). Underscore-only column names for clean loading in R / pandas.
- **Export All Processed Data is now a ZIP of CSVs** (one per table, combined
  across plates) — instant to build, no Excel-engine dependency. Replaces the
  slow single-workbook export.
- **Three-tab report:** Plate Report · **Quality Assurance & Control** ·
  **Background Correction Comparison**.
  - **QA & QC tab:** plate concordance heatmap (Lin's CCC), plus Sample / Antigen
    / Plate / Standard-curve check tables — **each downloadable as CSV**.
  - **Background Correction Comparison tab:** cross-plate agreement of specimen
    MFIs under raw / background-subtracted / background-divided, with bootstrap
    95% CIs.
- **Two-way cross-plate standard comparison.** Each featured curve panel overlays
  **every other plate** — fitted curves *and* raw standard points (grey ×) —
  independent of run order, so point-only standards (e.g. a NIBSC test plate that
  can't be fit) compare against the survey plates and vice versa.
- **Age-stratified range-status bars** beside each featured curve when an
  individual age CSV is loaded on the home page.
- **New-machine standard support** (no config change): target-named standards
  (`mAb Mix`, `Dengue`, `Measles/Diphtheria/Rubella/Tetanus`, `Cholera Pool
  High/Low`), plus provenance-labelled reference standards
  (`Measles 1:125_..._NIBSC_SERUM`) tracked as their own comparable entities.
- **5PL is the default curve model** (4PL optional, per report); fits run in
  parallel across CPU cores.

## Fixes

- Reports whose plate name contains spaces (e.g. `NIBSC test plate_15.9.26`) now
  open and download correctly (previously "Report not found").
- Named test/QC plates no longer shift the survey plates' numbering (e.g. Plate 3
  staying Plate 3, not becoming Plate 4).
- Cholera-pool concordance now recognises the new `Cholera Pool High/Low` control
  names.
- Curve grids for standards that can't be fit are skipped with a note (large
  standards-only plates render in seconds instead of minutes).
- Clearer "Regenerate All" message when a plate's source CSV is missing.

## Notes

- The separate `specimens_*.csv` and `results_wide_*` exports are retired; the
  canonical results table replaces them (`net_mfi` folded in).
- The home-page Intelliflex-inputfile and Sample/Barcode-map uploads were removed
  (not used for the Bangladesh panel).
