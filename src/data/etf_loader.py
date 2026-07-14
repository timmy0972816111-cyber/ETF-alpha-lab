import pandas as pd

from src.data.symbol_utils import fix_tw_etf_symbol


def load_etf_panel(panel_path):
    """
    Load ETF daily panel data.
    """

    panel = pd.read_csv(panel_path, dtype={"symbol": str})

    panel["symbol"] = panel["symbol"].apply(fix_tw_etf_symbol)

    if "date" in panel.columns:
        panel["date"] = pd.to_datetime(panel["date"], errors="coerce")

    panel = (
        panel
        .dropna(subset=["symbol", "date"])
        .sort_values(["symbol", "date"])
        .reset_index(drop=True)
    )

    return panel


def load_etf_dividend_events(events_path):
    """
    Load ETF dividend event data.
    """

    events = pd.read_csv(events_path, dtype={"symbol": str})

    events["symbol"] = events["symbol"].apply(fix_tw_etf_symbol)

    for col in ["ex_date", "record_date", "pay_date", "announcement_date"]:
        if col in events.columns:
            events[col] = pd.to_datetime(events[col], errors="coerce")

    events = (
        events
        .dropna(subset=["symbol", "ex_date"])
        .sort_values(["symbol", "ex_date"])
        .reset_index(drop=True)
    )

    return events


def build_valid_etf_universe(
    panel_all,
    event_summary,
    exclude_keywords=None,
):
    """
    Build valid ETF universe from panel and event data.
    """

    if exclude_keywords is None:
        exclude_keywords = [
            "正2", "反1", "反向", "槓桿", "期貨", "VIX", "期信",
            "2X", "Bear", "Bull", "Inverse", "Leveraged",
        ]

    name_col = None

    for candidate in ["etf_name", "fund_name", "name"]:
        if candidate in panel_all.columns:
            name_col = candidate
            break

    if name_col is None:
        for candidate in ["etf_name", "fund_name", "name"]:
            if candidate in event_summary.columns:
                name_col = candidate
                break

    if name_col and name_col in panel_all.columns:
        etf_info = panel_all[["symbol", name_col]].drop_duplicates("symbol").copy()
    elif name_col and name_col in event_summary.columns:
        etf_info = event_summary[["symbol", name_col]].drop_duplicates("symbol").copy()
    else:
        etf_info = panel_all[["symbol"]].drop_duplicates().copy()
        etf_info["etf_name"] = ""
        name_col = "etf_name"

    etf_info["name_for_filter"] = etf_info[name_col].astype(str)
    etf_info["is_excluded_by_name"] = etf_info["name_for_filter"].apply(
        lambda x: any(k in x for k in exclude_keywords)
    )

    valid_symbols = sorted(
        set(etf_info.loc[~etf_info["is_excluded_by_name"], "symbol"])
        & set(event_summary["symbol"])
        & set(panel_all["symbol"])
    )

    return valid_symbols, etf_info