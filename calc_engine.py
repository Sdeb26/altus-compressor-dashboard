"""
Altus Compressor Validation Tool — Python calc engine.
Reproduces, formula-for-formula, the logic in Altus_Compressor_Validation_Tool__v3.xlsx
(Calc_Engine / Input_Config / Equipment_Config / Metric_Map sheets).
"""
import pandas as pd
import numpy as np

# ---------------------------------------------------------------------------
# Metric definitions — mirrors the Metric_Map sheet exactly
# ---------------------------------------------------------------------------
METRICS = [
    # key, label, tolerance_type, unit, default_tol1, default_tol2, constant_expected, denom
    ("suct_press",  "Suction Pressure vs Setpoint",        "PercentDeviation", "psig", 0.10, 0.20, False, "expected"),
    ("disc_temp",   "Discharge Temp (ideal ceiling)",      "MarginDegF",       "deg F", 10,   0,    False, None),
    # NOTE: TR_FL / TR_PL / kW_per_Ton divide by the LIVE reading (not Expected) in the
    # original workbook (Calc_Engine columns K/N/Q) — zero-check is on Live too, so an
    # idle compressor (live=0) correctly shows N/A instead of a meaningless huge deviation.
    # This is reproduced exactly, not "fixed", to match the delivered tool.
    ("tr_fl",       "TR_FL (Full Load Capacity)",          "PercentDeviation", "Tons Refrigeration", 0.10, 0.20, False, "live"),
    ("tr_pl",       "TR_PL (Part Load Capacity)",          "PercentDeviation", "Tons Refrigeration", 0.10, 0.20, False, "live"),
    ("kw_per_ton",  "kW / Ton",                            "PercentDeviation", "kW/Ton", 0.10, 0.20, False, "live"),
    ("slide_vlv",   "Slide Valve Position",                "RangeCheck",       "%",    None, None, False, None),
    ("suct_temp",   "Suction Temp vs Design SST",          "PercentDeviation", "deg F", 0.10, 0.20, False, "expected"),
    ("disc_press",  "Discharge Pressure vs Design SCP",    "PercentDeviation", "psig", 0.10, 0.20, True, "expected"),
    ("motor_kw",    "Motor kW vs Motor Limit",              "CeilingPercent",   "kW",   0.10, 0,    True, "expected"),
    ("kwh",         "kWh (re-integrated)",                 "PercentDeviation", "kWh",  0.10, 0.20, False, "expected"),
    ("motor_kw_sv", "Motor kW vs Slide Valve Position",    "PercentDeviation", "kW",   0.10, 0.20, False, "expected"),
]
METRIC_BY_KEY = {m[0]: m for m in METRICS}

OBSERVED_INTERVAL_SEC = 101  # Input_Config!$B$18


def load_equipment_config(path="equipment_config.csv"):
    df = pd.read_csv(path)
    df["comp"] = df["comp"].astype(int)
    return df.set_index("comp")


def _flag_percent_deviation(live, expected, tol1, tol2, denom="expected"):
    denom_series = expected if denom == "expected" else live
    with np.errstate(divide="ignore", invalid="ignore"):
        dev = np.abs(live - expected) / np.abs(denom_series)
    flag = np.select(
        [denom_series == 0, dev <= tol1, dev <= tol2],
        ["N/A", "Normal", "Warning"],
        default="Invalid",
    )
    flag = np.where(np.isnan(live) | np.isnan(expected), "N/A", flag)
    return pd.Series(flag, index=live.index)


def _flag_margin_degf(live, expected, tol1, tol2):
    margin = expected - live
    flag = np.select(
        [margin > tol1, margin >= tol2],
        ["Normal", "Warning"],
        default="Invalid",
    )
    flag = np.where(np.isnan(live) | np.isnan(expected), "N/A", flag)
    return pd.Series(flag, index=live.index)


def _flag_range_check(live):
    flag = np.select(
        [live.isna(), (live < 0) | (live > 100)],
        ["N/A", "Invalid"],
        default="Normal",
    )
    return pd.Series(flag, index=live.index)


def _flag_ceiling_percent(live, expected, tol1, tol2):
    with np.errstate(divide="ignore", invalid="ignore"):
        margin_ratio = (expected - live) / expected
    flag = np.select(
        [expected == 0, margin_ratio > tol1, margin_ratio >= tol2],
        ["N/A", "Normal", "Warning"],
        default="Invalid",
    )
    flag = np.where(np.isnan(live) | np.isnan(expected), "N/A", flag)
    return pd.Series(flag, index=live.index)


