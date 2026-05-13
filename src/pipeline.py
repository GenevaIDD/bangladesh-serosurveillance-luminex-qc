"""Main QC pipeline — orchestrates parsing, QC, and report generation."""

from pathlib import Path

import pandas as pd

from .parse_xponent import parse_xponent_csv
from .classify import classify_wells
from .qc_beads import qc_bead_counts
from .qc_standard_curve import fit_standard_curves, compute_concentrations, compute_net_mfi
from .qc_replicates import qc_pc_replicates
from .qc_nc import qc_nc_levels
from .qc_kit_controls import qc_kit_controls
from .qc_history import load_history, append_history, save_history
from .parse_layout import read_plate_layout, build_layout
from .plate_summary import plate_summary
from .report import generate_report
from .settings import load_config


def run_pipeline(
    csv_path: str | Path,
    output_dir: str | Path | None = None,
    layout_path: str | Path | None = None,
    inputfile_path: str | Path | None = None,
    history_dir: str | Path | None = None,
    config: dict | None = None,
    plate_order: list | None = None,
) -> Path:
    """Run the full QC pipeline on a single plate CSV.

    Args:
        csv_path: path to xPONENT CSV file
        output_dir: where to write report and CSVs (defaults to csv parent dir)
        layout_path: optional path to plate layout xlsx
        history_dir: where to store history JSON files (defaults to output_dir/history)
        config: optional config dict (from settings.load_config); loaded if not provided

    Returns path to the generated HTML report.
    """
    csv_path = Path(csv_path)
    if output_dir is None:
        output_dir = csv_path.parent
    output_dir = Path(output_dir)
    if history_dir is None:
        history_dir = output_dir / "history"

    # Load config if not provided
    if config is None:
        config = load_config()

    # 1. Parse CSV
    parsed = parse_xponent_csv(csv_path)
    metadata = parsed["metadata"]
    data = parsed["data"]

    # 2. Classify wells (using config patterns)
    data = classify_wells(data, config=config)

    # 3. Optional layout enrichment.
    # New (Uvira) path: inputfile CSV (well → plate_well_type, barcode) +
    # optional Box xlsx (barcode → patient_id), merged via build_layout.
    # Legacy path: a Sample-list xlsx via read_plate_layout(layout_path).
    if inputfile_path:
        layout = build_layout(inputfile_path, box_xlsx_path=layout_path)
        if layout is not None and not layout.empty:
            # sample_id = patient_id when known, else on-plate barcode
            layout = layout.copy()
            layout["sample_id"] = layout["patient_id"].where(
                layout["patient_id"].astype(str).str.len() > 0,
                layout["barcode"],
            )
            keep_cols = [c for c in ("well", "sample_id", "barcode", "patient_id", "box_id") if c in layout.columns]
            data = data.merge(layout[keep_cols], on="well", how="left")
    elif layout_path:
        layout = read_plate_layout(layout_path)
        if layout is not None and any(c in layout.columns for c in ("sample_id", "visit_date", "dilution")):
            data = data.merge(layout, on="well", how="left", suffixes=("", "_layout"))
            # Apply per-well dilution overrides from layout where provided
            if "dilution_layout" in data.columns:
                mask = data["dilution_layout"].notna()
                data.loc[mask, "dilution"] = pd.to_numeric(
                    data.loc[mask, "dilution_layout"], errors="coerce"
                )
                data = data.drop(columns=["dilution_layout"])

    # 4. QC: bead counts
    bead_qc = qc_bead_counts(data, config=config)

    # 5. QC: 4PL standard curves
    fits = fit_standard_curves(data, config=config)

    # 6. QC: PC replicate CV
    replicate_qc = qc_pc_replicates(data, config=config)

    # 7. QC: NC levels
    nc_levels = qc_nc_levels(data, config=config)

    # 8. QC: kit controls
    kit_ctrl = qc_kit_controls(data, config=config)

    # 9. Compute specimen AU and Net MFI
    specimen_results = compute_concentrations(data, fits)
    data = compute_net_mfi(data)
    # Add net_mfi to specimen_results by index alignment
    if "net_mfi" in data.columns:
        specimen_results["net_mfi"] = data.loc[specimen_results.index, "net_mfi"]

    # 10. Plate summary
    summary = plate_summary(data)

    # 11. History — load, append, save (per pool)
    nc_history_path = Path(history_dir) / "nc_history.json"
    fit_history_path = Path(history_dir) / "fit_history.json"

    # Standard curve history — per pool
    history_std = {}
    for pool_name in fits:
        pool_slug = pool_name.replace(" ", "_")
        std_path = Path(history_dir) / f"std_curve_history_{pool_slug}.json"
        h = load_history(std_path)
        new_std = _build_std_history(metadata, fits[pool_name], pool_name)
        if not new_std.empty:
            h = append_history(h, new_std, ["plate_id", "analyte", "dilution"])
            save_history(h, std_path)
        history_std[pool_name] = h

    # NC history
    history_nc = load_history(nc_history_path)
    new_nc = _build_nc_history(metadata, nc_levels)
    if not new_nc.empty:
        history_nc = append_history(history_nc, new_nc, ["plate_id", "analyte"])
        save_history(history_nc, nc_history_path)

    # Fit history — per pool
    history_fit = {}
    for pool_name in fits:
        pool_slug = pool_name.replace(" ", "_")
        fit_path = Path(history_dir) / f"fit_history_{pool_slug}.json"
        h = load_history(fit_path)
        new_fit = _build_fit_history(metadata, fits[pool_name], pool_name)
        if not new_fit.empty:
            h = append_history(h, new_fit, ["plate_id", "analyte"])
            save_history(h, fit_path)
        history_fit[pool_name] = h

    # 12. Generate report
    report_name = f"QC_{metadata['plate_id']}.html"
    report_path = output_dir / report_name

    generate_report(
        metadata=metadata,
        data=data,
        bead_qc=bead_qc,
        fits=fits,
        replicate_qc=replicate_qc,
        nc_levels=nc_levels,
        kit_controls=kit_ctrl,
        specimen_results=specimen_results,
        summary=summary,
        history_std=history_std,
        history_nc=history_nc,
        output_path=report_path,
        plate_order=plate_order,
        config=config,
    )

    # 13. Export specimen results CSV
    if not specimen_results.empty:
        csv_out = output_dir / f"specimens_{metadata['plate_id']}.csv"
        export_df = specimen_results.copy()

        pools = list(fits.keys())
        multi_pool = len(pools) > 1

        if multi_pool:
            # Per-pool AU columns + censored flags
            for pool_name in pools:
                slug = pool_name.replace(" ", "_")
                rau_col = f"rau_{slug}"
                lloq_col = f"below_lloq_{slug}"
                uloq_col = f"above_uloq_{slug}"
                au_col = f"AU_{slug}"
                cens_col = f"au_censored_{slug}"

                if rau_col in export_df.columns:
                    export_df = export_df.rename(columns={rau_col: au_col})
                if lloq_col in export_df.columns and uloq_col in export_df.columns:
                    export_df[cens_col] = "none"
                    export_df.loc[export_df[lloq_col], cens_col] = "left"
                    export_df.loc[export_df[uloq_col], cens_col] = "right"
            # Also rename plain rau → AU (first pool default)
            if "rau" in export_df.columns:
                export_df = export_df.rename(columns={"rau": "AU"})
        else:
            export_df = export_df.rename(columns={"rau": "AU"})

        # Add au_censored from the default (plain) columns
        if "below_lloq" in export_df.columns and "above_uloq" in export_df.columns:
            export_df["au_censored"] = "none"
            export_df.loc[export_df["below_lloq"], "au_censored"] = "left"
            export_df.loc[export_df["above_uloq"], "au_censored"] = "right"

        export_df.to_csv(csv_out, index=False, encoding="utf-8")

    return report_path


