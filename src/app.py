"""Flask web app for Bangladesh Serosurveillance Luminex QC tool."""

from __future__ import annotations

import io
import json
import os
import signal
import sys
import traceback
import zipfile

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


def _safe_name(filename: str) -> str:
    """Return the basename of ``filename`` — blocks path traversal (drops any
    directory component / ``..``) while **preserving spaces and the original
    characters**. A plate_id parsed from a CSV ``Batch`` field can contain
    spaces (e.g. "NIBSC test plate_15.9.26"), so the report / CSV files are named
    with spaces; ``werkzeug.secure_filename`` would rewrite spaces to
    underscores and the lookup would miss the real file."""
    return Path(filename or "").name


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
        curve_model = load_config().get("panel", {}).get("curve_model", "5pl")
        # Whether a global individual-age file is currently stored.
        from .age import load_age_data
        _age_df = load_age_data(results / "age_data.csv")
        age_loaded = {"present": _age_df is not None,
                      "n_rows": (int(len(_age_df)) if _age_df is not None else 0)}
        return render_template("index.html", reports=reports, version=APP_VERSION,
                               curve_model=curve_model, age_loaded=age_loaded)

    @app.route("/upload", methods=["POST"])
    def upload():
        csv_files = request.files.getlist("csv_files")
        inputfile_file = request.files.get("inputfile_file")
        layout_file = request.files.get("layout_file")  # Box xlsx (optional)
        age_file = request.files.get("age_file")  # individual age CSV (optional)

        # Validate
        csv_files = [f for f in csv_files if f and f.filename]
        if not csv_files:
            # Allow uploading just the age CSV on its own (saved globally); the
            # user can then Regenerate All to add age bars to existing reports.
            if age_file and age_file.filename:
                (results / "uploads").mkdir(parents=True, exist_ok=True)
                age_file.save(results / "age_data.csv")
                flash("Individual age data saved. Use Regenerate All to add "
                      "age-stratified bars to existing reports.", "success")
                return redirect(url_for("index"))
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

        # Save optional individual age CSV. It is a single global file (applies to
        # every plate / age-stratified bars), persisted at results/age_data.csv so
        # Regenerate All and future uploads reuse it.
        if age_file and age_file.filename:
            age_file.save(results / "age_data.csv")

        # Home-page standard-curve model selector: apply to this batch and
        # persist it so the choice is remembered (dropdown + Settings stay in
        # sync, and Regenerate All then uses the same model).
        _model = request.form.get("curve_model", "").strip().lower()
        if _model in ("4pl", "5pl"):
            _cfg = load_config()
            _cfg.setdefault("panel", {})["curve_model"] = _model
            save_config(_cfg)
        # Effective model for this batch (dropdown choice, else saved default).
        eff_model = _model if _model in ("4pl", "5pl") else (
            load_config().get("panel", {}).get("curve_model", "5pl")
        )

        last_report = None
        inputfile_name = inputfile_path.name if inputfile_path else None
        layout_name = layout_path.name if layout_path else None
        for csv_file in csv_files:
            csv_name = secure_filename(csv_file.filename)
            csv_path = results / "uploads" / csv_name
            csv_file.save(csv_path)

            try:
                config = load_config()
                # Per-render standard-curve model override from the home-page
                # selector (falls back to the saved Settings default).
                config.setdefault("panel", {})["curve_model"] = eff_model
                report_path = run_pipeline(
                    csv_path=csv_path,
                    output_dir=results / "reports",
                    layout_path=layout_path,
                    inputfile_path=inputfile_path,
                    history_dir=results / "history",
                    config=config,
                )
                last_report = report_path

                plate_id = report_path.stem.replace("QC_", "")
                # Register plate (keep CSV/inputfile/layout for regeneration)
                _register_plate(results, plate_id, csv_name, layout_name, inputfile_name, curve_model=eff_model)

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
        report_file = results / "reports" / _safe_name(filename)
        if not report_file.exists():
            flash("Report not found.", "error")
            return redirect(url_for("index"))
        # Reports keep the same filename per plate, so a re-generated report
        # (e.g. after switching the curve model) reuses the URL. Disable caching
        # so the browser always shows the freshly generated content.
        resp = send_file(report_file)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

    @app.route("/download/report/<filename>")
    def download_report(filename):
        report_file = results / "reports" / _safe_name(filename)
        if not report_file.exists():
            flash("Report not found.", "error")
            return redirect(url_for("index"))
        return send_file(report_file, as_attachment=True)

    @app.route("/download/specimens/<filename>")
    def download_specimens(filename):
        # Per-plate CSVs are written to reports/; the specimens CSV is also
        # mirrored into specimens/. Look in both so every download link works.
        safe = _safe_name(filename)
        for sub in ("specimens", "reports"):
            f = results / sub / safe
            if f.exists():
                return send_file(f, as_attachment=True)
        flash("Download file not found.", "error")
        return redirect(url_for("index"))

    @app.route("/export/all")
    def export_all():
        """Export every table to date as one ZIP of CSVs — the single place
        that holds everything the app produces.

        One CSV per table, each combined across all plates. CSVs are instant to
        write, have no Excel-engine dependency, and load directly in R / pandas
        (or Excel, one file at a time).

        Tables: ``results`` (the canonical per plate × well × antigen table,
        wide by standard); the per-plate QC tables (in_range, pct_in_range,
        range_problem_antigens/samples, background_qc,
        bead_problem_antigens/samples/problems, pc_single_point);
        ``standard_curve_params`` / ``standard_curve_data``; and ``nc_levels``.
        """
        history_dir = results / "history"
        reports_dir = results / "reports"

        def _bundle(prefix: str, require: tuple = ()):
            """Concatenate every per-plate ``<prefix>*.csv`` in reports/ into one
            frame, prepending a plate_id column parsed from the filename.

            Files missing any column in ``require`` are skipped. This keeps the
            combined table clean when the reports/ folder still holds per-plate
            CSVs written by an older app version with a different schema —
            concatenating those would union every schema's columns. Re-render
            (Regenerate All) those plates to include them."""
            frames = []
            for csv_file in sorted(reports_dir.glob(f"{prefix}*.csv")):
                try:
                    df = pd.read_csv(csv_file, encoding="utf-8")
                except Exception:
                    continue
                if df.empty or any(c not in df.columns for c in require):
                    continue
                if "plate_id" not in df.columns:
                    df.insert(0, "plate_id", csv_file.stem[len(prefix):])
                frames.append(df)
            return pd.concat(frames, ignore_index=True) if frames else None

        def _hist(pattern: str):
            """Concatenate cross-plate history JSON files into one frame."""
            frames = []
            for path in sorted(history_dir.glob(pattern)):
                try:
                    df = pd.DataFrame(json.loads(path.read_text(encoding="utf-8")))
                    if not df.empty:
                        frames.append(df)
                except Exception:
                    pass
            return pd.concat(frames, ignore_index=True) if frames else None

        # Assemble every table once, in a fixed order.
        tables: list[tuple[str, pd.DataFrame]] = []
        # Only include per-plate results CSVs written in the current schema
        # (identified by ``result_type`` + ``reporting_standard``); stale
        # older-schema files are skipped so the combined table stays clean.
        results_df = _bundle("results_", require=("result_type", "reporting_standard"))
        if results_df is not None:
            tables.append(("results", results_df))
        for prefix, name in (
            ("in_range_", "in_range"),
            ("pct_in_range_", "pct_in_range"),
            ("range_problem_antigens_", "range_problem_antigens"),
            ("range_problem_samples_", "range_problem_samples"),
            ("background_qc_", "background_qc"),
            ("bead_problem_antigens_", "bead_problem_antigens"),
            ("bead_problem_samples_", "bead_problem_samples"),
            ("bead_problems_", "bead_problems"),
            ("pc_single_point_", "pc_single_point"),
        ):
            df = _bundle(prefix)
            if df is not None:
                tables.append((name, df))
        for name, df in (
            ("standard_curve_params", _hist("fit_history*.json")),
            ("standard_curve_data", _hist("std_curve_history*.json")),
        ):
            if df is not None:
                tables.append((name, df))
        nc_path = history_dir / "nc_well_history.json"
        if nc_path.exists():
            try:
                nc_df = pd.DataFrame(json.loads(nc_path.read_text(encoding="utf-8")))
                if not nc_df.empty:
                    tables.append(("nc_levels", nc_df))
            except Exception:
                pass

        # Bundle every table as a CSV into one ZIP. CSVs are near-instant to
        # write and have no Excel-engine dependency, so the export behaves
        # identically (and fast) for every user regardless of environment.
        # (Anyone who wants Excel can open a CSV in Excel directly.)
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, df in tables:
                zf.writestr(f"{name}.csv", df.to_csv(index=False))
        zip_buf.seek(0)
        return send_file(
            zip_buf,
            mimetype="application/zip",
            as_attachment=True,
            download_name="bangladesh_serosurveillance_all_data.zip",
        )

    @app.route("/delete/<plate_id>", methods=["POST"])
    def delete_plate(plate_id):
        """Delete a plate's report, specimen CSV, history entries, and uploaded files."""
        plate_id = _safe_name(plate_id)

        # Delete report HTML
        report_file = results / "reports" / f"QC_{plate_id}.html"
        if report_file.exists():
            report_file.unlink()

        # Delete this plate's per-plate CSVs (results + QC tables). They all
        # live in reports/; also clean any legacy specimens/ copy.
        for f in (results / "reports").glob(f"*_{plate_id}.csv"):
            try:
                f.unlink()
            except OSError:
                pass
        legacy_spec = results / "specimens" / f"specimens_{plate_id}.csv"
        if legacy_spec.exists():
            legacy_spec.unlink()

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
        # Honor the home-page standard-curve model selector for the whole batch,
        # and persist it so the choice sticks (keeps the dropdown, Settings, and
        # regenerated reports in sync).
        _model = request.form.get("curve_model", "").strip().lower()
        if _model in ("4pl", "5pl"):
            config.setdefault("panel", {})["curve_model"] = _model
            save_config(config)
        eff_model = config.get("panel", {}).get("curve_model", "5pl")
        ok = 0
        errors = 0
        for entry in registry_sorted:
            csv_path = results / "uploads" / entry["csv_filename"]
            if not csv_path.exists():
                flash(f"Couldn't regenerate {entry['plate_id']}: its source CSV "
                      f"({entry['csv_filename']}) is no longer in the uploads folder. "
                      f"Re-upload this plate's CSV to regenerate it (its existing "
                      f"report is kept).", "error")
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
                entry["curve_model"] = eff_model
                ok += 1
            except Exception as exc:
                traceback.print_exc()
                flash(f"Error regenerating {entry['plate_id']}: {exc}", "error")
                errors += 1

        # Persist the model used for each successfully regenerated plate.
        _save_registry(results, registry_sorted)
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

        # Standard-curve model default (5pl / 4pl). This is the default the
        # home-page selector starts from; each report can still override it.
        cm = request.form.get("curve_model", "5pl").strip().lower()
        config["panel"]["curve_model"] = cm if cm in ("4pl", "5pl") else "5pl"
        # Standard-curve pool mode + scoring pool.
        mode = request.form.get("pool_mode", "auto_select").strip()
        config["panel"]["pool_mode"] = mode if mode in ("per_pool", "auto_select") else "auto_select"
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
                    "bg_cv_threshold", "nc_cv_threshold", "hist_cv_threshold"):
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

    @app.route("/settings/example-config")
    def example_config():
        """Serve the annotated baseline config template (config.example.yaml)."""
        path = base / "config.example.yaml"
        if not path.exists():
            flash("Example config template not found.", "error")
            return redirect(url_for("settings"))
        return send_file(str(path), mimetype="text/yaml", as_attachment=True,
                         download_name="bangladesh_serosurveillance_config.example.yaml")

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
    registry = _load_registry(results_dir)
    order_map = {r["plate_id"]: r.get("sort_order", 9999) for r in registry}
    model_map = {r["plate_id"]: r.get("curve_model") for r in registry}

    reports = []
    for html_file in reports_dir.glob("QC_*.html"):
        plate_id = html_file.stem.replace("QC_", "")
        mtime = datetime.fromtimestamp(html_file.stat().st_mtime)
        # The single canonical per-plate results CSV (wide by standard).
        results_csv = reports_dir / f"results_{plate_id}.csv"
        _cm = (model_map.get(plate_id) or "").lower()
        fit_label = {"5pl": "5PL", "4pl": "4PL"}.get(_cm, "—")
        reports.append({
            "plate_id": plate_id,
            "filename": html_file.name,
            "date": mtime.strftime("%Y-%m-%d %H:%M"),
            "results_csv": results_csv.name if results_csv.exists() else None,
            "fit_label": fit_label,
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
    curve_model: str | None = None,
) -> None:
    """Add or update a plate entry in plate_registry.json."""
    registry = _load_registry(results_dir)
    existing = next((r for r in registry if r["plate_id"] == plate_id), None)
    if existing:
        existing["csv_filename"] = csv_filename
        existing["layout_filename"] = layout_filename
        existing["inputfile_filename"] = inputfile_filename
        if curve_model:
            existing["curve_model"] = curve_model
    else:
        registry.append({
            "plate_id": plate_id,
            "csv_filename": csv_filename,
            "layout_filename": layout_filename,
            "inputfile_filename": inputfile_filename,
            "sort_order": len(registry),
            "curve_model": curve_model,
        })
    _save_registry(results_dir, registry)
