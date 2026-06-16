# Bangladesh National Serosurveillance Luminex QC — To-Do & Session Log

Working document tracking a **new project** forked from `uvira-luminex-qc`
(which was itself forked from the legacy `mpox-luminex-qc`). This app provides
automated QC for **202-plex Luminex immunoassays run on a 384-well plate** for
the Bangladesh National Serosurveillance project.

Keep the **To-Do** section as the running plan and append a new entry under
**Session History** at the end of every working session. Mirror the conventions
of `UVIRA_TODO.md`.

> **STATUS: PLAN FOR REVIEW (Session 0).** Nothing in the code has been changed
> yet beyond the folder fork. The sections below are the proposed plan. Please
> review, edit, and confirm before implementation begins.

---

## Project context (snapshot)

- **Lineage**: `mpox-luminex-qc` (12-plex MPXV, MagPix, **multi-pool** standards
  "ITM PC"/"ITM PC2") → `uvira-luminex-qc` (200-plex, Intelliflex pilot,
  **single** `Standard1..10` series) → **this repo** (Bangladesh national
  serosurveillance, 384-well, **multi-pool** standards). Bangladesh is in some
  ways closer to the *legacy mpox* multi-pool design than to Uvira — the two
  attached screenshots ("ITM PC" / "ITM PC2" small-multiples with the green
  linear-range square, red out-of-tolerance triangles, and "×" excluded point)
  are exactly the legacy multi-pool curve grid we want to reproduce.

### Confirmed from the two pilot CSVs (parsed 2026-06-01)
- **Plate format**: **384-well, rows A–P (16) × columns 1–24 (24)**. Header
  declares `ProtocolPlate … Type,384`. Plate 1 (`…21.8.25`) fills A–P
  (346 wells); Plate 2 (`…25.8.25`) fills A–N (316 wells). Uvira's hard-coded
  96-well (8×12) plate map + several heatmap layouts MUST be generalized to 16×24
  (well-position regex is `[A-H]\d+` today → needs A–P / 1–24).
- **Panel**: both pilots expose **200 analytes** in the `Median` header (Uvira's
  exact same 200-name panel, `RES_Ade3 …`). The brief says "202-plex" — likely
  the production panel adds 2 antigens. Panel is auto-derived per ingest, so this
  is not blocking, but the default `ANTIGENS` list and "202" branding should be
  reconciled (see Open questions). DataType blocks present: Median, Mean, Count,
  Avg MFI, %CV, Peak, Std Dev, Trimmed Peak/SD/Mean, Net MFI, Avg Net MFI, Units,
  Dilution Factor. Operating mode: `FLEXMAP 3D® High PMT`. SN `IFLEXS23121001`.
  Batch e.g. `PLATE_08212025_RUN000`.
- **NO `inputfile.csv` was provided** — well classification must come from the
  `Sample` name in the CSV (regex), not an authoritative `Type` column.
- **Sample naming is entirely different from Uvira** (no `Standard1..10`):
  - **Background** → `Background0` (wells A1–A4). 4 wells per plate.
  - **Standards / PC = MULTIPLE distinct pools, each its own dilution series,
    with the dilution encoded in the sample name**:
    - `Pilot Control: Anti-OSP & cTxB (& HlyE) pool … 1:1 … 1:16384` (8-pt)
    - `Pilot Control: Dengue pool 1:1000 … 1:16384000` (8-pt)
    - `Pilot Control: Orpal pool 1:100 … 1:102400` (11-pt)
    - `Pilot Control: HlyE 0.39…50 ng/mL` (8-pt concentration series, Plate 1)
    - `Pilot Control: Cholera High/Low (1:1000)` (single points)
  - **Negative controls (NC)** → `Pilot Control: Negative 0 , 1:1000` and
    `Pilot Control: Negative 49 , 1:1000`. 4 NC wells per plate.
  - **Specimens** → `{id}_r3_{Serum|DBS}` (e.g. `10012_r3_Serum`,
    `10012_r3_DBS`). Each specimen appears as BOTH a Serum and a DBS sample.
    ~248–250 specimen wells per plate.
- **Implication — multi-pool standards return.** The Uvira single-series logic
  is insufficient. We need to: (a) parse the **pool name** and **dilution** from
  each PC sample name, (b) fit a 4PL per (pool × antigen), and (c) revive the
  per-pool history slug logic that Uvira simplified away (Section 1 / 5 below).
- **Priority pathogens (NEW concept)**: each pool targets specific pathogens
  (Dengue pool → dengue antigens; Anti-OSP/cTxB/HlyE & Orpal → cholera/typhoid;
  etc.). Only priority (pool × antigen) curves are meant to be *interpreted*.
  Curves are still *fit* for all antigens; Summary / All-Curves Overview show
  priority antigens by default. Default = all antigens until the team defines the
  pool→antigen priority mapping.
- **Dev fixtures**: the two pilot CSVs above now live in `tests/fixtures/`.
  No barcode map / patient-ID join yet (specimen IDs are in the sample name).

### Study design & controls (from project protocol, 2026-06-01)
- **Instrument / mode**: Intelliflex, **High PMT (enhanced) mode only** — all
  cross-sectional V. cholerae models were built on high-sensitivity mode for its
  higher MFI and greater dynamic range. Bead reagents mixed once weekly.
- **Production panel = 202-plex.** The pilots ran fewer beads because some
  bead-antigen reagents (e.g. MSP1, SARS-CoV-2) were in short supply; excluding
  low-volume beads was acceptable. So: brand the app "202-plex", but keep the
  panel **auto-derived from each CSV header** (pilots legitimately show ~200).
- **Goal**: quantify Relative Antibody Units (RAU) / Antibody Units (AU) and
  estimate seroprevalence/seroincidence. Final assay uses cholera + typhoid
  mAbs and icddr,b dengue pooled controls; Richelle Charles (RC) protocol is the
  study protocol.
- **Intended plate layout (well budget)**: Blank 4; V. cholerae OSP+CTXB mAbs 16;
  Typhoid HlyE mAbs 16; OSP+CTXB+HlyE combined mAbs 16; individual dengue
  controls 56 (28 samples ×2); Dengue pooled serum control 16; ORPAL controls 22;
  DBS SeroChit 124; Serum SeroChit 124; V. cholerae pooled serum High/Low 4
  (2 high, 2 low); Negative controls 4.
