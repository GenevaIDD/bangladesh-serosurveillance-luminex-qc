"""Panel definition and default thresholds for Uvira 200-plex Luminex assay.

All configurable values have defaults here. User overrides are stored in
~/uvira-luminex-qc-results/config.yaml and loaded at runtime via settings.py.

NOTE — Migration from the prior MPXV 12-plex codebase is in progress.
The aliases at the bottom of this file (``MPXV_ANTIGENS``, ``MPXV_KIT_CONTROLS``)
exist only so that downstream modules that still import them keep working
until each is rewritten in Sections 3–5 of UVIRA_TODO.md. Remove the
aliases when no callers remain.
"""

APP_VERSION = "0.9.0-uvira"

RESULTS_DIR_NAME = "uvira-luminex-qc-results"

# --- Uvira 200-plex antigen panel (auto-derived from xPONENT header on
# first ingest; this list is the canonical default). ---

ANTIGENS = [
    "RES_Ade3", "RES_Ade5_hexon", "TOXO_TgAMA1", "RES_Ade40_hexon",
    "VPD_B_pertussis_FHA", "HHV_CMV", "BAC_N_meningitidis_C_CPS",
    "HHV_EBV_gp125", "OTH_Echovirus", "ENT_EnteroV_CoxB3_VP1", "HEP_HepA",
    "ARB_CCHFV_NP", "ARB_CHIKV_E2", "ARB_CHIKV_VLP", "ARB_DENV1_NS1",
    "HEP_HBcAg", "HEP_HBeAg", "ARB_DENV1_VLP", "ARB_DENV2_NS1",
    "ARB_DENV2_VLP", "ARB_DENV3_NS1", "ARB_DENV3_VLP", "HEP_HBsAg",
    "HEP_HCcAg", "ARB_DENV4_NS1", "ARB_DENV4_VLP", "ARB_JEV_E",
    "ARB_JEV_NS1", "ARB_MAYV_E2", "ARB_ONNV_E2", "HHV_HHV6B", "HHV_HHV7",
    "HEP_HEV_ORF2", "ARB_OROV_NP", "ARB_RRV_Polyprot", "ARB_RVFV",
    "ARB_USUV_NS1", "ARB_WNV_NS1", "ARB_WNV_DIII", "BAC_S.typhi_HlyE",
    "STI_HPV18", "ARB_YFV_E", "ARB_YFV_NS1", "ARB_ZIKV_NS1", "ARB_ZIKV_VLP",
    "HHV_HSV1", "HHV_HSV2", "HHV_HSV2_gG2", "HCoV_229E_S", "OTH_TgSAG1",
    "OTH_TgGRA7", "NTD_Leishmania_K28", "CHO_CtxB", "CHO_Inaba_OSP",
    "CHO_Ogawa_OSP", "CTRL_E.coli", "HCoV_HKU1_NP", "HCoV_HKU1_S1",
    "HCoV_NL63_NP", "NTD_Bm14", "NTD_pgp3", "NTD_CT694", "NTD_cp23",
    "NTD_VSP3", "NTD_VSP5", "NTD_NIE", "HCoV_NL63_S", "HCoV_OC43_NP",
    "HCoV_OC43_S1", "RES_hMPVA", "CTRL_BSA", "VPD_Bordetella_p_Tox",
    "VPD_Diphteria_Tox", "VPD_measles_NP", "VPD_Tetanus_Toxin",
    "MAL_PfMSP1", "MAL_PvMSP1", "RES_hMPVB", "HCoV_229E_NP",
    "RES_measles_lysate", "NTD_Leishmania_K39", "RES_mumps_NP",
    "VPD_N_meningitidis_B_MP", "ENT_Norovirus_GII.4_VLP",
    "ENT_Norovirus_GII.6_VLP", "ENT_Parvovirus", "RES_RSVA", "RES_RSVB",
    "RES_Rhinovirus_T1A", "ENT_Rotavirus_VP7", "RES_RSVA_gG", "VPD_Rub_VLP",
    "SARS_CoV-2_Wuhan_NP", "SARS_CoV-2_Omicron_RBD",
    "SARS_CoV-2_Wuhan_RBD", "SARS_CoV-2_Spike_Wuhan", "SARS_CoV-2_S2_Wuhan",
    "SARS_CoV-2_Spike_Omicron", "HHV_VZV_gEgI", "TBD_p41pKo",
    "TBD_VlsEPBi", "TBD_VlsEB31", "TBD_P41B31", "TBD_p25/23_OspC",
    "TBD_OspA", "TBD_B.Afzelii", "TBD_B.b.Flagellin", "TBD_B.b.VIsE",
    "TBD_B.Garinii", "FLU_H5N1_HA1_D_Hong_Kong_1997",
    "FLU_H5N1_HA1_Hong_Kong_1997", "FLU_H5N1_HA1_Thailand_2004",
    "FLU_H5N1_HA1_vietnam_2004", "FLU_H5N1_HA_T_Turkey_2005",
    "FLU_H5N1_HA1_Egypt_2007", "FLU_H5N1_HA1_Hubei_2010",
    "FLU_H5N1_HA1_Egypt_2015", "FLU_H1N1_HA_Brevig_1918",
    "FLU_H1N1_HA1_Brevig_1918", "FLU_H1N1_HA_WSN_1933",
    "FLU_H1N1_HA1_WSN_1933", "FLU_H1N1_HA_Puerto_Rico_1934",
    "FLU_H1N1_HA1_Puerto_Rico_1934", "FLU_H1N1_HA1_Fort_Monmouth_1947",
    "FLU_H1N1_HA_Denver_1957", "FLU_H1N1_HA1_URSS_1977",
    "FLU_H1N1_HA_URSS_1977", "FLU_H1N1_HA_Taiwan_1986",
    "FLU_H1N1_HA_Beijing_1995", "POX_MpoxV_HA/B2R", "POX_MpoxV_A44R",
    "POX_MpoxV_E8L_C_His", "MAL_Po_MSP1", "MAL_Pm_MSP1", "MAL_PfAMA1",
    "FLU_B_HA_Maryland_1959", "MAL_PfGlurpR2", "FLU_B_NP_Brisbane_2008",
    "MAL_PfSBP1", "MAL_PfCSP", "CTRL_GST", "VPD_Tet_tox", "STI_HPV16",
    "FLU_H1N1_HA1_Beijing_1995", "FLU_H1N1_HA_New_Caledonia_1999",
    "FLU_H1N1_HA1_New_Caledonia_1999", "FLU_H1N1_HA_Brisbane_2007",
    "FLU_H1N1_HA1_Brisbane_2007", "FLU_H1N1_HA_California_2009",
    "FLU_H1N1_HA1_California_2009", "FLU_H1N1_HA1_Michigan_2015",
    "FLU_H3N2_HA_Hong_Kong_1968", "FLU_H3N2_HA1_Hong_Kong_1968",
    "FLU_H3N2_HA1_England_1972", "FLU_H3N2_HA1_Victoria_1975",
    "FLU_H3N2_HA1_Texas_1977", "FLU_H3N2_HA_Bangkok_1979",
    "FLU_H3N2_HA1_Christchurch_1985", "FLU_H3N2_HA_Shanghai_1987",
    "FLU_H3N2_HA1_Guizhou_1989", "FLU_H3N2_HA1_Beijing_1992",
    "FLU_H3N2_HA1_Johannesburg_1994", "FLU_H3N2_HA1_Sydney_1997",
    "FLU_H3N2_HA1_Fujian_2002", "FLU_H3N2_HA1_California_2004",
    "FLU_H3N2_HA1_New_York_2004", "FLU_H3N2_HA_Brisbane_2007",
    "FLU_H3N2_HA1_Brisbane_2007", "FLU_H3N2_HA_Perth_2009",
    "FLU_H3N2_HA1_Perth_2009", "FLU_H3N2_HA1_Victoria_2011",
    "FLU_H3N2_HA1_Switzerland_2013", "FLU_H3N2_HA1_Hong_Kong_2014",
    "FLU_H3N2_HA_Singapore_2016", "FLU_H3N2_HA_Kansas_2017",
    "FLU_H3N2_HA_Hong_Kong_2019", "FLU_H3N2_HA_Cambodia_2020",
    "FLU_H3N2_HA_Darwin_2021", "POX_VacciniaV", "CTRL_SNAP",
    "ARB_SNAP_DENV1_DIII", "ARB_SNAP_DENV2_DIII", "ARB_SNAP_DENV3_DIII",
    "ARB_SNAP_DENV4_DIII", "ARB_SNAP_WNV_DIII", "ARB_SNAP_YFV_DIII",
    "ARB_SNAP_JEV_DIII", "ARB_SNAP_ZIKV_DIII", "ARB_SNAP_USUV_DIII",
    "HAN_SEOV", "HAN_PUUV", "HAN_ANDES", "STI_Chlamydia_trachomatis",
    "BAC_Chlamydia_pneumoniae", "ENT_H_pylori",
    "RES_Legionella_pneumophila", "BAC_Myco_pneumoniae",
    "BAC_N_gonorrhea", "BAC_Streptococcus_pneumoniae", "OTH_JC_virus",
]

