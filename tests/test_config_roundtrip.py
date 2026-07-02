"""Config YAML round-trip tests.

Verifies that the Settings config — especially the antigen → standard-pool
matching fields — survives save → load → save unchanged. Run standalone
(`python -m tests.test_config_roundtrip` from the repo root) or via pytest.
"""

from __future__ import annotations

import copy
import tempfile
from pathlib import Path

from src import settings as S


def _with_temp_config(fn):
    """Run ``fn`` with settings.get_config_path pointing at a fresh temp file."""
    orig = S.get_config_path
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "config.yaml"
        S.get_config_path = lambda: path
        try:
            return fn(path)
        finally:
            S.get_config_path = orig


def test_pool_matching_config_roundtrips():
    """priority_antigens / pool_mode / scoring_pool / pool_assignment_rules /
    pool_antigen_overrides survive save→load→save (incl. a regex with a comma)."""
    def body(_path):
        cfg = S.load_config()  # defaults (no user file yet)
        panel = cfg.setdefault("panel", {})
        panel["priority_antigens"] = ["ARB_DENV1_VLP", "CHO_CtxB", "BAC_S.typhi_HlyE"]
        panel["pool_mode"] = "auto_select"
        panel["scoring_pool"] = "Dengue pool"
        # Rules include a regex with a comma ({1,2}) — must survive intact
        # because they're stored as a YAML list, not a comma-joined string.
        panel["pool_assignment_rules"] = [
            "ARB_DENV.*        => Dengue pool",
            "CHO_.*|.*CtxB.*   => Anti-OSP & cTxB pool",
            "X{1,2}.*HlyE.*    => HlyE",
        ]
        panel["pool_antigen_overrides"] = {"CHO_Inaba_OSP": "Anti-OSP & cTxB pool"}

        S.save_config(cfg)
        reloaded = S.load_config()
        rp = reloaded["panel"]
        assert rp["priority_antigens"] == panel["priority_antigens"]
        assert rp["pool_mode"] == "auto_select"
        assert rp["scoring_pool"] == "Dengue pool"
        assert rp["pool_assignment_rules"] == panel["pool_assignment_rules"]
        assert rp["pool_antigen_overrides"] == panel["pool_antigen_overrides"]

        # Idempotent: a second save/load is byte-stable for the panel fields.
        before = copy.deepcopy(rp)
        S.save_config(reloaded)
        again = S.load_config()["panel"]
        for k in ("priority_antigens", "pool_mode", "scoring_pool",
                  "pool_assignment_rules", "pool_antigen_overrides"):
            assert again[k] == before[k], f"round-trip changed {k}"

    _with_temp_config(body)


def test_qc_thresholds_roundtrip():
    """Numeric QC thresholds survive save→load with their types intact."""
    def body(_path):
        cfg = S.load_config()
        qc = cfg["qc_thresholds"]
        qc["bead_count_min"] = 25
        qc["recovery_tolerance"] = 0.25
        qc["drop_outlier"] = False
        S.save_config(cfg)
        r = S.load_config()["qc_thresholds"]
        assert r["bead_count_min"] == 25 and isinstance(r["bead_count_min"], int)
        assert abs(r["recovery_tolerance"] - 0.25) < 1e-9
        assert r["drop_outlier"] is False
    _with_temp_config(body)


if __name__ == "__main__":
    test_pool_matching_config_roundtrips()
    test_qc_thresholds_roundtrip()
    print("OK — config YAML round-trip tests passed")
