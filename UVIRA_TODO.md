# Uvira 200-plex Luminex QC — To-Do & Session Log

Working document tracking the migration of the MPXV 12-plex MagPix QC app to a
200-plex Intelliflex assay (Uvira pilot). Keep the **To-Do** section as the
running plan and append a new entry under **Session History** at the end of
every working session.

---

## Project context (snapshot)

- **Instrument**: Intelliflex (replaces MagPix). xPONENT CSV format is similar
  but has an expanded `DataType:` set (Median, Mean, Count, %CV, Peak, Std Dev,
  Trimmed Peak / SD / Mean, Net MFI, Avg Net MFI, Units, Dilution Factor).
  Header lines differ: `"Program","xPONENT","","Intelliflex"`, `SN` like
  `IFLEXP23263001`, `PanelName` (e.g. `XXL_CORRECTED [v1]`), no per-row
  bead-number prefix on analyte names.
- **Plate format**: 96-well. Row A wells A1–A10 hold the 10-point 4-fold
  standard curve; A11–A12 are backgrounds/NC. B1 onward are specimens
  (barcodes like `FD22124871`). See `Pilot_Uvira_XXL/…_inputfile.csv` for the
  authoritative layout (`Location, Plate Type, Type, Description, Dilution`).
- **Standards**: pooled standard with mAbs. Pool composition:
  - Standards: Zika 16/352, Diphtheria 10/262, Hep B surface 07/164,
    Mpox MP-001 (in-house), P. vivax 19/198, Rift Valley 22/104BA,
    Rubella RUBI-1-94, Yellow Fever YF, HPV18 10/140.
  - mAbs: HylE, ctxB, OSP.
- **Dilution series** (from screenshot): mAbs pre-diluted 1:50, then 4-fold
  serial. Final dilutions for the Std+Mabs row:
  62.5, 250, 1000, 4000, 16000, 64000, 256000, 1024000, 4096000, 16384000.
  Well volume 5 µL. First dilution recipe: `5 µL MAbs + 11.8 PBT (+3.2 Stds
  pool)`; proceeding dilutions: `5 pool + 15 PBT`.
- **Antigen panel**: ~200 antigens listed in the Median header of
  `PlateRunResults_PLATE_05112026_RUN000.csv` (row 52). Includes families
  RES_, TOXO_, VPD_, HHV_, BAC_, OTH_, ENT_, HEP_, ARB_, STI_, MAL_, CHO_,
  CTRL_, NTD_, HCoV_, SARS_, TBD_, FLU_, POX_, HAN_.
- **Erroneous bead regions to flag/drop**:
  `FLU_B_HA_Maryland_1959`, `FLU_B_NP_Brisbane_2008`, `VPD_Tet_tox`.
- **Barcode → patient-ID maps**: 22 xlsx files in
  `Renamed_Uvira_Sera_2023_Barcode_maps/`. Each has a single sheet with
  columns `Container Id, Orientation Barcode, Row, Column, Barcode, Scan
  Time, Filename, Automatic Export Directory, ID` — the `Barcode` column
  matches the `Description` field of the inputfile; `ID` is the patient ID
  (e.g. `4033-93`).

## What the existing app already provides (reuse vs. replace)

