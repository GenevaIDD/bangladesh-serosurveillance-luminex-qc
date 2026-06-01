# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Bangladesh Serosurveillance Luminex QC Tool — macOS build."""

from pathlib import Path

block_cipher = None
project_root = Path(SPECPATH)

a = Analysis(
    [str(project_root / "run.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        # Pipeline report template
        (str(project_root / "templates" / "report.html"), "templates"),
        # Flask web UI templates
        (str(project_root / "templates" / "web"), "templates/web"),
        # Bundled vendor JS (SortableJS — keeps app fully offline)
        (str(project_root / "static" / "vendor"), "static/vendor"),
        # Specification document
        (str(project_root / "SPECIFICATION.md"), "."),
    ],
    hiddenimports=[
        "src",
        "src.main",
        "src.app",
        "src.pipeline",
        "src.config",
        "src.parse_xponent",
        "src.parse_layout",
        "src.classify",
        "src.qc_beads",
        "src.qc_standard_curve",
        "src.qc_nc",
        "src.qc_background",
        "src.qc_history",
        "src.plate_summary",
        "src.report",
        "src.settings",
        "yaml",
        "scipy.optimize",
        "scipy.special",
        "scipy.stats",
        "scipy.special._cdflib",
        "plotly",
        "plotly.graph_objects",
        "plotly.subplots",
        "plotly.io",
        "plotly.offline",
        "matplotlib",
        "matplotlib.pyplot",
        "matplotlib.backends.backend_agg",
        "jinja2",
        "openpyxl",
        "flask",
        "flask.json",
        "werkzeug",
        "werkzeug.serving",
        "markupsafe",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "notebook", "IPython"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Bangladesh-Serosurveillance-Luminex-QC",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(project_root / "assets" / "app_icon.icns"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Bangladesh-Serosurveillance-Luminex-QC",
)

# macOS .app bundle — no Terminal window on launch
app = BUNDLE(
    coll,
    name="Bangladesh Serosurveillance Luminex QC.app",
    icon=str(project_root / "assets" / "app_icon.icns"),
    bundle_identifier="ch.unige.bangladesh-serosurveillance-luminex-qc",
    info_plist={
        "LSBackgroundOnly": False,
        "NSHighResolutionCapable": True,
    },
)
