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

### 0. Project setup & rebranding
- [x] Fork folder from `uvira-luminex-qc` → `bangladesh-serosurveillance-luminex-qc`.
- [x] Create this tracking doc (`BANGLADESH_TODO.md`) with the plan.
- [x] Rebrand (Session 1): `RESULTS_DIR_NAME` →
      `bangladesh-serosurveillance-luminex-qc-results`; app/window/report/settings
      titles; download filename prefixes; `.spec` files renamed + internal names;
      `APP_VERSION = "0.1.0-bangladesh"`; assay name/description; pyproject; GitHub
      URL. `report.py` module docstring.
- [ ] Rewrite `README.md` + `SPECIFICATION.md` for the 202-plex / 384-well /
      Bangladesh context (remove Uvira/MPXV-specific copy entirely). *(deferred —
      do alongside the descriptions audit, Section 8.)*
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

### 4. Background QC section (after Bead Count; substantial edits)
- [ ] **Default max-MFI threshold → 300** (`bg_max_mfi`), editable in Settings.
- [ ] **Rewrite the "How Background QC works" description.** Remove the
      confusing point 3 (Max Background MFI) wording; make every point match
      what the code actually computes after the table changes below. No stale
      copy left behind.
- [ ] **"Background MFI overview (all plates)" plot — redesign**:
  - Show, per antigen, the **IQR of historical plate runs** as a bar/range and
    the **current plate's mean** as a dot positioned relative to that IQR.
  - **< 3 plates total** → keep the current dot-per-plate scatter.
  - **≥ 3 plates** → vertical line spanning the IQR + a dot for the current
    plate (ideally inside the IQR).
  - Leave a hook for flagging dots outside the IQR (decision deferred — see
    Open questions).
- [ ] **Per-antigen Background QC table — rebuild + fold by default**:
  - Wrap in a collapsible (click-to-expand) container; make it scrollable
    horizontally and vertically.
  - **Remove** Mean MFI, Max MFI columns and the MAX flag.
  - **Keep** Analyte, n wells, SD, %CV; **add** the individual MFI measurements
    (one per background well) and two new IQR columns: **IQR of current plate**
    and **IQR of previous plates** (separate columns).
  - Column order: Analyte → n wells → individual MFI measurements → SD → %CV →
    IQR current plate → IQR previous plates.
  - Flags intentionally deferred — **note left in code/table** ("flags TBD").

### 5. Standard curves — multi-pool + priority-pathogen concept
- [ ] **Multi-pool fitting**: fit a 4PL per (pool × antigen). Each pool uses its
      own parsed dilution series. Single-point controls (Cholera High/Low) are
      not fit but can be shown as reference points.
- [ ] **Settings: priority pathogens.** New field (textarea/multiselect) to
      define priority antigens (and possibly pool→antigen pairings).
      **Default = all antigens** from the CSV output. Persist to YAML.
- [ ] **Standard Curve Summary** + **All Curves Overview**: show **priority
      antigens only** (curves still fit for all; display filtered). Likely one
      curve grid per pool (mirrors the two screenshots: "ITM PC" / "ITM PC2").
- [ ] **All Curves Overview — make interactive**: convert from the static
      matplotlib PNG grid to interactive plots with the **same hover + rug
      plot** as the picker. Rug plot here uses **current plate run only** (no
      historical overlays).
- [ ] **Linear-range square (confirmed from screenshots)**: on each curve, draw
      a **green shaded rectangle** spanning the reportable range — x from
      ULOQ-dilution to LLOQ-dilution, y from LLOQ-MFI to ULOQ-MFI (dashed green
      border, light-green fill), using existing `reportable_range`. Standard
      points **outside recovery tolerance** drawn as **red triangles** ("Out of
      tolerance"); a dropped/excluded point drawn as a **bold "×"**. Legend:
      Observed (blue dot), Out of tolerance (red triangle), 4PL Fit (red line),
      Specimens (rug ticks). Curve line is **red**, observed points **blue**.
- [ ] **Standard Curve Picker**: keep fitting against **ALL** antigens (all
      pools); **fold by default** (click-to-expand) with a disclaimer that not
      all curves are meant to be interpreted — only priority (pool × antigen)
      curves — and that the picker is for review only.

### 6. Standard-Curve Range Matrix + Serum/DBS pairing
- [ ] Remove sample-ID labels from the top axis; **keep well location** visible.
- [ ] Hover still shows: antigen, well position, sample id, and status
      (below range / in range / above range / no fit).
- [ ] **Paired Serum-vs-DBS comparison** (new folded sub-section/tab): for each
      person with both a `_Serum` and a `_DBS` sample, compare their MFI (and/or
      AU) per antigen — e.g. scatter of serum MFI vs DBS MFI with a y=x line, or
      a per-antigen paired view. Folded by default. Specimens still listed
      individually elsewhere; this is an added QC view, not a replacement.

### 7. Settings page — make thresholds editable
- [ ] Priority-pathogen list (section 5).
- [ ] Background max-MFI threshold (default 300).
- [ ] Bead-count thresholds (min/warn) — already present; verify wired through
      to the new card copy.
- [ ] Problem-fraction (≥X%) threshold for flagged antigens/samples — already
      present; verify.
- [ ] Background %CV threshold — already present; verify.
- [ ] Audit: every threshold used in the report must be read from config, not
      hard-coded, and every description string must reflect the live value.

### 8. Descriptions audit (cross-cutting)
- [ ] Review **every** section's explanatory text and rewrite to match what the
      code actually computes/shows after the changes above. Remove all
      Uvira/MPXV-specific and stale copy.

### 9. Validation
- [ ] Obtain a representative Bangladesh 384-well xPONENT CSV (+ input file +
      barcode map) and validate end-to-end.
- [ ] Verify plate map, well counts, and classification on real 384 data.
- [ ] Regression-check the Uvira fixtures still process (96-well path).

### 10. Deferred / future work (noted, not in this scope)
- [ ] PC Replicate Variability section — to be worked on later.
- [ ] Negative Control levels section — to be worked on later.
- [ ] Decide background-IQR out-of-range flagging rule.
- [ ] Decide final flag rules for the Background QC table.

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
1. **Pool → priority-antigen mapping (exact lists)**: auto-mapping now runs by
   default (name + best-fit). Team to confirm/override the prefix→pathogen rules
   and the priority-display list later in Settings.
2. **Individual dengue controls (Plate 2)**: are the 28 individual dengue
   controls "specimens" or "controls" for QC display? (Characterization samples,
   not a standard series. Default: treat as specimens unless told otherwise.)

---

## Session History

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