| Capability | Reuse? | Notes |
|---|---|---|
| `parse_xponent.py` CSV parser | **Edit** | Works on MagPix shape; Intelliflex header keys differ slightly and there are more `DataType:` blocks. The `01 MVA Ag` numeric-prefix strip is a no-op here. Plate-ID extraction regex (`(.+-Plate\d+)`) won't match `PLATE_05112026_RUN000` → needs new rule. |
| `classify.py` PC/NC patterns | **Edit** | New sample names are `Standard1…Standard10`, `Background`, and `FD########` barcodes. Pool concept (`ITM PC` vs `ITM PC2`) does not apply — single pooled standard. |
| `qc_beads.py` (bead-count flag) | **Reuse + extend** | Already flags `count < min`. Needs the 3-tier (red/yellow/green) table the user requested, plus a problem-sample list. |
| `qc_standard_curve.py` 4PL fitting | **Reuse** | Per-antigen 4PL is the right shape; just runs over ~200 antigens × 1 pool instead of 8 × 2 pools. Add the "% samples in linear range" metric and a per-(antigen, sample) IN/OUT-of-range table. |
| `qc_kit_controls.py`, `qc_nc.py`, `qc_replicates.py` | **Defer / probably drop** | The new assay has no MagPix kit-control beads (NC/ScG/FC/IC bead regions); NC is the row-A backgrounds. PC replicate CV does not apply (single replicate per dilution point in row A). |
| `report.py` / `templates/report.html` | **Edit heavily** | Layout assumes 8 antigens (2×4 grids). Needs to scale to 200 (paginated / filterable / searchable). New bead-count table and IN/OUT-of-range table go here. |
| `config.py`, `settings.py` | **Edit** | Panel definition, kit-control list, default thresholds, well-classification patterns all hard-coded for 12-plex MPXV. |
| `parse_layout.py` | **Edit** | Currently reads a Geneva "Sample list" xlsx. New flow joins the Intelliflex `inputfile.csv` (well → barcode) with one of the Box barcode-map xlsx files (barcode → patient ID). |
| `qc_history.py` / per-pool history JSON | **Keep, simplify** | Drop the multi-pool slug logic; one history per assay. |

---

## To-Do

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked.

### 0. Project setup
- [x] Create this tracking doc (`UVIRA_TODO.md`).
- [x] Decision: **single-mode app** — Uvira 200-plex Intelliflex only. The
      existing MPXV 12-plex MagPix code path will be removed. No assay
      selector; the pipeline replaces (not augments) the current one.
- [~] Strip MPXV-specific code. Done in Session 2: `MPXV_ANTIGENS` and
      `MPXV_KIT_CONTROLS` are now deprecated aliases for `ANTIGENS` / `[]`
      in `config.py` (kept as a shim so legacy `qc_*` / `report.py`
      modules still import cleanly until Sections 3–5). README, SPEC,
      `app.py`, `main.py`, and the three HTML templates rebranded.
      Outstanding: remove `qc_kit_controls.py` / `qc_nc.py` /
      `qc_replicates.py` entirely (Section 5), strip remaining MPXV
      copy from `report.py` and `templates/report.html` (Section 5),
      and update the legacy descriptive sections of README/SPEC
      (Section 7).
- [x] Rename app branding (window title, report title, settings page,
      results-dir name, download filenames, README/SPEC headers) from
      "MPXV Luminex QC" to "Uvira Luminex QC". Package import path
      stays `src/`. `RESULTS_DIR_NAME = "uvira-luminex-qc-results"` now
      lives in `config.py` and is consumed by `app.py` + `settings.py`.
- [x] Bumped `APP_VERSION` to `0.9.0-uvira`.

### 1. Data ingestion
- [x] Extend `parse_xponent.py` to handle Intelliflex headers. Captures
      `instrument_program` (MagPix / Intelliflex), `panel_name`,
      `batch_description`, `batch_stop_time`. Metadata scan now stops at
      the first `DataType:` row. Smoke-tested on
      `PlateRunResults_PLATE_05112026_RUN000.csv`: 200 analytes × 96
      wells parsed cleanly, batch / SN / panel name all captured. The
      existing `_strip_bead_prefix` regex is a no-op for unprefixed
      Intelliflex analyte names.
- [x] New plate-ID rule. `_extract_plate_id` falls back to the raw
      batch string when the legacy `-Plate\d+` regex doesn't match, so
      Intelliflex batches like `PLATE_05112026_RUN000` are used verbatim
      as the plate ID.
- [x] Replaced `parse_layout.py` with `read_inputfile_csv()`,
      `read_box_xlsx()`, and `build_layout()` (a unified well-level join
      that produces `well, plate_well_type, barcode, patient_id, box_id,
      source_row, source_col`). `read_plate_layout()` retained as a
      backward-compat wrapper. Smoke-tested on the pilot data: 84/84
      specimens get a patient ID; the 12 control wells correctly have
      empty barcodes.