# Bead regions known to have been added in error during plate setup. These
# are kept in the data (soft flag) but rendered visually muted in the
# report. Editable from the Settings page.
EXCLUDED_ANALYTES = [
    "FLU_B_HA_Maryland_1959",
    "FLU_B_NP_Brisbane_2008",
    "VPD_Tet_tox",
]

# Kit-control bead concept does not apply to the Uvira assay; the NC for
# this plate is the Row-A "Background" well, not a kit-bead.
KIT_CONTROLS: list[str] = []

ALL_BEADS = ANTIGENS + KIT_CONTROLS

# --- QC thresholds ---

BEAD_COUNT_MIN = 30          # Red below this
BEAD_COUNT_WARN = 50         # Yellow between MIN and WARN; green above
PC_CV_THRESHOLD = 0.25       # Unused on Uvira (no PC duplicates) — kept for legacy callers
RECOVERY_TOLERANCE = 0.30    # ±30% Obs/Exp recovery for standard curve points

# --- Standard curve dilution series ---
# 10-point 4-fold dilution from Std+Mabs row of the dilution-series screenshot.
# Standard1 maps to STANDARD_DILUTIONS[0] (the most concentrated point) and
# Standard10 to STANDARD_DILUTIONS[9] (the most dilute).
STANDARD_DILUTIONS = [
    62.5, 250.0, 1000.0, 4000.0, 16000.0,
    64000.0, 256000.0, 1024000.0, 4096000.0, 16384000.0,
]