- **Control intent (drives the pool → priority-antigen mapping)**:
  - **V. cholerae mAbs** (OSP IgG + CTXB IgG; ±HlyE) → cholera antigens (OSP/CtxB);
    high/low pooled serum marks the detectable range.
  - **Typhoid HlyE mAbs** (8-pt dilution series) → S. typhi HlyE. Pilot tests
    whether HlyE can be combined in-well with cholera mAbs vs run separately.
  - **Dengue pooled serum** + **individual dengue controls** (28 PCR-confirmed,
    serotype counts DENV1=3, DENV2=21, DENV3=4, DENV4=0) → DENV antigens.
  - **ORPAL controls** (White lab, limited stock) → dengue/flavivirus;
    used to cross-validate the icddr,b dengue pool.
  - **Negative** = pooled North American plasma collected pre-2019 (also a
    SARS-CoV-2-naïve control for future work).
- **Two pilot plates have different purposes**:
  - **Plate 1**: cholera controls; compares **Michael White vs Richelle Charles
    protocols** by MFI concordance (study will use RC; scaling factor TBD).
  - **Plate 2**: blank + negatives + the 28 individual dengue controls in
    duplicate; RC protocol, 202-plex reagents; characterizes the dengue control
    pool (primary vs secondary infection, cross-reactivity by serotype).

## What the existing (Uvira) app provides — reuse vs. replace

| Capability | File(s) | Plan |
|---|---|---|
| xPONENT CSV parser | `parse_xponent.py` | **Edit** — generalize well-position parsing to A–P / 1–24; confirm plate-ID extraction on Bangladesh batch strings. |
| Well classification (PC/NC/specimen) | `classify.py` | **Rewrite patterns** — no input file; classify from `Sample` name: Background=`^Background`, NC=`Negative`, PC=`^Pilot Control:` (minus NC), specimen=rest. Add pool-name + dilution parsing. |
| Bead-count QC | `qc_beads.py` | **Reuse + relabel** — logic stays; card copy and thresholds clarified/made configurable. |
| Standard-curve 4PL fitting | `qc_standard_curve.py` | **Extend to multi-pool** — fit 4PL per (pool × antigen) with per-pool dilution series; add priority filtering; expose `reportable_range` for the linear-range square. Revive multi-pool slug logic (mpox-style). |
| Multi-pool history slugs | `qc_history.py`, `pipeline.py` | **Revive** — Uvira dropped per-pool slugs; Bangladesh needs them back (one history per pool). |
| Background QC | `qc_background.py` | **Edit** — default max-MFI → 300; add per-plate & previous-plate IQR; drop mean/max columns + max flag from table. |
| Cross-plate history | `qc_history.py`, `pipeline.py` | **Reuse** — already persists background/specimen/std/nc history per output dir; reused for IQR comparison. |
| Report generator | `report.py`, `templates/report.html` | **Edit heavily** — section reorder, 384 plate map (shape-coded + hover + scroll), bead-count relabel, background IQR plot + folded table, priority-antigen curves, interactive All-Curves Overview, folded picker, range-matrix axis change. |
| Settings page | `templates/web/settings.html`, `config.py`, `settings.py`, `app.py` | **Edit** — add priority-pathogen list, background max-MFI, and make all flag thresholds editable. |
| Branding / paths | everywhere | **Edit** — rename "Uvira Luminex QC" → "Bangladesh Serosurveillance Luminex QC"; `RESULTS_DIR_NAME`; window/report titles; README/SPEC; .spec files; .Rproj. |

---

## To-Do

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked.

### 11. Docs, downloads, master export, cleanup — DONE (Session 11)
- [x] **README.md + SPECIFICATION.md** rewritten for the Bangladesh 202-plex /
      384-well / High-PMT / multi-pool assay (sections, pools, auto pool-select,
      outputs, settings, build). No Uvira/MPXV copy.
- [x] **Per-plate download CSVs fixed**: report links point to
      `/download/specimens/<f>`, but only `specimens_*.csv` was mirrored to
      `specimens/` — the rest live in `reports/`. `download_specimens` now checks
      both dirs. Verified all 9 links return 200.
- [x] **Clean master CSV (with RAU)**: new per-plate `results_<plate>.csv`
      (`_build_clean_results`) — plate, well, sample_id, matrix, analyte, pool,
      mfi, RAU, status, censored. `/export/all` now leads with a concatenated
      **results** sheet (+ specimens / curve params / curve data / nc_levels);
      fixed the NC history filename (`nc_well_history.json`). Verified via Flask.
- [x] **Code cleanup**: removed dead `_make_nc_heatmap`, `get_kit_control_names`,
      `KIT_CONTROLS`/`ALL_BEADS`, `PC_CV_THRESHOLD`/`pc_cv_threshold`,
      `STANDARD_DILUTIONS` (+ the dead `standard_dilutions` settings handler) and
      the unused `replicate_qc`/`kit_controls` report params. Imports clean.

### 0. Project setup & rebranding
- [x] Fork folder from `uvira-luminex-qc` → `bangladesh-serosurveillance-luminex-qc`.
- [x] Create this tracking doc (`BANGLADESH_TODO.md`) with the plan.
- [x] Rebrand (Session 1): `RESULTS_DIR_NAME` →
      `bangladesh-serosurveillance-luminex-qc-results`; app/window/report/settings
      titles; download filename prefixes; `.spec` files renamed + internal names;
      `APP_VERSION = "0.1.0-bangladesh"`; assay name/description; pyproject; GitHub
      URL. `report.py` module docstring.
- [x] Rewrite `README.md` + `SPECIFICATION.md` for the 202-plex / 384-well /
      Bangladesh context (remove Uvira/MPXV-specific copy entirely). DONE
      Session 11.
- [x] Legacy docs moved to `legacy/` (UVIRA_TODO + PLATE_RUN_FINDINGS .md/.html).
      Pilot CSVs copied to `tests/fixtures/`.

### 1. 384-well + multi-pool foundation (do first)
- [x] Generalize well parsing in `parse_xponent.py` `_parse_well_from_location`
      to accept rows A–P and columns 1–24.
- [x] Plate-geometry inferred from the data (snaps to 96 or 384) in `report.py`
      `_make_plate_layout_overview` (replaces hard-coded 8×12). *(Full shape-coded
      redesign is Section 2; this is the geometry groundwork.)*
- [ ] Audit remaining heatmaps for 384 scale. *(Bead/range/NC heatmaps already use
      first-seen well order + dynamic height, so they render; revisit visual
      density in Sections 3/6.)*
- [x] **Rewrote `classify.py` patterns** for Bangladesh sample names
      (Background0 / Negative / Pilot Control / `{id}_r3_{Serum|DBS}`), checked
      background→nc→pc→specimen with `re.search`. Defaults in `config.py`,
      editable in Settings.