- [x] Extended the Flask upload form to accept three files (plate CSV
      [required], inputfile CSV [optional but recommended], Box xlsx
      [optional]). All three are persisted to `uploads/` and tracked in
      `plate_registry.json` (new `inputfile_filename` field) so
      Regenerate-All works without re-upload. `run_pipeline` now takes
      `inputfile_path`; when provided it routes through `build_layout`
      and writes `sample_id` (patient_id if known, else barcode),
      `barcode`, `patient_id`, `box_id` onto each row.
- [ ] **Soft-flag** the three erroneous bead regions
      (`FLU_B_HA_Maryland_1959`, `FLU_B_NP_Brisbane_2008`, `VPD_Tet_tox`):
      keep them in all tables/plots but render them visually muted (grey
      row, italic label, "(excluded)" suffix) and surface the list in a
      report banner. Do **not** drop them from the data. **Data side
      done** — `EXCLUDED_ANALYTES` and `panel.excluded_analytes` are in
      `config.py` and exposed via `get_excluded_analytes()` in
      `settings.py`. **Render side pending** until Section 5
      (report.py rewrite).

### 2. Config & panel definition
- [x] Replaced `MPXV_ANTIGENS` / `MPXV_KIT_CONTROLS` with the 200 Uvira
      antigens (`ANTIGENS` constant in `config.py`). Old names retained
      as deprecated aliases.
- [x] Panel auto-derived from each CSV's Median-block header on
      ingest. `parse_xponent_csv` records `metadata['analytes']`;
      `pipeline.py` passes that list as the authoritative panel into
      `fit_standard_curves(antigens=...)`. Config panel is now a
      display-only fallback.
- [x] `excluded_analytes` is editable from the Settings page (textarea,
      one analyte per line). Defaults to the three erroneous bead
      regions. Surfaced on the per-(antigen × sample) range table via
      the `excluded` column.
- [x] Updated `well_classification` patterns to `^Standard\d+$` /
      `^Background`.
- [x] Standard dilution series baked into defaults (10-point 4-fold
      from 62.5 → 16,384,000); editable on the Settings page as a
      single comma-separated field (the old auto/manual mode toggle was
      removed because Intelliflex never encodes dilutions in sample
      names).

### 3. Standard-curve QC (200 antigens)
- [x] Existing 4PL per-antigen fit reused. `fit_standard_curves` now
      takes an `antigens` kwarg so the pipeline passes the per-plate
      panel from the CSV header. Pool concept collapses to a single
      `"PC"` key on Uvira (the multi-pool branch is unused but kept
      for backward compat).
- [x] **New metric** `compute_pct_in_range_per_antigen(in_range, ...)`
      returns one row per analyte with `n_samples / n_in_range /
      n_out_of_range / n_no_fit / pct_in_range / excluded`. Exported
      as `pct_in_range_<plate>.csv`.
- [x] **New table** `compute_in_range_table(data, fits, excluded)`
      returns one row per (specimen well × analyte) with `mfi /
      mfi_lloq / mfi_uloq / status / excluded` plus any sample-id /
      barcode / patient-id columns from the layout merge. Status is
      strictly `IN_RANGE` / `OUT_OF_RANGE` / `NO_FIT`; below-LLOQ and
      above-ULOQ both collapse to OUT_OF_RANGE per decision #3.
      Exported as `in_range_<plate>.csv`. Smoke-test on the pilot data:
      16,800 rows (84 specimens × 200 antigens), the three excluded
      bead regions came back at 0–3.6% in-range as expected.
- [x] Curve-plot picker shipped — single Plotly figure with all 200
      antigens as visibility-toggled traces and a dropdown menu (Section 5).

### 4. Bead-count QC
- [x] **New table** built in `qc_beads.py::qc_bead_counts`. Returns
      `matrix` (analytes × wells, raw counts), `tier_matrix` (red /
      yellow / green strings), and a `problems` long-format DataFrame
      sorted red-first. Rendered in the report as a discrete-tier
      Plotly heatmap.