def _build_std_history(metadata: dict, pool_fits: dict, pool_name: str = "") -> pd.DataFrame:
    """Build standard curve history entries from current plate fits for one pool."""
    rows = []
    for analyte, fit in pool_fits.items():
        std_data = fit.get("std_data", pd.DataFrame())
        if std_data.empty:
            continue
        for _, r in std_data.iterrows():
            row = {
                "plate_id": metadata["plate_id"],
                "run_date": metadata.get("run_date", ""),
                "analyte": analyte,
                "dilution": r["dilution"],
                "mfi": r["mfi"],
            }
            if pool_name:
                row["pool"] = pool_name
            rows.append(row)
    return pd.DataFrame(rows)


def _build_nc_history(metadata: dict, nc_levels: pd.DataFrame) -> pd.DataFrame:
    """Build NC history entries."""
    if nc_levels.empty:
        return pd.DataFrame()
    nc_mean = nc_levels.groupby("analyte")["mfi"].mean().reset_index()
    nc_mean["plate_id"] = metadata["plate_id"]
    nc_mean["run_date"] = metadata.get("run_date", "")
    return nc_mean


def _build_fit_history(metadata: dict, pool_fits: dict, pool_name: str = "") -> pd.DataFrame:
    """Build fit coefficient history entries for one pool."""
    rows = []
    for analyte, fit in pool_fits.items():
        row = {
            "plate_id": metadata["plate_id"],
            "run_date": metadata.get("run_date", ""),
            "analyte": analyte,
            "fit_ok": fit["fit_ok"],
        }
        if pool_name:
            row["pool"] = pool_name
        if fit["params"]:
            a, b, c, d = fit["params"]
            row.update({"a": a, "b": b, "c": c, "d": d})
        rows.append(row)
    return pd.DataFrame(rows)
