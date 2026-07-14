import numpy as np
import pandas as pd


def build_all_etf_event_data(
    panel_all: pd.DataFrame,
    event_summary: pd.DataFrame,
    symbols: list[str],
    window_before: int = 60,
    window_after: int = 10,
    price_col: str = "adj_close",
    allow_next_trading_day_match: bool = True,
):
    """
    Build event-window data for ETF dividend events.
    """

    event_rows = []
    skipped_rows = []

    panel_by_symbol = {
        symbol: g.sort_values("date").reset_index(drop=True)
        for symbol, g in panel_all[panel_all["symbol"].isin(symbols)].groupby("symbol")
    }

    events = event_summary[event_summary["symbol"].isin(symbols)].copy()
    events = events.sort_values(["symbol", "ex_date"]).reset_index(drop=True)

    for _, ev in events.iterrows():
        symbol = ev["symbol"]
        ex_date = ev["ex_date"]

        if symbol not in panel_by_symbol:
            skipped_rows.append({
                "symbol": symbol,
                "ex_date": ex_date,
                "reason": "symbol_not_in_panel",
            })
            continue

        p = panel_by_symbol[symbol].copy()
        dates = p["date"]

        exact_match = dates == ex_date

        if exact_match.any():
            ex_idx = int(np.where(exact_match.to_numpy())[0][0])
            matched_ex_date = ex_date
            match_type = "exact"
        elif allow_next_trading_day_match:
            candidate_idx = dates.searchsorted(ex_date)

            if candidate_idx >= len(dates):
                skipped_rows.append({
                    "symbol": symbol,
                    "ex_date": ex_date,
                    "reason": "ex_date_after_panel_end",
                })
                continue

            ex_idx = int(candidate_idx)
            matched_ex_date = p.loc[ex_idx, "date"]
            match_type = "next_trading_day"
        else:
            skipped_rows.append({
                "symbol": symbol,
                "ex_date": ex_date,
                "reason": "ex_date_not_trading_day",
            })
            continue

        start_idx = ex_idx - window_before
        end_idx = ex_idx + window_after

        if start_idx < 0 or end_idx >= len(p):
            skipped_rows.append({
                "symbol": symbol,
                "ex_date": ex_date,
                "reason": "insufficient_window",
                "ex_idx": ex_idx,
                "panel_len": len(p),
            })
            continue

        window = p.loc[start_idx:end_idx].copy()
        window["relative_day"] = np.arange(-window_before, window_after + 1)
        window["event_id"] = f"{symbol}_{pd.to_datetime(ex_date).strftime('%Y%m%d')}"
        window["event_ex_date"] = ex_date
        window["matched_ex_date"] = matched_ex_date
        window["ex_date_match_type"] = match_type

        for col in event_summary.columns:
            if col == "symbol":
                continue
            if col not in window.columns:
                window[col] = ev[col]
            else:
                window[f"event_{col}"] = ev[col]

        event_rows.append(window)

    event_data = pd.concat(event_rows, ignore_index=True) if event_rows else pd.DataFrame()
    skipped = pd.DataFrame(skipped_rows)

    return event_data, skipped


def add_event_features(
    event_data: pd.DataFrame,
    price_col: str = "adj_close",
):
    """
    Add event features such as cumulative return and volume ratio.
    """

    df = event_data.copy()
    df = df.sort_values(["event_id", "relative_day"]).reset_index(drop=True)

    start_price = df.groupby("event_id")[price_col].transform("first")
    df["event_start_price"] = start_price
    df["cum_return_from_start"] = df[price_col] / df["event_start_price"] - 1
    df["daily_return"] = df.groupby("event_id")[price_col].pct_change()

    if "volume" in df.columns:
        pre_event_volume_median = (
            df[df["relative_day"] < 0]
            .groupby("event_id")["volume"]
            .median()
        )
        df["pre_event_volume_median"] = df["event_id"].map(pre_event_volume_median)
        df["volume_ratio"] = df["volume"] / df["pre_event_volume_median"]
    else:
        df["pre_event_volume_median"] = np.nan
        df["volume_ratio"] = np.nan

    return df