import numpy as np
import pandas as pd


def fix_tw_etf_symbol(x):
    """
    Normalize Taiwan ETF symbols while preserving leading zeros.

    Examples:
    - 50 -> 0050
    - 713 / 0713 -> 00713
    - 6208 -> 006208
    """

    if pd.isna(x):
        return np.nan

    s = str(x).strip()

    if s.endswith(".0"):
        s = s[:-2]

    symbol_fix_map = {
        "50": "0050",
        "0050": "0050",
        "52": "0052",
        "0052": "0052",
        "56": "0056",
        "0056": "0056",
        "713": "00713",
        "0713": "00713",
        "00713": "00713",
        "878": "00878",
        "0878": "00878",
        "00878": "00878",
        "919": "00919",
        "0919": "00919",
        "00919": "00919",
        "929": "00929",
        "0929": "00929",
        "00929": "00929",
        "939": "00939",
        "0939": "00939",
        "00939": "00939",
        "940": "00940",
        "0940": "00940",
        "00940": "00940",
        "6208": "006208",
        "006208": "006208",
    }

    if s in symbol_fix_map:
        return symbol_fix_map[s]

    if len(s) <= 4:
        return s.zfill(4)

    return s