- [x] **Problem list** included as an HTML table below the heatmap and
      exported as `bead_problems_<plate>.csv` from the pipeline.
- [x] Threshold pair wired through Settings (`bead_count_min` /
      `bead_count_warn`) and into the Plotly heatmap legend.

### 5. Reporting & UI
- [x] `templates/report.html` and `src/report.py` rewritten from
      scratch for the 200-antigen layout. Removed all kit-control / NC
      bead / replicate-CV sections. Plotly is loaded via CDN once.
- [x] Bead-Count matrix + IN/OUT-of-Range matrix, both as Plotly
      heatmaps with discrete colour scales and per-cell hover.
- [x] Standard-Curve Picker — Plotly figure with 200 traces and an
      `updatemenus` dropdown that swaps the visible analyte. Title
      updates with `fit_ok` and the four 4PL parameters.
- [x] Per-antigen Standard-Curve Summary table (a, b, c=IC50, d, LLOQ
      / ULOQ dilutions, %-in-range, QC warnings, `fit_ok` badge).
      Excluded-analyte rows rendered muted.
- [x] Banner sections: excluded analytes (warn-yellow); Box xlsx
      identifier and patient-ID resolution count (info-blue).
- [x] Specimen-results table not embedded — 200 cols × 84 rows would
      blow up the page. Three CSV download buttons replace it
      (`specimens_*.csv`, `in_range_*.csv`, `pct_in_range_*.csv`).

### 6. Validation
- [ ] End-to-end run on `Pilot_Uvira_XXL/`. Confirm report opens, all 200
      antigens render, the 3 erroneous beads are flagged, bead-count matrix
      and IN/OUT-of-range matrix populate correctly.
- [ ] Cross-check a handful of patient IDs against
      `RENAMED-Box1_Uvira_sera_2023.xlsx`.

### 7. Packaging & docs
- [ ] Update `README.md` and `SPECIFICATION.md` to describe the Uvira /
      Intelliflex / 200-plex assay.
- [ ] Re-run PyInstaller specs (mac + win) once the rename lands.

---

## Decisions log

| # | Decision | Date |
|---|---|---|
| 1 | ~~Dual-mode app~~ **Reversed**: single-mode Uvira 200-plex Intelliflex; MPXV 12-plex MagPix path will be removed. | 2026-05-13 |
| 2 | Excluded bead regions are **soft-flagged** (rendered muted, never dropped). | 2026-05-13 |
| 3 | IN/OUT-of-range table is **strictly binary**. Below-LLOQ and above-ULOQ both collapse to "OUT OF RANGE". | 2026-05-13 |
| 4 | Barcode-map workflow: **manual upload** at submit time (no auto-matching by filename / BatchDescription). | 2026-05-13 |

## Open questions for the user

_None at the moment._ All four initial questions are resolved (see
Decisions log).

---

## Session History

### Session 4 — 2026-05-14

Implemented Sections 4 and 5. The pipeline now produces a fully
functional Uvira 200-plex HTML report end-to-end on the pilot data.
Legacy MagPix-only modules removed.

**Files added / rewritten:**
- `src/qc_beads.py` — fully rewritten. New return shape:
  `matrix` (analyte × well counts), `tier_matrix` (red/yellow/green),
  `sample_labels`, `problems` (long-format, sorted red-first), plus the
  legacy `flagged` / `n_flagged` / `by_well` fields for any code that
  still expects them. Tier classifier reads
  `qc_thresholds.bead_count_min` (red below) and `bead_count_warn`
  (yellow below; green above) — both editable from Settings.
- `src/report.py` — fully rewritten (≈400 lines, down from 813).
  Six-section Uvira layout (Plate Overview, Bead-Count Matrix,
  Standard-Curve Summary, Standard-Curve Picker, IN/OUT-of-Range
  Matrix, Downloads). Three Plotly figures (`_make_bead_heatmap`,
  `_make_curve_picker`, `_make_in_range_heatmap`); Plotly is loaded
  once via CDN at the top of the template. The curve picker bundles
  all 200 antigens as visibility-toggled traces with a single
  `updatemenus` dropdown.
