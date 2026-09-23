# v0.4.1 — packaged-app fix

Patch release fixing standard-curve fitting in the downloaded macOS / Windows
app.

- **Fix:** in the packaged (PyInstaller) app, standard curves were not being fit
  — the v0.4.0 parallel curve-fitting used Python multiprocessing, which is
  unreliable inside a frozen `.app`/`.exe` (spawned workers re-launch the bundle
  instead of running the fit). The packaged app now fits **serially** (correct,
  just slower on very large plates); running from source still uses the parallel
  speedup. Added `multiprocessing.freeze_support()` at the entry point as a
  safeguard.

Everything else is unchanged from v0.4.0.
