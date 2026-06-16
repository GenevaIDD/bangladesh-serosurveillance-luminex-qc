"""Panel definition and default thresholds for the Bangladesh National
Serosurveillance 202-plex Luminex assay (384-well, Intelliflex, High PMT).

All configurable values have defaults here. User overrides are stored in
~/bangladesh-serosurveillance-luminex-qc-results/config.yaml and loaded at
runtime via settings.py.

The production panel is 202-plex; pilot plates ran fewer beads due to reagent
shortages. The per-plate panel is always auto-derived from the xPONENT
``Median`` header on ingest, so the list below is only a display/fallback
default.
"""

from __future__ import annotations

APP_VERSION = "0.1.0-bangladesh"

RESULTS_DIR_NAME = "bangladesh-serosurveillance-luminex-qc-results"

# --- 202-plex antigen panel (auto-derived from xPONENT header on
# first ingest; this list is the canonical default / fallback). ---

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
# report. Editable from the Settings page. Empty by default for Bangladesh
# (the legacy MPXV/Uvira exclusions do not apply to this assay).
EXCLUDED_ANALYTES: list[str] = []

# --- QC thresholds ---

BEAD_COUNT_MIN = 30          # Red below this
BEAD_COUNT_WARN = 50         # Yellow between MIN and WARN; green above
RECOVERY_TOLERANCE = 0.30    # ±30% Obs/Exp recovery for standard curve points
PC_CV_THRESHOLD = 0.20       # Flag a standard point when the %CV between its
                             # duplicate wells exceeds this (PC replicate QC)

# Shared "≥ X% problematic" threshold used by the bead-count and range
# summary cards. An antigen is "problem" when at least this fraction of
# its wells (resp. samples) hits the problem state (red/yellow for bead
# counts; BELOW_RANGE / ABOVE_RANGE for ranges).
PROBLEM_FRACTION_THRESHOLD = 0.20

# Background QC. The max-MFI threshold defaults to 300 for Bangladesh
# (High PMT) and is editable on the Settings page. Formal Background
# flagging rules are still being finalized (see BANGLADESH_TODO Section 4).
BG_CV_THRESHOLD = 0.25       # Background %CV reference threshold
BG_MAX_MFI = 300             # Background max-MFI reference threshold

# Standard-curve dilutions are NOT a fixed series for Bangladesh — each
# control pool carries its own dilution series encoded in the sample name
# (e.g. "Pilot Control: Dengue pool 1:4000"), parsed per-well in classify.py.

SPECIMEN_DEFAULT_DILUTION = 100  # placeholder; specimens are run at a single dilution

# --- Well classification patterns ---
# Bangladesh sample-name conventions (no Intelliflex input file; the
# Sample name in the CSV is the only classification signal):
#
#   Background  : "Background0"                          → background
#   NC          : "Pilot Control: Negative 0 , 1:1000"   → nc
#                 "Pilot Control: Negative 49 , 1:1000"
#   PC/standard : "Pilot Control: <pool> [<descr>] <dilution>"  → pc
#                 e.g. "Pilot Control: Dengue pool 1:4000",
#                      "Pilot Control: Orpal pool 1:800",
#                      "Pilot Control: Anti-OSP & cTxB & HlyE pool 1:16",
#                      "Pilot Control: HlyE 50 ng/mL",
#                      "Pilot Control: Cholera High (1:1000)"  (single point)
#   Specimen    : "{id}_r3_{Serum|DBS}"                  → specimen
#
# Classification order in classify.py is: background → nc → pc → specimen,
# and patterns are matched with re.search (not anchored) so the shared
# "Pilot Control:" prefix on NC + PC samples resolves correctly (NC wins
# because it is checked first). Patterns are editable on the Settings page.
PC_PATTERNS = [r"^Pilot Control:"]
BACKGROUND_PATTERNS = [r"^Background"]
NC_PATTERNS = [r"Negative"]

# --- Structured defaults dict for settings.py ---

DEFAULTS = {
    "assay": {
        "name": "Bangladesh Serosurveillance 202-Plex Luminex",
        "description": "202-plex Luminex immunoassay on Intelliflex (High PMT, 384-well) — Bangladesh National Serosurveillance",
    },
    "panel": {
        # bead_region is informational only on Intelliflex; analytes are
        # keyed by name in the xPONENT export.
        "antigens": [{"name": a, "bead_region": None} for a in ANTIGENS],
        "excluded_analytes": list(EXCLUDED_ANALYTES),
        # Priority antigens whose standard curves are meant to be
        # interpreted. Empty list = all antigens (default). Curves are
        # still fit for every antigen; this only filters the display in
        # the Standard Curve Summary / All Curves Overview (Section 5).
        "priority_antigens": [],
        # How standard curves are presented/scored:
        #   "per_pool"    — fit & show a curve for EVERY (pool × antigen);
        #                   no antigen→pool matching or auto-selection.
        #   "auto_select" — pick one calibrating pool per antigen (pathogen
        #                   name match, tie-broken by best fit).
        "pool_mode": "per_pool",
        # In per_pool mode, the single pool used to compute specimen RAU /
        # range status (Range Matrix, clean results). Blank = first pool.
        "scoring_pool": "",
        # Optional user rules for auto_select mode: "<regex> => <pool name>"
        # strings, first match wins, applied before the built-in pathogen
        # heuristic. Lets the lab define antigen→pool mapping without code.
        "pool_assignment_rules": [],
    },
    "well_classification": {
        "pc_patterns": PC_PATTERNS,
        "background_patterns": BACKGROUND_PATTERNS,
        "nc_patterns": NC_PATTERNS,
    },
    "standard": {
        "bead_batch": "",
    },
    "specimens": {
        "default_dilution": SPECIMEN_DEFAULT_DILUTION,
    },
    "qc_thresholds": {
        "bead_count_min": BEAD_COUNT_MIN,
        "bead_count_warn": BEAD_COUNT_WARN,
        "recovery_tolerance": RECOVERY_TOLERANCE,
        "pc_cv_threshold": PC_CV_THRESHOLD,
        "drop_outlier": True,
        "problem_fraction_threshold": PROBLEM_FRACTION_THRESHOLD,
        "bg_cv_threshold": BG_CV_THRESHOLD,
        "bg_max_mfi": BG_MAX_MFI,
    },
}


