# v0.3.0

Bangladesh National Serosurveillance Luminex QC — 202-plex IgG, Intelliflex (High PMT, 384-well).

## Highlights

**5PL standard curves (new default).** Standard curves are now fit with a five-parameter logistic model, `y = d + (a − d)/(1 + (x/c)^b)^g`, whose asymmetry term `g` (bounded 0.1–10; `g = 1` ≡ 4PL) reduces back-calculation bias near an asymptote. 4PL remains available. A report uses **one model throughout** — there is no per-antigen fallback; an antigen the chosen model cannot fit is reported as **NO_FIT** for that report. The model is stored per fit and in history, so past-plate overlays render under the model each plate was generated with.

**Two independent Fit selectors + Past Reports Fit column.** The home page now has separate standard-curve-model dropdowns for **Generate Report** and **Regenerate All**, so a new upload and a full rebuild can use different models without affecting each other. The **Past Reports** table shows a **Fit** column (5PL / 4PL) recording the model each report was generated under.

**Phase A pool relevance remap.** Antigens are scored against the pool that calibrates them: cholera & typhoid → mAb Mix, Dengue → the dedicated Dengue pool, and measles / diphtheria / rubella / tetanus → their dedicated NIBSC dilution series. Non-dengue arboviruses and other VPDs (pertussis, bordetella, meningitidis) are viewable but have no calibrating standard (best-fit only). Handles the differing pool combinations in the pilot plates.

**Three-state Fit-OK.** The curve summary distinguishes **OK** (passed all checks), **FAIL** (fit produced but failed QC), and **NO_FIT** (chosen model could not converge), with definitions included in the report.

**Per-standard range-problem flags.** Out-of-range specimen flags are computed within each standard pool on dedicated antigens (BELOW / ABOVE, informational), clearly labeled for which standard; the detail table carries a Standard column and reference standards are shown as context.

## Also in this release

- Bead-count cards reordered (wells card first) plus a new "wells with ≥1 critically-low antigen" card; bead grid ordered A1 → last well.
- Editable %CV thresholds in Settings; DBS and cross-run MFI plots hidden entirely when no Serum/DBS pairs are present.
- App icon updated to icddr,b ochre with "Bangladesh NSL" text.
- Priority-antigens field and dead code removed.
- README, SPECIFICATION, and in-app Settings text updated throughout.

## Infrastructure

- Version strings aligned to `0.3.0`.
- CI build runners pinned: `macos-15`, `windows-2022`.

## Upgrade notes

- Existing reports generated before this release show **—** in the Past Reports Fit column until regenerated; run **Regenerate All** to record the model and rebuild history plots under a single model.
- The default standard-curve model is now **5PL**. To keep 4PL behavior, select 4PL in Settings (default) and/or in the home-page selectors.