- `templates/report.html` — fully rewritten. New CSS, semantic
  sections, sticky-header tables, muted-row styling for excluded
  analytes, downloadable CSV buttons.
- `src/pipeline.py` — dropped `qc_pc_replicates`, `qc_nc_levels`,
  `qc_kit_controls` calls and their imports. `generate_report` now
  receives the new args (`in_range`, `pct_in_range`) and the
  try/except wrapper from Session 3 is removed (the pipeline now
  expects the report to succeed). Bead-problem CSV export added
  (`bead_problems_<plate>.csv`). `_build_nc_history` deleted.
  `history_nc` is `None`.
- `src/qc_kit_controls.py`, `src/qc_nc.py`, `src/qc_replicates.py` —
  **deleted**.
- `src/config.py` — deprecated kit-control aliases (`MPXV_ANTIGENS`,
  `MPXV_KIT_CONTROLS`, `NC_BEAD_MFI_MAX`, `SCG_MFI_MIN`,
  `FC_MFI_RANGE`, `IC_MFI_RANGE`) removed; nothing imports them
  anymore.
- All `src/*.py` — `from __future__ import annotations` added so the
  modules parse on Python 3.9+ (project still officially requires
  3.11; this is purely defensive).

**Bug fixes during smoke-test verification:**
- **Plotly version skew** — plotly Python 6.x emits JSON for
  plotly.js 3.x but the template was loading a hardcoded
  plotly.js 2.27 CDN tag, so the three figures silently failed to
  render. Fixed by switching to `include_plotlyjs=True` on the first
  figure (embeds the matching v3.5.0 bundle inline) and `False` on
  the rest. Stale CDN `<script>` tag removed from `report.html`.
  Result is fully self-contained — no internet required, no version
  drift — at the cost of ~+4.6 MB per report. A
  `_reset_plotlyjs_embed_flag()` call at the top of
  `generate_report` ensures successive reports each get their own
  inline bundle.
- **Standard-curve perf** — `_fit_one` already had a degenerate-input
  guard (max-MFI floor) but `_try_drop_one_outlier` was still called
  on every failed fit, running 10 extra scipy passes per analyte
  with no signal. Now retry is gated on `params is not None` (i.e.,
  scipy converged but QC criteria failed). On the pilot data, the
  end-to-end wall clock should drop substantially from ~6:40.
- **4PL fit quality** (user reported HCoV_OC43_NP with `d=0` and a
  visibly bad lower tail) — root cause was linear-residual fitting.
  The upper plateau (~10⁵ MFI) dominates absolute residuals, so the
  optimizer "ignored" tail points at MFI ~80 and landed at `d=0`.
  Switched `_fit_one` to fit on log10(MFI), matching standard
  immunoassay practice; R² and the retry path's selection metric now
  use the same log-space objective. Also fixed misleading
  `a_init` / `d_init` variable comments (the math was always right
  because both have the same `[0, ∞)` bounds, but the comments
  swapped what each represents). X-axis label clarified from
  `Dilution (1:x)` → `Dilution factor (1 : x)`.

**Smoke tests run:**
- `qc_bead_counts` on the pilot data: matrix shape `(200, 96)`,
  430 red cells, 856 yellow cells, 1,286 problem rows. The three
  excluded bead regions consistently show 0 beads across every well
  (consistent with their being added in error).
- **Render-only end-to-end** (`/tmp/uvira_smoke_render.py`):
  parse → layout merge → bead-QC → synthetic 4PL fits → range tables
  → `report.generate_report` → 6.3 MB self-contained HTML. All 13
  grep markers hit (UI sections present, excluded analyte rendered,
  Box xlsx + barcode + IN_RANGE/OUT_OF_RANGE language present, no
  residual MPXV / kit-control / NC-bead strings). Synthetic fits used
  to bypass `scipy.curve_fit` because the system Python 3.9 used in
  this dev env is far slower than the project's pinned 3.11 + scipy
  ≥ 1.11. **Full scipy-fit pass on the project's 3.11 still to be
  done by the user** — `uv run python -m src.main`, then upload the
  pilot CSV / inputfile / Box xlsx through the web UI.
