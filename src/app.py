"""Flask web app for Bangladesh Serosurveillance Luminex QC tool."""

from __future__ import annotations

import io
import json
import os
import signal
import sys
import traceback

import yaml
from datetime import datetime
from pathlib import Path

import pandas as pd
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from werkzeug.utils import secure_filename

from .config import APP_VERSION, RESULTS_DIR_NAME
from .pipeline import run_pipeline
from .settings import load_config, save_config, reset_config, get_config_path

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _get_base_path() -> Path:
    """Return the base path for bundled resources.

    PyInstaller sets sys._MEIPASS when running from a bundle.
    In dev, use the project root (parent of src/).
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent.parent


def _get_results_dir() -> Path:
    """Persistent results directory in user's home."""
    d = Path.home() / RESULTS_DIR_NAME
    for sub in ("reports", "specimens", "history", "uploads"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> Flask:
    base = _get_base_path()
    results = _get_results_dir()

    app = Flask(
        __name__,
        template_folder=str(base / "templates" / "web"),
        static_folder=str(base / "static") if (base / "static").exists() else None,
    )
    app.secret_key = os.urandom(24)
    app.config["RESULTS_DIR"] = results
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @app.route("/")
    def index():
        reports = _list_reports(results)
        return render_template("index.html", reports=reports, version=APP_VERSION)

    @app.route("/upload", methods=["POST"])
    def upload():
        csv_files = request.files.getlist("csv_files")
        inputfile_file = request.files.get("inputfile_file")
        layout_file = request.files.get("layout_file")  # Box xlsx (optional)

        # Validate
        csv_files = [f for f in csv_files if f and f.filename]
        if not csv_files:
            flash("Please select at least one plate result CSV file.", "error")
            return redirect(url_for("index"))

        # Save optional inputfile CSV (Intelliflex well→barcode map)
        inputfile_path = None
        if inputfile_file and inputfile_file.filename:
            inputfile_name = secure_filename(inputfile_file.filename)
            inputfile_path = results / "uploads" / inputfile_name
            inputfile_file.save(inputfile_path)

        # Save optional Box xlsx (barcode→patient_id map)
        layout_path = None
        if layout_file and layout_file.filename:
            layout_name = secure_filename(layout_file.filename)
            layout_path = results / "uploads" / layout_name
            layout_file.save(layout_path)

        last_report = None
        inputfile_name = inputfile_path.name if inputfile_path else None
        layout_name = layout_path.name if layout_path else None
        for csv_file in csv_files:
            csv_name = secure_filename(csv_file.filename)
            csv_path = results / "uploads" / csv_name
            csv_file.save(csv_path)

            try:
                config = load_config()
                report_path = run_pipeline(
                    csv_path=csv_path,
                    output_dir=results / "reports",
                    layout_path=layout_path,
                    inputfile_path=inputfile_path,
                    history_dir=results / "history",
                    config=config,
                )
                last_report = report_path

                # Move specimen CSV from reports/ to specimens/
                plate_id = report_path.stem.replace("QC_", "")
                spec_csv = results / "reports" / f"specimens_{plate_id}.csv"
                if spec_csv.exists():
                    spec_csv.rename(results / "specimens" / spec_csv.name)

                # Register plate (keep CSV/inputfile/layout for regeneration)
                _register_plate(results, plate_id, csv_name, layout_name, inputfile_name)

                flash(f"Report generated: {report_path.name}", "success")

            except Exception as exc:
                traceback.print_exc()
                flash(f"Error processing {csv_name}: {exc}", "error")

        # Redirect to the last generated report, or back to index
        if last_report and last_report.exists():
            return redirect(url_for("view_report", filename=last_report.name))
        return redirect(url_for("index"))

    @app.route("/report/<filename>")
    def view_report(filename):
        report_file = results / "reports" / secure_filename(filename)
        if not report_file.exists():
            flash("Report not found.", "error")
            return redirect(url_for("index"))
        return send_file(report_file)

    @app.route("/download/report/<filename>")
    def download_report(filename):
        report_file = results / "reports" / secure_filename(filename)
        if not report_file.exists():
            flash("Report not found.", "error")
            return redirect(url_for("index"))
        return send_file(report_file, as_attachment=True)

    @app.route("/download/specimens/<filename>")
    def download_specimens(filename):
        # Per-plate CSVs are written to reports/; the specimens CSV is also
        # mirrored into specimens/. Look in both so every download link works.
        safe = secure_filename(filename)
        for sub in ("specimens", "reports"):
            f = results / sub / safe
            if f.exists():
                return send_file(f, as_attachment=True)
        flash("Download file not found.", "error")
        return redirect(url_for("index"))

    @app.route("/export/all")
    def export_all():
        """Export all data to date as an Excel workbook.

        Sheets:
        - specimens: all specimen results combined across plates
        - standard_curve_params: 4PL fit parameters (a, b, c, d) per plate/analyte
        - standard_curve_data: raw standard curve MFI data points
        - nc_levels: negative control MFI per plate/analyte
        """
        history_dir = results / "history"
        specimens_dir = results / "specimens"

        reports_dir = results / "reports"
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            # Clean master "results" sheet — tidy per (plate × well × antigen)
            # with the selected pool, RAU/AU, and range status. This is the
            # headline analysis-ready table (legacy-style, plus RAU).
            res_frames = []
            for csv_file in sorted(reports_dir.glob("results_*.csv")):
                try:
                    res_frames.append(pd.read_csv(csv_file, encoding="utf-8"))
                except Exception:
                    pass
            if res_frames:
                pd.concat(res_frames, ignore_index=True).to_excel(
                    writer, sheet_name="results", index=False
                )

            # All specimens (raw + per-pool AU columns)
            spec_frames = []
            for csv_file in sorted(specimens_dir.glob("specimens_*.csv")):
                df = pd.read_csv(csv_file, encoding="utf-8")
                plate_id = csv_file.stem.replace("specimens_", "")
                df.insert(0, "plate_id", plate_id)
                spec_frames.append(df)
            if spec_frames:
                pd.concat(spec_frames, ignore_index=True).to_excel(
                    writer, sheet_name="specimens", index=False
                )

            # Fit history (standard curve parameters) — one file per pool
            fit_frames = []
            for fit_path in sorted(history_dir.glob("fit_history*.json")):
                try:
                    df = pd.DataFrame(json.loads(fit_path.read_text(encoding="utf-8")))
                    if not df.empty:
                        fit_frames.append(df)
                except Exception:
                    pass
            if fit_frames:
                pd.concat(fit_frames, ignore_index=True).to_excel(
                    writer, sheet_name="standard_curve_params", index=False
                )

            # Standard curve raw data — one file per pool
            std_frames = []
            for std_path in sorted(history_dir.glob("std_curve_history*.json")):
                try:
                    df = pd.DataFrame(json.loads(std_path.read_text(encoding="utf-8")))
                    if not df.empty:
                        std_frames.append(df)
                except Exception:
                    pass
            if std_frames:
                pd.concat(std_frames, ignore_index=True).to_excel(
                    writer, sheet_name="standard_curve_data", index=False
                )

            # NC levels (cross-plate history; file is nc_well_history.json)
            nc_path = history_dir / "nc_well_history.json"
            if nc_path.exists():
                nc_data = pd.DataFrame(json.loads(nc_path.read_text(encoding="utf-8")))
                if not nc_data.empty:
                    nc_data.to_excel(
                        writer, sheet_name="nc_levels", index=False
                    )

        buf.seek(0)
        return send_file(
            buf,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name="bangladesh_serosurveillance_all_data.xlsx",
        )

    @app.route("/delete/<plate_id>", methods=["POST"])
    def delete_plate(plate_id):
        """Delete a plate's report, specimen CSV, history entries, and uploaded files."""
        plate_id = secure_filename(plate_id)

        # Delete report HTML
        report_file = results / "reports" / f"QC_{plate_id}.html"
        if report_file.exists():
            report_file.unlink()

        # Delete specimen CSV
        spec_file = results / "specimens" / f"specimens_{plate_id}.csv"
        if spec_file.exists():
            spec_file.unlink()

        # Remove plate from history JSON files
        history_dir = results / "history"
        for hist_file in history_dir.glob("*.json"):
            try:
                data = json.loads(hist_file.read_text(encoding="utf-8"))
                filtered = [r for r in data if r.get("plate_id") != plate_id]
                if len(filtered) < len(data):
                    hist_file.write_text(json.dumps(filtered, indent=2), encoding="utf-8")
            except Exception:
                pass

        # Delete uploaded CSV/layout and remove from registry
        registry = _load_registry(results)
        entry = next((r for r in registry if r["plate_id"] == plate_id), None)
        if entry:
            for fname in (
                entry.get("csv_filename"),
                entry.get("layout_filename"),
                entry.get("inputfile_filename"),
            ):
                if fname:
                    f = results / "uploads" / fname
                    if f.exists():
                        f.unlink()
        registry = [r for r in registry if r["plate_id"] != plate_id]
        # Renumber sort_order to keep gapless
        for i, r in enumerate(sorted(registry, key=lambda x: x.get("sort_order", 0))):
            r["sort_order"] = i
        _save_registry(results, registry)

        flash(f"Deleted plate {plate_id}.", "success")
        return redirect(url_for("index"))

    @app.route("/reorder", methods=["POST"])
    def reorder_plates():
        """Update plate order from JSON body {"order": ["plate_id_1", ...]}."""
        body = request.get_json(force=True, silent=True) or {}
        order = body.get("order", [])
        registry = _load_registry(results)
        id_to_entry = {r["plate_id"]: r for r in registry}
        for i, pid in enumerate(order):
            if pid in id_to_entry:
                id_to_entry[pid]["sort_order"] = i
        # Plates not in the submitted order keep their existing sort_order (pushed to end)
        max_order = len(order)
        for r in registry:
            if r["plate_id"] not in order:
                r["sort_order"] = max_order
                max_order += 1
        _save_registry(results, registry)
        return jsonify({"ok": True})

    @app.route("/regenerate-all", methods=["POST"])
    def regenerate_all():
        """Re-run pipeline for all registered plates in registry order."""
        registry = _load_registry(results)
        if not registry:
            flash("No plates in registry to regenerate.", "error")
            return redirect(url_for("index"))

        registry_sorted = sorted(registry, key=lambda r: r.get("sort_order", 0))
        plate_order = [r["plate_id"] for r in registry_sorted]

        config = load_config()
        ok = 0
        errors = 0
        for entry in registry_sorted:
            csv_path = results / "uploads" / entry["csv_filename"]
            if not csv_path.exists():
                flash(f"Upload file missing for {entry['plate_id']}: {entry['csv_filename']}", "error")
                errors += 1
                continue
            layout_path = None
            if entry.get("layout_filename"):
                lp = results / "uploads" / entry["layout_filename"]
                layout_path = lp if lp.exists() else None
            inputfile_path = None
            if entry.get("inputfile_filename"):
                ip = results / "uploads" / entry["inputfile_filename"]
                inputfile_path = ip if ip.exists() else None
            try:
                report_path = run_pipeline(
                    csv_path=csv_path,
                    output_dir=results / "reports",
                    layout_path=layout_path,
                    inputfile_path=inputfile_path,
                    history_dir=results / "history",
                    config=config,
                    plate_order=plate_order,
                )
                plate_id = report_path.stem.replace("QC_", "")
                spec_csv = results / "reports" / f"specimens_{plate_id}.csv"
                if spec_csv.exists():
                    spec_csv.rename(results / "specimens" / spec_csv.name)
                ok += 1
            except Exception as exc:
                traceback.print_exc()
                flash(f"Error regenerating {entry['plate_id']}: {exc}", "error")
                errors += 1

        flash(f"Regenerated {ok} report(s)." + (f" {errors} error(s)." if errors else ""), "success" if not errors else "error")
        return redirect(url_for("index"))

    @app.route("/specification")
    def specification():
        """Serve the SPECIFICATION.md as a simple HTML page."""
        spec_path = base / "SPECIFICATION.md"
        if not spec_path.exists():
            flash("Specification file not found.", "error")
            return redirect(url_for("index"))
        content = spec_path.read_text(encoding="utf-8")
        # Simple markdown-to-HTML: render as preformatted with basic styling
        html = (
            '<!DOCTYPE html><html><head><meta charset="UTF-8">'
            '<title>Bangladesh Serosurveillance Luminex QC — Specification</title>'
            '<style>'
            'body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;'
            ' max-width: 900px; margin: 0 auto; padding: 20px; color: #333; }'
            'pre { white-space: pre-wrap; word-wrap: break-word; font-family: inherit;'
            ' line-height: 1.7; font-size: 14px; }'
            'a.back { display: inline-block; margin-bottom: 16px; padding: 8px 16px;'
            ' background: #3498db; color: #fff; border-radius: 6px; text-decoration: none;'
            ' font-size: 13px; font-weight: 600; }'
            '</style></head><body>'
            '<a class="back" href="/">&larr; Back to Menu</a>'
            f'<pre>{content}</pre>'
            '</body></html>'
        )
        return html

    # ------------------------------------------------------------------
    # Settings routes
    # ------------------------------------------------------------------

    @app.route("/settings")
    def settings():
        config = load_config()
        return render_template(
            "settings.html",
            config=config,
            version=APP_VERSION,
            config_path=str(get_config_path()),
        )

    @app.route("/settings", methods=["POST"])
    def save_settings():
        config = load_config()

        # Assay info
        config["assay"]["name"] = request.form.get("assay_name", "").strip()
        config["assay"]["description"] = request.form.get("assay_description", "").strip()
        config["standard"]["bead_batch"] = request.form.get("bead_batch", "").strip()

        # Excluded analytes (newline-separated, soft-flag list)
        excluded_raw = request.form.get("excluded_analytes", "")
        excluded = [line.strip() for line in excluded_raw.splitlines() if line.strip()]
        config["panel"]["excluded_analytes"] = excluded

        # Priority antigens (newline-separated; empty = all antigens shown).
        priority_raw = request.form.get("priority_antigens", "")
        priority = [line.strip() for line in priority_raw.splitlines() if line.strip()]
        config["panel"]["priority_antigens"] = priority

        # Standard-curve pool mode + scoring pool.
        mode = request.form.get("pool_mode", "per_pool").strip()
        config["panel"]["pool_mode"] = mode if mode in ("per_pool", "auto_select") else "per_pool"
        config["panel"]["scoring_pool"] = request.form.get("scoring_pool", "").strip()
        # Pool assignment rules ("<regex> => <pool>", one per line).
        rules_raw = request.form.get("pool_assignment_rules", "")
        config["panel"]["pool_assignment_rules"] = [
            line.strip() for line in rules_raw.splitlines() if line.strip()
        ]

        # Well classification patterns
        pc_pats = request.form.get("pc_patterns", "")
        bg_pats = request.form.get("background_patterns", "")
        nc_pats = request.form.get("nc_patterns", "")
        config["well_classification"]["pc_patterns"] = [p.strip() for p in pc_pats.split(",") if p.strip()]
        config["well_classification"]["background_patterns"] = [p.strip() for p in bg_pats.split(",") if p.strip()]
        config["well_classification"]["nc_patterns"] = [p.strip() for p in nc_pats.split(",") if p.strip()]

        # Specimen dilution
        try:
            config["specimens"]["default_dilution"] = int(request.form.get("specimen_default_dilution", 100))
        except ValueError:
            pass

        # QC thresholds
        qc = config["qc_thresholds"]
        for key in ("bead_count_min", "bead_count_warn", "bg_max_mfi"):
            try:
                qc[key] = int(request.form.get(key, qc.get(key, 0)))
            except (ValueError, TypeError):
                pass
        for key in ("recovery_tolerance", "problem_fraction_threshold",
                    "bg_cv_threshold", "pc_cv_threshold"):
            try:
                qc[key] = float(request.form.get(key, qc.get(key, 0)))
            except (ValueError, TypeError):
                pass
        # Outlier detection checkbox
        qc["drop_outlier"] = request.form.get("drop_outlier") == "true"

        save_config(config)
        flash("Settings saved.", "success")
        return redirect(url_for("settings"))

    @app.route("/settings/reset", methods=["POST"])
    def reset_settings():
        reset_config()
        flash("Settings reset to defaults.", "success")
        return redirect(url_for("settings"))

    @app.route("/download/plate-layout-template")
    def download_plate_layout_template():
        """Generate and serve a blank plate layout XLSX template."""
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sample list"
        ws.append(["well", "sample_id", "visit_date", "dilution"])
        # Pre-fill well IDs for a 96-well plate
        for row_letter in "ABCDEFGH":
            for col_num in range(1, 13):
                ws.append([f"{row_letter}{col_num}", "", "", ""])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return send_file(
            buf,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name="plate_layout_template.xlsx",
        )

    @app.route("/settings/export")
    def export_config():
        config = load_config()
        buf = io.BytesIO()
        buf.write(yaml.dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True).encode("utf-8"))
        buf.seek(0)
        return send_file(buf, mimetype="text/yaml", as_attachment=True, download_name="bangladesh_serosurveillance_config.yaml")

    @app.route("/settings/import", methods=["POST"])
    def import_config():
        config_file = request.files.get("config_file")
        if not config_file or not config_file.filename:
            flash("No file selected.", "error")
            return redirect(url_for("settings"))
        try:
            content = config_file.read().decode("utf-8")
            imported = yaml.safe_load(content)
            if not isinstance(imported, dict):
                raise ValueError("Invalid YAML structure")
            save_config(imported)
            flash("Configuration imported.", "success")
        except Exception as exc:
            flash(f"Import failed: {exc}", "error")
        return redirect(url_for("settings"))

    @app.route("/shutdown", methods=["POST"])
    def shutdown():
        os.kill(os.getpid(), signal.SIGINT)
        return "Shutting down...", 200

    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _list_reports(results_dir: Path) -> list[dict]:
    """List past reports sorted by registry order (or mtime for unregistered plates)."""
    reports_dir = results_dir / "reports"
    specimens_dir = results_dir / "specimens"
    registry = _load_registry(results_dir)
    order_map = {r["plate_id"]: r.get("sort_order", 9999) for r in registry}

    reports = []
    for html_file in reports_dir.glob("QC_*.html"):
        plate_id = html_file.stem.replace("QC_", "")
        mtime = datetime.fromtimestamp(html_file.stat().st_mtime)
        spec_csv = specimens_dir / f"specimens_{plate_id}.csv"
        reports.append({
            "plate_id": plate_id,
            "filename": html_file.name,
            "date": mtime.strftime("%Y-%m-%d %H:%M"),
            "specimen_csv": spec_csv.name if spec_csv.exists() else None,
            "_sort_key": (order_map.get(plate_id, 9999), -mtime.timestamp()),
        })

    reports.sort(key=lambda r: r["_sort_key"])
    for r in reports:
        del r["_sort_key"]
    return reports


def _get_registry_path(results_dir: Path) -> Path:
    return results_dir / "plate_registry.json"


def _load_registry(results_dir: Path) -> list[dict]:
    """Load plate_registry.json; return [] if missing or corrupt."""
    path = _get_registry_path(results_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_registry(results_dir: Path, registry: list[dict]) -> None:
    """Save plate_registry.json."""
    path = _get_registry_path(results_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2), encoding="utf-8")


def _register_plate(
    results_dir: Path,
    plate_id: str,
    csv_filename: str,
    layout_filename: str | None,
    inputfile_filename: str | None = None,
) -> None:
    """Add or update a plate entry in plate_registry.json."""
    registry = _load_registry(results_dir)
    existing = next((r for r in registry if r["plate_id"] == plate_id), None)
    if existing:
        existing["csv_filename"] = csv_filename
        existing["layout_filename"] = layout_filename
        existing["inputfile_filename"] = inputfile_filename
    else:
        registry.append({
            "plate_id": plate_id,
            "csv_filename": csv_filename,
            "layout_filename": layout_filename,
            "inputfile_filename": inputfile_filename,
            "sort_order": len(registry),
        })
    _save_registry(results_dir, registry)