- [x] **Pool + dilution parser** (`_parse_pc` in `classify.py`): extracts pool
      label (parenthetical stripped), dilution (`1:N`), or concentration
      (`N ng/mL` → `pc_x_kind='concentration'` for HlyE); flags single-point
      controls (`pc_single_point`). Verified on both pilots: pools, dilutions,
      x-kinds, single-points all parse correctly.
- [x] **Multi-pool standard-curve fitting + per-pool history** working. Single-
      point pools dropped from fitting; pools with <4 dilution points → NO_FIT
      (no crash). Per-pool `fit_history_*` / `std_curve_history_*` JSON written.
      Verified: Dengue pool fits its DENV antigens (15/15 on subset), cholera/
      typhoid pool does not (1/15) — confirms the priority-pathogen concept.

- [x] **Auto antigen→pool selection** (`select_pool_per_antigen`): each antigen
      is scored against the curve of the pool meant to calibrate it. Pathogen
      group parsed from the antigen name (dengue / cholera / typhoid), matched to
      pools by name; **ties and unmatched antigens broken by best fit (fit_ok then
      highest R²)**. Runs as the default; overridable via
      `config['panel']['pool_antigen_overrides']` (antigen→pool) once the team
      signs off. `compute_in_range_table` + `compute_concentrations` now use this
      per-antigen mapping instead of `pools[0]`. R² stored in each fit result.

> **Section 1 verification (Session 1):** both pilots parse (Plate 1: 90 PC /
> 4 BG / 4 NC / 248 specimen wells; Plate 2: 58 / 4 / 4 / 250). Full 200-antigen
> × multi-pool fit + history completes. `generate_report` runs on the multi-pool
> /384 data. Auto pool-selection verified: DENV NS1 → Dengue pool (R²≈0.999),
> DENV VLP → Orpal pool (best-fit tiebreak), HlyE → HlyE pool, CtxB → cholera
> pool; plain `rau` for a DENV antigen correctly equals its selected pool's AU.

### 2. Plate Overview section (rebuild) — DONE (Session 2)
- [x] **Metadata table** (replaced inline header grid): Plate ID, Batch, Run
      date, Operator, Instrument (+ SN), Operating mode (with Low-PMT badge),
      CSV file, Panel.
- [x] **Number cards**: total wells, PC (standard) wells, NC wells, specimen
      wells, antigens analysed — from `plate_counts` in `report.py`. Verified on
      Plate 1: 346 / 90 / 4 / 248 / 200.
- [x] **384 plate map** rebuilt as a shape-coded Plotly scatter:
      circle = PC/standard, ✕ = NC, square = specimen, open square = background.
      No sample labels; hover shows well position + sample ID + type. Geometry
      inferred (96 or 384), equal-aspect, wrapped in a horizontally/vertically
      scrolling container (max-height 560px).

### 3. Bead Count section (move to 2nd; relabel) — DONE (Session 3)
- [x] Reordered: Bead Count now comes immediately after Plate Overview, before
      Background QC (template blocks swapped + figure-build order updated in
      `report.py` for the Plotly embed-first invariant; section comments
      renumbered 1–9).
- [x] Rewrote the four cards with self-explanatory copy (thresholds live from
      settings): "Antigens flagged (≥X% of wells have either 30–49 beads or
      <30 beads)", "Specimens flagged (≥X% of antigens …)", "Overall cells with
      bead count <30 (red cells)", "Overall cells with bead count 30–49 (yellow
      cells)". Numbers come from `bead_count_min`/`bead_count_warn`/
      `problem_fraction_threshold`. Cards forced to a 4-column row.
- [x] **Bead-count heatmap**: x-axis shows the **well location only** (no sample
      ID); hover shows Antigen, Well, Sample, Bead count, Tier.
- [x] **Wide-matrix legibility + frozen antigen labels**: matrix rendered as two
      row-aligned panes — a fixed antigen-label column on the left (frozen) and
      the heatmap (wells) in a horizontal-scroll pane beside it; both share an
      outer vertical-scroll box. Fonts 7px, cells 10px rows × 9px cols. Page
      width unaffected (`min-width:0` on the content grid track + on the scroll
      pane). Label pane uses a wide left margin so long antigen names aren't
      clipped and sit flush against the cells.
- [x] Heatmap + problem tables render at 384 scale.

### 4. Background QC section (after Bead Count; substantial edits) — DONE (Session 4)
- [x] **Default max-MFI threshold → 300** (`bg_max_mfi`) in `config.py`,
      `qc_background.py`, `pipeline.py`, `report.py` fallback, and `settings.html`.
- [x] **Rewrote the "How Background QC works" description**: dropped the
      confusing mean/max points; now describes within-plate spread (individual
      MFIs, SD, %CV) and the this-plate-vs-history IQR comparison, and states
      that formal pass/fail flagging is still in development (max-MFI is a
      tracked reference only). No stale copy left.
- [x] **Overview plot redesigned** (`_bg_overview_iqr` + branch in
      `_make_background_overview_plot`): < 3 plates → existing dot scatter;
      ≥ 3 plates → grey vertical bar = previous-plates IQR (Q1–Q3, current
      excluded) + current-plate mean dot; dots **outside the IQR flagged** in
      red (provisional, "flagging in development" note). Verified with a
      synthetic 3-plate history.
- [x] **Per-antigen table rebuilt + folded** (click to expand, scrollable both
      ways). Dropped Mean MFI, Max MFI, and the MAX/CV flag column. Columns now:
      Analyte → n wells → Individual MFIs → SD → %CV → IQR current plate (Q1–Q3
      of this plate's Background wells) → IQR previous plates (Q1–Q3 of per-plate
      mean across earlier plates). Flags deferred — noted in code + UI.
- [x] Cards replaced with neutral info (antigens w/ Background data, Background
      wells this plate, previous plates in history) — no premature pass/fail.

### 5. Standard curves — multi-pool + priority-pathogen concept — DONE (Session 5)
- [x] **Multi-pool fitting** (Section 1): 4PL per (pool × antigen); single-point
      controls excluded from fitting.
- [x] **Settings: priority pathogens** — new textarea (`panel.priority_antigens`,
      default empty = all); wired through `settings.html`, `app.py`, and a
      `get_priority_antigens` getter. Persists to YAML.
- [x] **Per-antigen selected fit** (`_build_selected_fits`): each antigen shown
      against its auto-selected pool's curve (pool name injected); a single
      `selected_fits` dict feeds the Summary, Overview, and Picker.
- [x] **Standard Curve Summary** filtered to **priority antigens** (default all),
      with a new **Pool** column and a note that curves are fit for all antigens.