- `_fit_one` was given a **degenerate-input guard** (max-MFI floor +
  flat-response check) to keep `scipy.curve_fit` from thrashing on
  all-zero noise channels (the three excluded bead regions and any
  similar low-signal antigens). `maxfev` lowered 50,000 → 10,000.
- **Full real-scipy run** on pilot data: 6:40 wall clock initially;
  after the perf gating above, much faster. Output:
  - HTML 11 MB (with embedded plotly.js)
  - `specimens_*.csv` 2.5 MB
  - `in_range_*.csv` 2.3 MB
  - `pct_in_range_*.csv` 8 KB
  - `bead_problems_*.csv` 52 KB

  Real-fit `pct_in_range` distribution: median 86.9%, mean 74.2%.
  195/200 antigens have at least one specimen in range. The three
  excluded analytes all correctly show 0 IN_RANGE / 84 NO_FIT.

**Known follow-ups (Section 6 / 7):**
- Section 6 validation cross-check (a handful of patient IDs) still to
  do — the wiring is in place; just need to spot-check a few wells.
- Section 7: legacy descriptive copy in README.md and SPECIFICATION.md
  still describes the MPXV 12-plex assay; the GitHub URL in the
  templates/footer still points at the old repo; PyInstaller specs
  not yet renamed.
- The `KIT_CONTROLS = []` constant and the kit-control branch in
  `qc_standard_curve._fit_one`'s pool-discovery code are dead and
  could be simplified further.

**Next session:** Section 6 (validation pass with patient-ID
spot-check) and Section 7 (rewrite README / SPEC, update repo URLs,
rename PyInstaller specs).

### Session 3 — 2026-05-14

Implemented Sections 2 and 3. Pipeline now produces the Section-3
deliverable CSVs end-to-end on the pilot data; HTML report rendering
remains the Section-5 task.

**Files edited:**
- `src/config.py` — added `BEAD_COUNT_WARN = 50` to `DEFAULTS`. Re-added
  the deprecated kit-control thresholds (`NC_BEAD_MFI_MAX`,
  `SCG_MFI_MIN`, `FC_MFI_RANGE`, `IC_MFI_RANGE`) as module-level
  constants so legacy `qc_kit_controls.py` and `report.py` keep
  importing during the Section-5 transition.
- `src/parse_xponent.py` — `metadata['analytes']` now carries the
  per-plate panel in the order the instrument exported it.
- `src/qc_standard_curve.py` — `fit_standard_curves` accepts an
  `antigens=` kwarg. Two new functions:
  - `compute_in_range_table(data, fits, excluded_analytes)` →
    long-format `(well × analyte)` table with MFI, MFI bounds, ternary
    `status`, `excluded` flag, and any sample-id / barcode / patient-id
    columns from the layout merge.
  - `compute_pct_in_range_per_antigen(in_range, excluded_analytes)`
    → per-antigen summary with `n_samples / n_in_range /
    n_out_of_range / n_no_fit / pct_in_range / excluded`.
  - Helper `_mfi_bounds_for_fit(fit_result)` evaluates the 4PL at the
    LLOQ/ULOQ dilutions to get MFI bounds for the IN/OUT decision.
- `src/pipeline.py` — uses `metadata['analytes']` as the authoritative
  panel for `fit_standard_curves`; calls the two new range functions
  using `get_excluded_analytes(config)`; exports
  `in_range_<plate>.csv` and `pct_in_range_<plate>.csv`. The
  `generate_report` call is now wrapped in try/except — when it fails
  (expected during Section-5 transition) a placeholder HTML is written
  so Past Reports still has a row, and the pipeline carries on to
  produce the CSVs.