def compute_compressor(raw_df: pd.DataFrame, comp: int, equip_cfg: pd.DataFrame) -> pd.DataFrame:
    """Computes Live/Expected/Flag for all 11 metrics for one compressor.
    Returns a DataFrame indexed like raw_df, with columns <key>_live/_expected/_flag.
    """
    cfg = equip_cfg.loc[comp]
    c = {f"c{i}": cfg[f"c{i}"] for i in range(1, 11)}
    design_sst = cfg["design_sst"]  # may be NaN (Comp 8)
    design_sct = cfg["design_sct"]
    motor_kw_rated = cfg["motor_kw_rated"]

    def col(tag):
        name = f"C{comp}_{tag}"
        if name not in raw_df.columns:
            return pd.Series(np.nan, index=raw_df.index)
        return raw_df[name]

    out = pd.DataFrame(index=raw_df.index)
    out["timestamp"] = raw_df["timestamp"]

    suct_press = col("suct_press")
    suct_press_sp = col("suct_press_sp")
    disc_press = col("disc_press")
    disc_temp = col("disc_temp")
    suct_temp = col("suct_temp")
    tr_fl_live = col("tr_fl")
    tr_pl_live = col("tr_pl")
    slide_vlv = col("slide_vlv_pos")
    kw_per_ton_live = col("kw_per_ton")
    motor_kw_live = col("motor_kw")
    kwh_live = col("kwh")

    # 1. Suction Pressure vs its own live setpoint
    out["suct_press_live"] = suct_press
    out["suct_press_expected"] = suct_press_sp

    # 2. Discharge Temp vs isentropic ideal ceiling (GPSA/Purdue relation, k=1.3 for NH3)
    T1_K = (suct_temp - 32) * 5 / 9 + 273.15
    ratio = (disc_press + 14.696) / (suct_press + 14.696)
    T2_ideal_K = T1_K * (ratio ** (0.3 / 1.3))
    disc_temp_expected = (T2_ideal_K - 273.15) * 9 / 5 + 32
    out["disc_temp_live"] = disc_temp
    out["disc_temp_expected"] = disc_temp_expected

    # 3. TR_FL — SOO Sec 3.4 polynomial. SCT substituted with live Discharge Temp
    #    (validated practical substitute — see README Known Open Items #1).
    SST, SCT = suct_temp, disc_temp
    tr_fl_raw = (
        c["c1"] + c["c2"] * SST + c["c3"] * SCT + c["c4"] * SST ** 2
        + c["c5"] * SST * SCT + c["c6"] * SCT ** 2 + c["c7"] * SST ** 3
        + c["c8"] * SST ** 2 * SCT + c["c9"] * SST * SCT ** 2 + c["c10"] * SCT ** 3
    )
    tr_fl_expected = tr_fl_raw * 474.3 / 12000
    out["tr_fl_live"] = tr_fl_live
    out["tr_fl_expected"] = tr_fl_expected

    # 4. TR_PL = TR_FL(calc) x Slide Valve %
    tr_pl_expected = tr_fl_expected * slide_vlv / 100
    out["tr_pl_live"] = tr_pl_live
    out["tr_pl_expected"] = tr_pl_expected

    # 5. kW/Ton = Motor kW (measured) / TR_PL(calc)
    with np.errstate(divide="ignore", invalid="ignore"):
        kw_per_ton_expected = motor_kw_live / tr_pl_expected
    out["kw_per_ton_live"] = kw_per_ton_live
    out["kw_per_ton_expected"] = kw_per_ton_expected

    # 6. Slide Valve Position — range check only
    out["slide_vlv_live"] = slide_vlv

    # 7. Suction Temp vs Design SST (constant nameplate value; N/A if undocumented, e.g. Comp 8)
    out["suct_temp_live"] = suct_temp
    out["suct_temp_expected"] = pd.Series(design_sst, index=raw_df.index)

    # 8. Discharge Pressure vs Design SCP — pressure equivalent of design condensing temp
    #    (SOO Sec 2.3.B formula inverted: (Design_SCT - 19.5) / 0.575)
    disc_press_expected = (design_sct - 19.5) / 0.575
    out["disc_press_live"] = disc_press
    out["disc_press_expected"] = pd.Series(disc_press_expected, index=raw_df.index)

    # 9. Motor kW vs nameplate Motor Limit (one-sided ceiling)
    out["motor_kw_live"] = motor_kw_live
    out["motor_kw_expected"] = pd.Series(motor_kw_rated, index=raw_df.index)

    # 10. kWh re-integrated — anchored to the PLC's own first reading, then
    #     Sum(Motor kW x elapsed hours) added cumulatively.
    elapsed_hours = out["timestamp"].diff().dt.total_seconds() / 3600
    elapsed_hours.iloc[0] = 0
    increment = (motor_kw_live * elapsed_hours).fillna(0)
    first_valid = kwh_live.iloc[0] if not pd.isna(kwh_live.iloc[0]) else 0
    kwh_expected = first_valid + increment.cumsum()
    out["kwh_live"] = kwh_live
    out["kwh_expected"] = kwh_expected

    # 11. Motor kW vs Slide Valve Position (working proportional estimate, not
    #     a manual-sourced formula — correlation 0.5-0.93 across the fleet).
    motor_kw_sv_expected = motor_kw_rated * slide_vlv / 100
    out["motor_kw_sv_live"] = motor_kw_live
    out["motor_kw_sv_expected"] = pd.Series(motor_kw_sv_expected, index=raw_df.index)

    return out


def apply_flags(calc_df: pd.DataFrame, tol_overrides: dict | None = None) -> pd.DataFrame:
    """Adds <key>_flag columns using each metric's tolerance type.
    tol_overrides: {metric_key: (tol1_pct, tol2_pct)} — percent as 0-1 fraction, or None to use default.
    Mirrors the Dashboard's Tolerance Override cells: only applies to PercentDeviation/CeilingPercent metrics.
    """
    tol_overrides = tol_overrides or {}
    out = calc_df.copy()
    for key, label, ttype, unit, tol1_def, tol2_def, const_exp, denom in METRICS:
        live = calc_df[f"{key}_live"]
        if ttype == "RangeCheck":
            out[f"{key}_flag"] = _flag_range_check(live)
            continue
        expected = calc_df[f"{key}_expected"]
        if ttype == "MarginDegF":
            out[f"{key}_flag"] = _flag_margin_degf(live, expected, tol1_def, tol2_def)
            continue
        tol1, tol2 = tol_overrides.get(key, (tol1_def, tol2_def))
        if ttype == "PercentDeviation":
            out[f"{key}_flag"] = _flag_percent_deviation(live, expected, tol1, tol2, denom=denom)
        elif ttype == "CeilingPercent":
            out[f"{key}_flag"] = _flag_ceiling_percent(live, expected, tol1, tol2)
    return out