SPECIMEN_DEFAULT_DILUTION = 100  # placeholder; specimens are run at a single dilution

# --- Well classification patterns ---
# Intelliflex inputfile labels A1..A10 = "Standard" (sample names
# "Standard1".."Standard10"), A11/A12 = "Background" (sample name
# "Background"). Specimen sample names are FD-prefixed barcodes.
PC_PATTERNS = [r"^Standard\d+$"]
NC_PATTERNS = [r"^Background"]

# --- Structured defaults dict for settings.py ---

DEFAULTS = {
    "assay": {
        "name": "Uvira 200-Plex Luminex",
        "description": "200-plex Luminex immunoassay on Intelliflex (Uvira pilot)",
    },
    "panel": {
        # bead_region is informational only on Intelliflex; analytes are
        # keyed by name in the xPONENT export.
        "antigens": [{"name": a, "bead_region": None} for a in ANTIGENS],
        "kit_controls": [],
        "excluded_analytes": list(EXCLUDED_ANALYTES),
    },
    "well_classification": {
        "pc_patterns": PC_PATTERNS,
        "nc_patterns": NC_PATTERNS,
    },
    "standard": {
        "dilutions": list(STANDARD_DILUTIONS),  # explicit (not "auto") — Intelliflex doesn't encode them in sample names
        "bead_batch": "",
    },
    "specimens": {
        "default_dilution": SPECIMEN_DEFAULT_DILUTION,
    },
    "qc_thresholds": {
        "bead_count_min": BEAD_COUNT_MIN,
        "bead_count_warn": BEAD_COUNT_WARN,
        "pc_cv_threshold": PC_CV_THRESHOLD,
        "recovery_tolerance": RECOVERY_TOLERANCE,
        "drop_outlier": True,
    },
}


# ---------------------------------------------------------------------------
# Deprecated aliases — to be removed once Sections 3–5 land.
# ---------------------------------------------------------------------------

MPXV_ANTIGENS = ANTIGENS
MPXV_KIT_CONTROLS = KIT_CONTROLS