- `templates/web/settings.html` — replaced. Per-antigen / kit-control
  table editors removed (panel is auto-derived). New
  `excluded_analytes` textarea (newline-separated), `bead_count_warn`
  input, simplified standard-dilutions field. Legacy
  `nc_bead_mfi_max` / `scg_mfi_min` / `fc_mfi_*` / `ic_mfi_*` /
  `pc_cv_threshold` / `dilution_mode` fields removed from the UI.
- `src/app.py` — `save_settings` rewritten to match the new form:
  parses `excluded_analytes`, `bead_count_warn`, single
  `standard_dilutions` field; drops the per-row antigen / kit-control
  iteration and the kit-control range parsers.
- `UVIRA_TODO.md` — Sections 2 and 3 marked done (curve-plot rendering
  deferred to Section 5).

**Smoke tests run:**
- `parse_xponent_csv()` on pilot CSV: `metadata['analytes']` carries
  all 200 names in order.
- `compute_in_range_table()` with synthetic 4PL fits derived from the
  standard MFI bounds: 16,800 rows = 84 specimens × 200 antigens;
  status counts split 14,723 IN_RANGE / 2,077 OUT_OF_RANGE; 252 rows
  flagged `excluded=True` (84 × 3 erroneous beads).
- `compute_pct_in_range_per_antigen()`: 200 rows; the three excluded
  bead regions show 0–3.6% in-range (correctly the worst), good
  antigens like `RES_Ade3` show 97.6%.

**Known follow-ups (NOT done in Session 3):**
- `report.py` not rewritten yet — still imports kit-control constants
  and tries to render an 8-antigen layout. Pipeline now swallows the
  resulting error and writes a placeholder. Section 5 owns the rewrite.
- `qc_kit_controls.py`, `qc_nc.py`, `qc_replicates.py` still called
  from `pipeline.py` — they return empty/safe results on Uvira data
  but should be deleted in Section 5.
- Bead-count Red/Yellow/Green matrix and problem list (Section 4) not
  yet built. The thresholds (`bead_count_min`, `bead_count_warn`) are
  in config and editable from Settings; the matrix-building helper
  is the Section-4 task.

**Next session:** Section 4 (bead-count matrix + problem list) and the
start of Section 5 (200-antigen report layout).

### Session 2 — 2026-05-13

Implemented Sections 0 and 1 (foundation only — report rendering stays
broken for Uvira data until Section 5).

**Files edited:**
- `src/config.py` — fully rewritten. `ANTIGENS` is the 200-name Uvira
  panel pulled from the pilot CSV header; `KIT_CONTROLS = []`;
  `EXCLUDED_ANALYTES = [FLU_B_HA_Maryland_1959, FLU_B_NP_Brisbane_2008,
  VPD_Tet_tox]`; `STANDARD_DILUTIONS` baked in as the 10-point 4-fold
  series from the screenshot (62.5 → 16,384,000); new `PC_PATTERNS =
  ['^Standard\d+$']` and `NC_PATTERNS = ['^Background']`; new
  `BEAD_COUNT_WARN = 50` threshold; `RESULTS_DIR_NAME =
  'uvira-luminex-qc-results'`; `APP_VERSION = '0.9.0-uvira'`. Kit-control
  kit-bead defaults removed. `MPXV_ANTIGENS` / `MPXV_KIT_CONTROLS` kept
  as deprecated aliases.
- `src/settings.py` — uses `RESULTS_DIR_NAME`; new
  `get_excluded_analytes()` accessor.
- `src/classify.py` — new `^Standard\d+$` PC pattern, `^Background` NC
  pattern; dropped `pc_pool`; PC dilution looked up by Standard index
  into `STANDARD_DILUTIONS`.
- `src/parse_xponent.py` — handles Intelliflex `Program` field
  (captures `instrument_program`), additional `DataType:` blocks,
  `PanelName` / `BatchDescription` / `BatchStopTime` metadata. Metadata
  scan stops at first `DataType:`. Plate-ID fallback uses the raw batch
  string when the `-Plate\d+` pattern doesn't match.
