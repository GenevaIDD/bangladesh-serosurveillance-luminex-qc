# v0.4.3 — much faster report generation (no more freeze on large plates)

Performance patch for slow / apparently-frozen report generation on full
(200-plex) plates in the packaged app. **No report content is removed — every
antigen × standard curve is still shown.**

- **Parallel curve fitting is back in the packaged app.** v0.4.1 forced serial
  fitting in the frozen build to sidestep a multiprocessing problem; with
  `multiprocessing.freeze_support()` now in place that's no longer needed.
  Fitting runs across CPU cores again (~54s → ~15s for a 200-plex plate), with a
  timeout that automatically falls back to serial if the pool ever misbehaves —
  so it can't hang. Results are numerically identical to serial (verified).
- **The "all curve fits" grids render ~7× faster** — each ~200-antigen static
  grid dropped from ~28s to ~4s. The cost was matplotlib's log-scale **minor
  tick marks** (hundreds per panel) plus `tight_layout` / `bbox_inches="tight"`
  layout passes; those are removed. Every antigen against every standard is
  still drawn (fitted curves and NO_FIT panels with their raw points), axes stay
  readable, and the images are smaller.

Net effect: a full 200-plex report now generates in roughly **a quarter** of the
previous time (~200s → ~50s). Everything else is unchanged from v0.4.2.