- [x] **All Curves Overview — interactive** (`_make_curve_grid_interactive`):
      Plotly small-multiples for priority antigens with hover, current-plate
      specimen **rug** (status-coloured), **linear-range green square**, red
      4PL line, blue observed points, **red triangles** for out-of-tolerance
      standards, **✕** for a dropped point. Falls back to a static grid (still
      with the square) above 48 panels (unfiltered default).
- [x] **Standard Curve Picker**: covers **all** antigens (each via its selected
      pool fit); **folded by default** with a "review only — only priority
      curves are interpretable" disclaimer.
- [x] Linear-range square **now also in the Standard-Curve Picker** (Session 9):
      per-antigen green reportable-range rectangle (log10 coords) appended to the
      rug-separator base shapes and swapped on typeahead via
      `Plotly.relayout(DIV,"shapes",…)`.

### 6. Standard-Curve Range Matrix + Serum/DBS pairing — DONE (Session 6)
- [x] Range Matrix rebuilt with the **frozen antigen-label** + horizontal-scroll
      pattern (shared `_frozen_label_heatmap` helper). Top axis shows the **well
      location only** (no sample-ID); hover shows Antigen, Well, Sample, Status
      (Below/In/Above range, No fit). Uses `sample_id` when present, else
      `sample_name`.
- [x] **Paired Serum-vs-DBS comparison** (`_make_serum_dbs_comparison`): folded
      sub-section under the Range Matrix. Parses `{id}_r3_{Serum|DBS}`
      (case-insensitive), pairs per person × antigen, and plots Serum MFI vs DBS
      MFI (scattergl) with a y=x reference line and per-point hover. Specimens
      still listed individually elsewhere.