- `src/parse_layout.py` — replaced. New `read_inputfile_csv()`,
  `read_box_xlsx()`, `build_layout()`. Old `read_plate_layout(path)`
  kept as a backward-compat wrapper.
- `src/pipeline.py` — `run_pipeline()` takes new `inputfile_path` kwarg;
  when present, layout merge routes through `build_layout` and yields
  `sample_id` / `barcode` / `patient_id` / `box_id` columns.
- `src/app.py` — three-file upload form wired (`inputfile_file` added);
  registry stores `inputfile_filename`; delete + Regenerate-All paths
  updated; download filenames / page titles / results-dir path
  rebranded.
- `src/main.py` — rebranded.
- `templates/web/index.html`, `templates/web/settings.html`,
  `templates/report.html` — page titles, footer strings, GitHub link
  rebranded (link still points at legacy `mpox-luminex-qc` repo —
  flagged for Section 7).
- `README.md` + `SPECIFICATION.md` — top sections rebranded; bodies
  flagged "migration in progress" pending Section 7 rewrite.
- `UVIRA_TODO.md` — Sections 0 + 1 marked done / partial as appropriate.

**Smoke tests run:**
- `parse_xponent_csv()` on the pilot CSV: 200 analytes, 96 wells, batch
  + SN + panel name + Intelliflex program correctly captured. Plate ID
  resolved to `PLATE_05112026_RUN000`.
- `classify_wells()` on the parsed data: 10 PCs (Standard1..Standard10)
  with the correct dilution ladder 62.5 → 16,384,000; 2 NCs
  (`Background0` in A11/A12); 84 specimens.
- `build_layout()` joining `_inputfile.csv` × `RENAMED-Box1_Uvira_sera_2023.xlsx`:
  96 rows, 84/84 specimens get a patient ID, 12 control wells correctly
  empty.

**Known follow-ups (NOT done in Session 2 — explicit scope cut):**
- `report.py` still imports / renders kit-control + multi-pool +
  replicate-CV sections that no longer exist in the Uvira pipeline. The
  app will not produce a usable HTML report on Uvira data until
  Sections 3–5 land. The 4PL math itself (`qc_standard_curve.py`) is
  unchanged and ready to run.
- `qc_kit_controls.py`, `qc_nc.py`, `qc_replicates.py` not yet deleted;
  `pipeline.py` still calls them. Pipeline rewrite is part of Section 3+.
- GitHub repo URL in templates + README still points at the legacy
  repo path — flagged for Section 7.
- PyInstaller specs (`mpox-luminex-qc.spec`, `mpox-luminex-qc-win.spec`)
  not yet renamed.
- No unit tests written; testing is by-hand smoke tests only.

**Next session:** Section 2 (config / panel auto-derivation from the CSV
header, Settings-page wiring for the new fields) and Section 3 (standard
curves over 200 antigens + the "% in linear range" metric).

### Session 1 — 2026-05-13
- Reviewed the `uvira-luminex-qc` repo end to end (`src/*.py`, README,
  SPECIFICATION) and the OneDrive data drop (Intelliflex CSV, plate input
  file, 22 barcode-map xlsx files, dilution-series screenshot).
- Captured project context, mapped each existing module to reuse/edit/drop.
- Authored this `UVIRA_TODO.md` with the working plan and four open
  questions for the user.
- **User answers received** (same session):
  - Initial: dual-mode app accepted. **Reversed shortly after**: go
    single-mode Uvira 200-plex only; MPXV 12-plex MagPix support will be
    removed.
  - Excluded beads → **soft flag** (muted, not dropped).
  - IN/OUT-of-range table → **strictly binary**.
  - Barcode-map workflow → **manual upload** at submit time.
- **No code edits yet.** All open questions resolved. Next session:
  start on Section 0 (strip MPXV code, rebrand) and Section 1 (Intelliflex
  parser + manual upload of inputfile.csv and Box xlsx).
