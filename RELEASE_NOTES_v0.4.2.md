# v0.4.2 — standards recognised regardless of saved settings

Patch release fixing "no standard curves / 0 PC wells" in the packaged app for
users who have an older saved settings file.

- **Fix:** the built-in standard/control name patterns are now **always applied**,
  with any user-added custom patterns layered on top. Previously a
  `config.yaml` saved by an earlier version pinned the pattern list, and the
  config merge replaced the built-in list wholesale — so newer standard-name
  patterns were silently dropped and standards were misclassified as specimens
  (curves wouldn't fit). This only affected environments with a saved config
  (e.g. the installed app), not fresh runs.

If you already hit this, "Reset to defaults" on the Settings page also fixes it;
with v0.4.2 no reset is needed.

Everything else is unchanged from v0.4.1.