### 7. Settings page — make thresholds editable — DONE (Session 7)
- [x] Priority-pathogen list (Section 5).
- [x] Background max-MFI threshold (default 300).
- [x] Bead-count thresholds (min/warn) — labels clarified ("RED below" / "YELLOW
      below"); read live from config in `qc_bead_counts`.
- [x] Problem-fraction (≥X%) threshold — present; read live in pipeline + report.
- [x] Background %CV threshold — present (reference only).
- [x] Recovery tolerance — present; drives LLOQ/ULOQ.
- [x] **Audit**: confirmed every threshold is read from config (bead via
      `qc_bead_counts`, problem-fraction/bg-cv/bg-max/recovery via
      `qc_thresholds`, priority via `panel`); none hard-coded in the report.
- [x] **Cleanup**: removed the now-unused "Standard Dilutions" field (dilutions
      are parsed from sample names per pool) and replaced it with an explanatory
      note; updated Well-Classification labels/copy for Bangladesh naming; marked
      Background thresholds as "reference (flagging in development)".
- [x] Verified Settings round-trip with a Flask test client (GET renders, POST
      persists all thresholds + priority list, reset restores defaults).

### 8. Descriptions audit (cross-cutting) — DONE (Session 8)
- [x] Reviewed every section's explanatory text against current behavior. Fixed:
      NC QC (Bangladesh `Negative` pattern, `Background0`, pre-2019 NA plasma, NC
      flagging-in-development note); Background QC download desc (flags are
      reference-only); Range-Matrix download desc (auto-selected pool; dropped
      Uvira barcode/patient_id/box_id wording); upload page (input-file + barcode
      map marked optional / not needed for Bangladesh).
- [x] Confirmed no stale Uvira / MPXV / MagPix / RENAMED / Row-A / Standard1 /
      12-plex copy remains in report.html, index.html, settings.html.

### 9. Validation
- [ ] Obtain a representative Bangladesh 384-well xPONENT CSV (+ input file +
      barcode map) and validate end-to-end.
- [ ] Verify plate map, well counts, and classification on real 384 data.
- [ ] Regression-check the Uvira fixtures still process (96-well path).

### 10. Deferred / future work (noted, not in this scope)
- [x] **PC Replicate Variability** — BUILT (Session 12). Standards are run in
      duplicate; `qc_pc_replicates` computes the %CV between the two replicate
      wells per (pool × antigen × dilution), flags points > `pc_cv_threshold`
      (default 0.20, editable in Settings), and the report shows a "PC replicate
      variability" subsection (cards + folded flagged-points table) with a
      `pc_replicates_*.csv` download.
- [~] Negative Control levels section — **reworked to the legacy MPOX style**
      (Session 9): per-antigen "NC MFI across plates" small-multiples (current
      plate red) + folded "NC details for this plate" (mean-MFI-by-analyte bar +
      Well/Analyte/MFI table). Deeper NC flagging (thresholds, drift) still TBD.
- [ ] Decide background-IQR out-of-range flagging rule.
- [ ] Decide final flag rules for the Background QC table.
- [ ] **Standard-Curve Picker performance at full panel scale.** Generating the
      full ~200-antigen report is slow (minutes); the picker builds a very large
      multi-trace Plotly figure (all antigens × pools + historical overlays).
      With a priority list set everything is fast. Optimize later (e.g. limit/
      lazy traces, or build the picker only for a capped set). Logged Session 5.
- [x] Add the green linear-range square inside the Picker's own curve panel —
      DONE Session 9.

---

## Decisions log
- **2026-06-01**: New project created as a fork of `uvira-luminex-qc`. Target
  assay is 202-plex on a 384-well plate for Bangladesh national
  serosurveillance. Plan drafted for review (this document).
- **2026-06-01**: Pilot CSVs parsed → assay is **multi-pool** (revive mpox-style
  per-pool fitting/history); 384-well A–P × 1–24; classify from sample name (no
  input file). Linear-range styling locked from screenshots.
- **2026-06-01**: Study protocol received. Production = 202-plex (pilots reduced
  by reagent shortage; panel auto-derived). High PMT only. Pool intents + plate
  well-budget recorded. Legacy docs moved to `legacy/`.
- **2026-06-02**: Plan finalized for build. HlyE → ng/mL axis; Serum/DBS = two
  specimens + folded paired comparison (Section 6); single-point controls =
  reference markers (no fit); no White-vs-RC view; bead-count heatmap loses the
  top sample-ID labels (keeps well location, sample id in hover). Priority
  antigens = fit-all + user Settings filter. Ready to start Sections 0 & 1.

## Open questions for the user
**Resolved 2026-06-01:** screenshots received (green linear-range square + red
out-of-tolerance triangles + "×" excluded point — see Section 5); priority-
pathogen default = all antigens; IQR = Tukey Q1–Q3 on per-plate mean background
MFI per antigen, previous-plate IQR excludes the current plate, current plate is
the overlaid dot; flag current-plate dot when outside historical IQR (with a
"more BG flags in development" note); 384 layout confirmed (A–P × 1–24); keep
legacy docs in a `legacy/` folder.

**Resolved 2026-06-01 (study protocol):** production is **202-plex**; pilots ran
fewer beads due to reagent shortage (auto-derive panel, brand as 202). High PMT
only. NC = pooled pre-2019 North American plasma (`Negative 0`/`Negative 49` —
treat both as NC). Pool intents now known (cholera mAbs → OSP/CtxB; HlyE →
S. typhi HlyE; Dengue pool + individual dengue + ORPAL → DENV; Cholera High/Low =
range markers). Serum & DBS are both SeroChit specimens (124 each).

**Resolved 2026-06-02:**
- **Priority antigens**: always fit every pool × antigen; the priority list is a
  *display filter* the user sets in Settings (default = all). Exact list TBD by
  team but does not block the build.
- **No White-vs-RC concordance view** in the QC tool — that's a separate
  analysis done outside this app.
- **Dilution x-axis** (FINAL): `1:N` is the curve x-axis. **HlyE** is fit on its
  own **ng/mL concentration axis**, shown in the same curve grid with different
  x-units. Everything else uses dilution.
- **Serum vs DBS** (FINAL): treated as **two independent specimens**, clearly
  labeled `{id} (Serum)` / `{id} (DBS)` (casing normalized). **Plus** a
  **paired serum-vs-DBS comparison in a folded sub-section/tab** (per-person
  serum MFI vs DBS MFI). See Section 6.
- **Single-point controls** (FINAL): Cholera High/Low and combined-mAb
  singletons shown as **reference markers**, no curve fit.

**Resolved 2026-06-02 (auto pool-selection):** specimens are scored against the
pool that calibrates each antigen, auto-derived by parsing the pathogen name and
tie-breaking by best fit (default on). Team can later override per antigen and
confirm the prefix→pathogen rules in Settings.

**Still open (non-blocking):**
1. **Pool → priority-antigen mapping (exact lists)**: **Decision (Session 13):
   default mode is `per_pool` — fit & show a curve for EVERY (pool × antigen),
   NO matching or auto-selection.** Auto-select remains available as a Settings
   option. Caveat (documented in the report): pools have different dilution
   ranges (Dengue 1:1k–16M, ORPAL 1:100–102k, OSP/cTxB 1:1–16k, HlyE ng/mL), so
   RAU is anchored per pool and not comparable across pools; specimen RAU/range
   use a single configurable scoring pool. Once the team confirms the
   pool→antigen mapping, switch to a per-antigen intended calibrator.

---

## Session History

### Session 15 — 2026-06-02 (CI release workflow for Mac/Windows builds)
- Rewrote the inherited `.github/workflows/build.yml` (was still MPXV-branded:
  wrong spec filenames, `MPXV Luminex QC.app`, MPXV zip/artifact names) for the
  Bangladesh app: builds `bangladesh-serosurveillance-luminex-qc.spec` (macOS
  `.app`, ad-hoc codesigned + zipped) and `…-win.spec` (Windows folder zipped),
  uploads artifacts, and on a `v*` tag publishes a GitHub Release with both zips.
  Also runs on `workflow_dispatch`.
- Added `src.qc_pc_replicates` to the `hiddenimports` of both `.spec` files (new
  module this project; would otherwise risk a missing-import in the frozen app).
- Verified all build inputs exist (run.py, make_icon.py, icons .icns/.ico,
  templates, static/vendor, SPECIFICATION.md) and the workflow YAML is valid.
- Note: builds run on GitHub's macOS/Windows runners — push the repo + a `vX.Y.Z`
  tag (or run the workflow manually) to produce the downloadable apps. No native
  build was possible in this Linux sandbox.
- Added a **"Download & install"** section to the README (Releases link + macOS
  right-click-Open / `xattr` and Windows SmartScreen first-launch steps).
- Smoke-tested: app imports + boots (home + settings pages 200). All session
  changes are still **uncommitted/local**; CI has not run yet (no tags).

### Session 14 — 2026-06-02 (Regex pool-assignment rules in Settings)
- Documented how `auto_select` works (antigen-name pathogen group → pools whose
  name targets that group → best-fit tie-break → fallback).
- Added a **Settings "Pool assignment rules"** textarea: `"<regex> => <pool>"`,
  one per line, first match wins. In `select_pool_per_antigen` the order is now:
  (1) exact `pool_antigen_overrides`, (2) **user regex rules** (`_parse_pool_rules`),
  (3) built-in pathogen heuristic, (4) best-fit fallback. Lets the lab define the
  antigen→pool mapping explicitly without code (and sidesteps the keyword
  heuristic's edge cases). Config `panel.pool_assignment_rules` + app.py parse.
- Verified: a rule `ARB_DENV.* => Orpal pool` forces all DENV antigens to ORPAL;
  `RES_Ade.* => Dengue pool` assigns antigens the heuristic wouldn't match;
  settings round-trip + reset OK.

### Session 13 — 2026-06-02 (Per-pool curve mode — no matching/auto-select)
- **Decision reversed**: do NOT auto-select a pool per antigen for the interim.
  New default **`pool_mode = "per_pool"`**: a 4PL is fit and shown for EVERY
  (pool × antigen), with no pathogen matching and no best-fit pick.
  - Standard-Curve Summary → one row per (pool × antigen) (Pool column; %-in-range
    omitted since it's a single-pool metric).
  - All-Curves Overview → one curve grid **per pool** (legacy ITM-style), each
    with its hover / rug / linear-range square.
  - Picker / cross-run / Range Matrix / RAU → scored against a single
    **scoring pool** (`panel.scoring_pool`; blank → the pool with the most
    fit_ok antigens, via `default_scoring_pool`). Per-pool AU columns remain in
    specimens CSV; clean results uses the scoring pool.
- **Settings**: added `pool_mode` (per_pool | auto_select) dropdown + `scoring_pool`
  field; wired through `app.py`; verified round-trip + reset → per_pool.
- Refactor: `compute_in_range_table` / `compute_concentrations` /
  `_build_clean_results` now take an explicit `pool_map`; `build_pool_map`
  applies the mode. `auto_select` mode preserved (banner explains each mode).
- Fixed a `html` name-shadowing bug (`html = template.render` shadowed the
  `import html` used by the per-pool heading escape) → render var renamed.
- Verified both modes render on the pilot (per-pool: 5 pool grids + per-(pool×
  antigen) summary; auto_select: single grid + Pool column).
- **Bug fix**: in per-pool mode every pool's interactive grid was emitted with
  the same Plotly div id (`fig-curve-grid`), so only the first pool's grid
  rendered and the rest were blank. Threaded a unique `div_id` per pool
  (`fig-curve-grid-{i}`) through `_make_curve_grid` → all pool grids now render.

### Session 12 — 2026-06-02 (PC replicate QC + pool-group fix + threshold restore)
- Confirmed standards run in **duplicate** (2 wells per pool × dilution).
- Restored `PC_CV_THRESHOLD` (default 0.20) — now a real, consumed threshold —
  + Settings field + POST handler.
- New **`qc_pc_replicates`** module: %CV between duplicate standard wells per
  (pool × antigen × dilution); per-point table + per-(pool × antigen) summary.
  Wired into the pipeline (`pc_replicates_*.csv` export) and a "PC replicate
  variability" subsection in the report (cards + folded flagged-points table +
  download). Verified end-to-end + settings round-trip.
- **Bug fix**: `_antigen_group` was tagging Borrelia `TBD_OspA`/`OspC` as
  *cholera* via a bare "OSP" substring. Cholera now keys on the `CHO_` prefix /
  cholera-specific tokens (CtxB/Inaba/Ogawa/cholera/vibrio); verified TBD_Osp*
  → None, CHO_Inaba_OSP → cholera.
- Clarified the pool-column question: full-panel selected-pool distribution is
  150 Dengue / 44 Orpal / 2 Anti-OSP&cTxB / 1 HlyE / 1 combined — the cholera/
  typhoid pools map only to their targets; the rest fall back to the broadly-
  reactive pooled sera. (Earlier "only Dengue/Orpal" was a 12-antigen preview
  artifact.)

### Session 11 — 2026-06-01 (Docs + downloads + master CSV + cleanup)
- Rewrote README.md + SPECIFICATION.md for Bangladesh (202-plex / 384-well /
  High PMT / multi-pool; sections, pools, auto pool-selection, outputs, build).
- Fixed all per-plate CSV download links (`download_specimens` now serves from
  both `specimens/` and `reports/`) — verified 9/9 return 200.
- Added clean master `results_<plate>.csv` (`_build_clean_results`: well ×
  antigen with pool, MFI, **RAU**, status, censored, Serum/DBS matrix) and made
  `/export/all` lead with a concatenated **results** sheet; fixed NC history
  filename. Verified the workbook via a Flask test client.
- Code cleanup: removed dead `_make_nc_heatmap`, `get_kit_control_names`,
  `KIT_CONTROLS`/`ALL_BEADS`, `PC_CV_THRESHOLD`, `STANDARD_DILUTIONS`, the dead
  `standard_dilutions` settings handler, and unused `replicate_qc`/`kit_controls`
  report params. All modules import cleanly.
- This completes the planned scope (Sections 0–11). Remaining items are the
  deferred/in-development ones in Section 10 (Background/NC flagging rules, PC
  replicate variability, picker performance, team pool→antigen mapping).

### Session 10 — 2026-06-01 (Picker rug alignment + NC controls split)
- **Picker rug/curve alignment**: curve and rug panels now pinned to the SAME
  explicit per-antigen log10 y-range (`_y_range_for`, computed from standards +
  current/historical specimen MFIs), set on load and via
  `Plotly.relayout({yaxis.range, yaxis2.range})` on each pick — guarantees a
  given MFI lands at the same height in both panels.
- **Picker linear-range square**: reimplemented as a per-antigen filled
  ("toself") trace toggled by the existing visibility scheme (the layout-shape +
  relayout approach wasn't rendering); `n_per_analyte` 2P+6 → 2P+7.
- **NC reworked per user decisions**: Negative 0 and Negative 49 kept **separate**
  (`_nc_control` parses the control; duplicate wells averaged within each
  control). Across-plate panels = static grid over **all** antigens, one coloured
  line per control, current-plate markers ringed. NC bar = grouped bars per
  control. NC table gained a **Control** column. Clarified the "dots = plates"
  point (preview used synthetic plates).
- Verified on Plate 1: 4 NC wells → Negative 0 / Negative 49; panels, grouped
  bar, and table all split by control.

### Session 9 — 2026-06-01 (Picker linear-range square + NC rework)
- **Picker linear-range square**: added a per-antigen green reportable-range
  rectangle to the Standard-Curve Picker (log10 coords on the log axes),
  appended to the static rug-separator shapes and swapped per antigen via
  `Plotly.relayout(DIV,"shapes",…)`; description updated.
- **NC QC reworked to the legacy MPOX style**: replaced the two purple heatmaps
  with (1) per-antigen "Negative Control MFI across plates" small-multiples
  (`_make_nc_history_plot` now a subplot grid; line + markers across plates,
  current plate red; bounded to priority antigens, capped at 48), and (2) a
  folded "NC details for this plate" containing a mean-NC-MFI-by-analyte bar
  (`_make_nc_bar`, scrollable) + a Well/Analyte/MFI table (`_format_nc_table`).
  Banner rewritten accordingly.
- Verified: picker carries shapes + relayout; NC panels/bar/table render; old
  `fig-nc-heatmap` removed.
- Remaining: README/SPEC rewrite for the Bangladesh context.

### Session 8 — 2026-06-01 (Section 8: Descriptions audit)
- Swept all report/upload copy for accuracy and stale Uvira/MPXV references:
  - NC QC banner rewritten (Bangladesh `Negative` pattern, `Background0`,
    pre-2019 NA plasma; "deeper NC QC in development" note; updated "no NC" copy).
  - Downloads: Background QC desc (flags reference-only), Range-Matrix desc
    (auto-selected pool; removed barcode/patient_id/box_id Uvira wording).
  - Upload page: input-file + barcode-map fields marked optional / not needed
    (wells classified from the sample name; IDs in `{id}_r3_{Serum|DBS}`).
- Verified report renders and a grep sweep finds no remaining
  Uvira/MPXV/MagPix/RENAMED/Row-A/Standard1/12-plex copy.
- Next: rewrite README.md + SPECIFICATION.md for the Bangladesh 202-plex / 384-
  well / multi-pool context (Section 0 leftover).

### Session 7 — 2026-06-01 (Section 7: Settings audit)
- Confirmed all flag thresholds are editable AND read live from config: bead
  RED/YELLOW (via `qc_bead_counts`), problem-fraction, background %CV, background
  max-MFI, recovery tolerance (via `qc_thresholds`), priority antigens (via
  `panel`). Nothing hard-coded in the report path.
- Cleaned the Settings page: removed the unused "Standard Dilutions" field
  (dilutions now parsed per-pool from sample names) → replaced with a note;
  rewrote Well-Classification labels/help for Bangladesh naming
  (`Background0` / `Pilot Control:` / `Negative` / `{id}_r3_{Serum|DBS}`);
  clarified bead labels ("RED below"/"YELLOW below"); marked the two Background
  thresholds as reference-only (flagging still in development).
- Verified the full Settings round-trip with a Flask test client (GET renders,
  POST persists every threshold + the priority list, reset restores defaults).
- Next: Section 8 (descriptions audit across all sections), then README / SPEC
  rewrite for the Bangladesh context.

### Session 6 — 2026-06-01 (Section 6: Range Matrix + Serum/DBS)
- Added shared **`_frozen_label_heatmap`** helper (frozen antigen-label pane +
  horizontal-scroll well pane); the Range Matrix now uses it — bare well-location
  top axis, hover = Antigen / Well / Sample / Status. (Bead matrix keeps its own
  equivalent inline version.)
- **`_make_serum_dbs_comparison`**: folded Serum-vs-DBS scatter (scattergl) under
  the Range Matrix — pairs `{id}_r3_{Serum|DBS}` per person × antigen, y=x
  reference, per-point hover. Hidden when no matched pairs exist.
- Clarified earlier preview confusion (Section 5): the "handful of antigens" was
  a fast-preview artifact (only ~10–24 antigens fit to dodge the 45 s tool cap);
  the real pipeline fits all ~200 (198/200 get a usable fit). Logged a picker
  performance follow-up (full-panel report is slow).
- Verified: range matrix frozen panes + enriched hover; serum/dbs section builds
  and pairs on the pilot specimens.
- **Follow-up (Section 6):** upgraded both the bead matrix and the range matrix
  to full **freeze panes** — promoted the helper to `_freeze_pane_heatmap`
  (frozen corner + frozen column header for well positions + frozen row header
  for antigens + scrolling body), with a small JS shim syncing the body's
  horizontal scroll → column header and vertical scroll → row header. Now both
  the antigen names AND the well positions stay visible while scrolling either
  way. Bead matrix retains its well-type group separators.
- Next: Section 7 (Settings completeness — confirm all flag thresholds editable)
  and Section 8 (descriptions audit), then README/SPEC rewrite.

### Session 5 — 2026-06-01 (Section 5: Standard curves)
- **Priority-pathogen setting**: `panel.priority_antigens` (default empty = all)
  added to config, `settings.html`, `app.py` POST, and `get_priority_antigens`.
- **`_build_selected_fits`**: per-antigen fit from its auto-selected pool (pool
  injected), shaped as a single-pool dict; one `selected_fits` feeds Summary /
  Overview / Picker. Priority list derived (panel order; empty = all).
- **Standard-Curve Summary**: now priority-filtered, with a **Pool** column and
  a "fit for all antigens / curves shown for priority" note.
- **All-Curves Overview** rebuilt: interactive Plotly small-multiples
  (`_make_curve_grid_interactive`) for ≤ 48 panels — hover, current-plate
  status-coloured **rug**, green **linear-range square**, red 4PL line, blue
  observed points, red-triangle out-of-tolerance standards, ✕ dropped point.
  `_make_curve_grid_static` keeps the matplotlib grid (now with the square) for
  larger/unfiltered sets. Linear-range geometry via `_linear_range_box`.
- **Standard-Curve Picker** folded by default with a "review only" disclaimer;
  now spans all antigens via their selected-pool fits.
- Verified: default (all) shows the Pool column + note; priority filter narrows
  the Summary/Overview to the chosen antigens; interactive grid carries the
  square + rug + out-of-tolerance markers; picker collapsed with disclaimer.
- Follow-up: add the linear-range square inside the picker curve too (deferred);
  PC Replicate Variability + NC levels still later (Section 9 / general).
- Next: Section 6 (Range Matrix axis change + Serum/DBS paired sub-section),
  then Section 7/8 (settings completeness + descriptions audit).

### Session 4 — 2026-06-01 (Section 3 finalize + Section 4: Background QC)
- Finalized Section 3 (bead matrix frozen labels + sizing) per user approval.
- **Section 4 — Background QC overhaul:**
  - Max-MFI default 100 → **300** everywhere (config, qc_background, pipeline,
    report fallback, settings.html).
  - `qc_background_levels` now returns the **individual Background-well MFIs**
    plus the current-plate **IQR (Q1/Q3)**; mean/sd/cv/max retained for the
    plot + history. Flagging columns kept for reference only (display deferred).
  - **Overview plot**: new `_bg_overview_iqr` — ≥3 plates shows previous-plate
    IQR bars (current excluded) + current-plate dot, outside-IQR dots flagged
    red; <3 plates keeps the dot scatter. `_make_background_overview_plot`
    branches on plate count.
  - **Description rewritten** (clear, accurate; no stale mean/max copy; states
    flagging is in development).
  - **Per-antigen table**: folded by default, scrollable; columns Analyte /
    n wells / Individual MFIs / SD / %CV / IQR current plate / IQR previous
    plates. Mean/Max/flag columns removed.
  - Cards now neutral (no premature pass/fail).
  - Verified: single-plate report renders (table + columns + note); ≥3-plate
    IQR overview + previous-plate IQR column verified with a synthetic history.
- Next: Section 5 (standard curves — multi-pool priority display, interactive
  All-Curves Overview with rug + linear-range square, folded picker).

### Session 3 — 2026-06-01 (Section 3: Bead Count)
- Reordered report: **Plate Overview → Bead Count → Background QC → …**
  (swapped the template `<details>` blocks, renumbered section comments 1–9, and
  reordered the figure builds in `report.py` so `bead_heatmap` is built before
  `bg_overview` — preserves the "Plotly.js embeds on first call" DOM invariant).
- Rewrote the four Bead Count cards in plain language (counts vs <30 / 30–49
  thresholds and the ≥X% flag, all from settings); fixed to a 4-column row.
- Bead-count heatmap: dropped the sample-ID text from the top axis (well
  location only); hover now shows Antigen / Well / Sample / Bead count / Tier.
- Left "red / yellow cell" wording only where it correctly names the heatmap
  tiers (the detail list + download descriptions), per the colour legend.
- Verified on Plate 1: DOM order correct, new card copy present, hover enriched.
- Plate Overview review fixes from last round also confirmed (compact 6-card row,
  top-centered plate-map legend, trimmed map description).
- **Review fixes (Section 3):** the wide bead heatmap was stretching the whole
  page — fixed with `min-width:0` on the `1fr` content grid track (and on the
  scroll pane). Reworked the matrix into a **frozen left antigen-label pane +
  horizontally-scrolling heatmap** (per user choice "antigens left, freeze
  them"), shrank fonts to 7px and cells to 10×9px, and fixed the large
  label↔cell gap (left-margin sizing) so long antigen names aren't clipped.
- Section 3 finalized and approved.
- Next: Section 4 (Background QC overhaul — max-MFI default 300, rewritten
  description, IQR overview plot, folded/scrollable table with individual MFIs +
  current/previous-plate IQR columns).

### Session 2 — 2026-06-01 (Section 2: Plate Overview rebuild)
- **Metadata table**: replaced the inline `meta-grid` with a table — Plate ID,
  Batch, Run date, Operator, Instrument (+SN), Operating mode (Low-PMT badge
  retained), CSV file, Panel.
- **Count cards**: total / PC / NC / specimen wells + antigens, computed as
  `plate_counts` in `generate_report`. Verified on Plate 1 (346/90/4/248/200).
- **Plate map** (`_make_plate_layout_overview`) fully rebuilt: shape-coded Plotly
  scatter (● PC, ✕ NC, ■ specimen, ▫ background), no labels, hover = well +
  sample ID + type, equal aspect, geometry auto (96/384), inside a both-axis
  scrolling container. Legend across the top.
- Verified: report renders with metadata table, correct card counts, and the
  scrollable shape-coded map.
- **Review fixes (Session 2)** from user screenshot: removed the redundant
  subtitle line under the title (it duplicated the metadata table); **removed the
  excluded-analytes concept** — emptied the leftover MPXV/Uvira default
  (`EXCLUDED_ANALYTES = []`), removed the Plate Overview banner and the stray
  excluded-analyte sentences in the Background QC / Standard-Curve descriptions;
  added a **Background (blank) wells** card so the cards reconcile to the total
  (90 PC + 4 NC + 248 specimen + 4 background = 346).
- Also explained the multi-pool auto pool-selection on the report (banner in
  Standard-Curve Summary + note in Range Matrix) — see Section 1 entry.
- Next: Section 3 (Bead Count — move above Background QC, relabel cards, drop
  top sample-ID labels on the heatmap, keep well location + richer hover).

### Session 1 — 2026-06-01 (Section 0 rebranding + Section 1 foundation)
- **Section 0 (rebranding)** complete: `config.py` (version `0.1.0-bangladesh`,
  `RESULTS_DIR_NAME`, assay name/description, panel/pattern docstrings), all
  user-facing titles in `templates/` + `src/main.py` + `src/app.py`, download
  filenames, `pyproject.toml`, GitHub URL, `.spec` files (renamed + internal app
  names + bundle id), `report.py` docstring. App imports + loads config cleanly.
- **Section 1 (384 + multi-pool foundation)** complete:
  - `parse_xponent.py`: well regex `[A-H]` → `[A-P]` (96- and 384-well).
  - `report.py`: plate-map geometry inferred from data (snaps 96↔384).
  - `classify.py`: full rewrite for Bangladesh sample names + `_parse_pc` pool/
    dilution/concentration/single-point parser. New columns `pc_pool`,
    `dilution`, `pc_single_point`, `pc_x_kind`.
  - `config.py`: Bangladesh well-classification patterns; added
    `panel.priority_antigens` (default `[]` = all).
  - `qc_standard_curve.py`: drop single-point pools from fitting; guard pools
    with <4 dilution points (→ NO_FIT, no crash). Multi-pool dict + per-pool
    history confirmed.
- **Verified** on both `tests/fixtures/` pilots: classification counts, 7/4-pool
  detection, dilution parsing, HlyE ng/mL axis, full fit + per-pool history, and
  `generate_report` on the multi-pool/384 data (tested on a 15-antigen subset for
  speed — full 200-antigen run works but takes minutes; the per-pool history
  files from the full run are the evidence it completes).
- **Auto antigen→pool selection added** (resolves the `pools[0]` follow-up):
  `select_pool_per_antigen` parses pathogen group from the antigen name, matches
  to target pools, tie-breaks by best fit (fit_ok then R²); overridable via
  `config['panel']['pool_antigen_overrides']`. Wired into `compute_in_range_table`
  + `compute_concentrations`. Verified per-antigen routing on Plate 1.
- **Explained on the report**: added an explanatory banner in the Standard-Curve
  Summary ("Multiple control pools — how each antigen is scored") that lists the
  detected pools, describes the name-match + best-fit-tiebreak rule, and shows how
  many antigens each pool was chosen to calibrate; plus a short cross-reference
  note in the Range Matrix. Driven by `_build_pool_selection_summary` →
  `pool_selection` template var. Banner only shows when >1 pool is present.
- Next: Section 2 (Plate Overview rebuild — metadata table, count cards,
  shape-coded scrollable 384 plate map with hover).

### Session 0 — 2026-06-01 (Project kickoff + plan)
- Folder forked from `uvira-luminex-qc`.
- Read and mapped the Uvira codebase: `config.py`, `settings.py`,
  `parse_xponent.py`, `classify.py`, `qc_*`, `pipeline.py`, `report.py`
  (full section map), `templates/report.html`, `templates/web/settings.html`,
  and the `UVIRA_TODO.md` history (through Session 19).
- Confirmed key facts: all requested Plate Overview metadata is already parsed;
  plate map + several heatmaps are hard-coded to 96-well (8×12) and need
  generalizing to 384-well (16×24); `reportable_range` (LLOQ/ULOQ) already
  available to drive the linear-range square; cross-plate history already
  persisted (reusable for IQR comparison).
- **Parsed the two pilot CSVs** and discovered Bangladesh is structurally closer
  to the legacy *multi-pool* mpox app than to Uvira: 384-well (A–P × 1–24), 200
  analytes, no input file, and PC = multiple named pools each with its own
  dilution series encoded in the sample name (Anti-OSP/cTxB/HlyE, Dengue, Orpal,
  HlyE ng/mL, Cholera High/Low), NC = "Negative 0/49", specimens = `{id}_r3_
  {Serum|DBS}`. Updated plan: revive multi-pool fitting + per-pool history,
  rewrite classification patterns, new pool/dilution parser.
- Received the two screenshots; locked the linear-range styling (green square,
  red out-of-tolerance triangles, "×" excluded point).
- Raised 6 new open questions from the pilot data (202 vs 200, pool→antigen
  priority mapping, HlyE concentration axis, NC labels, Serum/DBS pairing,
  single-point controls).
- Drafted this plan (To-Do sections 0–10) for user review. **No code changed**
  (other than moving legacy docs into `legacy/`).
- Next session (pending approval): Section 0 rebranding + Section 1 (384-well +
  multi-pool foundation), since all downstream UI work depends on it.
