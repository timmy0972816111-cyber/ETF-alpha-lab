import numpy as np
import pandas as pd

from src.data.symbol_utils import fix_tw_etf_symbol


def calculate_event_trade_return_enriched(
    event_data: pd.DataFrame,
    price_col: str,
    entry_day: int,
    exit_day: int,
    fee_rate: float = 0.0008,
):
    """
    Calculate event trade returns.
    """

    rows = []

    for event_id, g in event_data.groupby("event_id"):
        g = g.set_index("relative_day").sort_index()

        if entry_day not in g.index or exit_day not in g.index:
            continue

        entry_row = g.loc[entry_day]
        exit_row = g.loc[exit_day]

        entry_price = entry_row[price_col]
        exit_price = exit_row[price_col]

        if pd.isna(entry_price) or pd.isna(exit_price) or entry_price == 0:
            continue

        raw_return = exit_price / entry_price - 1
        net_return = raw_return - 2 * fee_rate

        close_entry = entry_row["close"] if "close" in g.columns else entry_price
        dividend = entry_row["dividend"] if "dividend" in g.columns else np.nan

        dividend_yield_on_entry = (
            dividend / close_entry
            if pd.notna(dividend) and pd.notna(close_entry) and close_entry != 0
            else np.nan
        )

        entry_premium = entry_row["premium_discount"] if "premium_discount" in g.columns else np.nan
        exit_premium = exit_row["premium_discount"] if "premium_discount" in g.columns else np.nan
        entry_volume_ratio = entry_row["volume_ratio"] if "volume_ratio" in g.columns else np.nan

        row = {
            "event_id": event_id,
            "symbol": fix_tw_etf_symbol(entry_row["symbol"]),
            "entry_day": entry_day,
            "exit_day": exit_day,
            "holding_days": exit_day - entry_day,
            "entry_date": entry_row["date"],
            "exit_date": exit_row["date"],
            "ex_date": entry_row["event_ex_date"] if "event_ex_date" in g.columns else entry_row.get("ex_date", pd.NaT),
            "entry_price": entry_price,
            "exit_price": exit_price,
            "raw_return": raw_return,
            "net_return": net_return,
            "daily_net_return": net_return / (exit_day - entry_day),
            "entry_premium": entry_premium,
            "exit_premium": exit_premium,
            "premium_change_entry_to_exit": (
                exit_premium - entry_premium
                if pd.notna(entry_premium) and pd.notna(exit_premium)
                else np.nan
            ),
            "entry_volume_ratio": entry_volume_ratio,
            "dividend": dividend,
            "dividend_yield_on_entry": dividend_yield_on_entry,
        }

        for c in ["etf_name", "fund_name", "name"]:
            if c in g.columns:
                row["etf_name"] = entry_row[c]
                break

        rows.append(row)

    trades = pd.DataFrame(rows)

    if trades.empty:
        return trades

    for col in ["entry_date", "exit_date", "ex_date"]:
        trades[col] = pd.to_datetime(trades[col], errors="coerce")

    trades["entry_year"] = trades["entry_date"].dt.year

    return trades


def build_ex_dividend_strategy_trades(
    event_data: pd.DataFrame,
    symbols: list[str],
    entry_day: int = -10,
    exit_day: int = -1,
    price_col: str = "adj_close",
    fee_rate: float = 0.0008,
    etf_category_map: dict | None = None,
):
    """
    Build ex-dividend pre-positioning strategy trades.
    """

    symbols = [fix_tw_etf_symbol(s) for s in symbols]

    trades = calculate_event_trade_return_enriched(
        event_data=event_data,
        price_col=price_col,
        entry_day=entry_day,
        exit_day=exit_day,
        fee_rate=fee_rate,
    )

    if trades.empty:
        return trades

    trades = trades.copy()
    trades["symbol"] = trades["symbol"].apply(fix_tw_etf_symbol)
    trades = trades[trades["symbol"].isin(symbols)].copy()

    if trades.empty:
        return trades

    trades["strategy_entry_day"] = entry_day
    trades["strategy_exit_day"] = exit_day
    trades["strategy_holding_days"] = exit_day - entry_day

    trades["entry_date"] = pd.to_datetime(trades["entry_date"], errors="coerce")
    trades["exit_date"] = pd.to_datetime(trades["exit_date"], errors="coerce")
    trades["ex_date"] = pd.to_datetime(trades["ex_date"], errors="coerce")

    trades["entry_year"] = trades["entry_date"].dt.year
    trades["exit_year"] = trades["exit_date"].dt.year

    if etf_category_map is not None:
        trades["category"] = trades["symbol"].map(etf_category_map).fillna("others")
    else:
        trades["category"] = "unknown"

    trades = trades.sort_values(["entry_date", "symbol", "ex_date"]).reset_index(drop=True)

    return trades


def summarize_strategy_trades(
    trades: pd.DataFrame,
    return_col: str = "net_return",
):
    """
    Summarize trade-level performance.
    """

    if trades.empty:
        return pd.Series({
            "trade_count": 0,
            "symbol_count": 0,
            "avg_return": np.nan,
            "median_return": np.nan,
            "win_rate": np.nan,
            "std_return": np.nan,
            "min_return": np.nan,
            "max_return": np.nan,
            "profit_factor": np.nan,
            "avg_holding_days": np.nan,
            "start_date": pd.NaT,
            "end_date": pd.NaT,
        })

    r = trades[return_col].dropna()

    wins = r[r > 0]
    losses = r[r <= 0]

    gross_profit = wins.sum()
    gross_loss = losses.sum()

    profit_factor = gross_profit / abs(gross_loss) if gross_loss < 0 else np.nan

    return pd.Series({
        "trade_count": len(r),
        "symbol_count": trades["symbol"].nunique(),
        "avg_return": r.mean(),
        "median_return": r.median(),
        "win_rate": (r > 0).mean(),
        "std_return": r.std(),
        "min_return": r.min(),
        "max_return": r.max(),
        "profit_factor": profit_factor,
        "avg_holding_days": trades["holding_days"].mean() if "holding_days" in trades.columns else np.nan,
        "start_date": trades["entry_date"].min(),
        "end_date": trades["exit_date"].max(),
    })


def build_event_basket_returns(
    trades: pd.DataFrame,
    return_col: str = "net_return",
):
    """
    Convert trades into event-basket returns.

    If multiple trades share the same entry and exit date,
    they are treated as one equal-weight basket.
    """

    if trades.empty:
        return pd.DataFrame()

    basket = (
        trades
        .groupby(["entry_date", "exit_date"], as_index=False)
        .agg(
            basket_return=(return_col, "mean"),
            trade_count=("event_id", "count"),
            symbol_count=("symbol", "nunique"),
            symbols=("symbol", lambda x: ",".join(sorted(x.unique()))),
        )
        .sort_values(["exit_date", "entry_date"])
        .reset_index(drop=True)
    )

    basket["equity_curve"] = (1 + basket["basket_return"]).cumprod()
    basket["cum_return"] = basket["equity_curve"] - 1
    basket["running_max"] = basket["equity_curve"].cummax()
    basket["drawdown"] = basket["equity_curve"] / basket["running_max"] - 1

    return basket


def summarize_basket_strategy(
    basket: pd.DataFrame,
):
    """
    Summarize basket-level strategy performance.
    """

    if basket.empty:
        return pd.Series({
            "basket_count": 0,
            "total_return": np.nan,
            "avg_basket_return": np.nan,
            "median_basket_return": np.nan,
            "basket_win_rate": np.nan,
            "max_drawdown": np.nan,
            "profit_factor": np.nan,
            "start_date": pd.NaT,
            "end_date": pd.NaT,
        })

    r = basket["basket_return"].dropna()

    wins = r[r > 0]
    losses = r[r <= 0]

    gross_profit = wins.sum()
    gross_loss = losses.sum()

    profit_factor = gross_profit / abs(gross_loss) if gross_loss < 0 else np.nan

    return pd.Series({
        "basket_count": len(basket),
        "total_return": basket["equity_curve"].iloc[-1] - 1,
        "avg_basket_return": r.mean(),
        "median_basket_return": r.median(),
        "basket_win_rate": (r > 0).mean(),
        "max_drawdown": basket["drawdown"].min(),
        "profit_factor": profit_factor,
        "avg_trades_per_basket": basket["trade_count"].mean(),
        "start_date": basket["entry_date"].min(),
        "end_date": basket["exit_date"].max(),
    })


def summarize_strategy_by_year(
    trades: pd.DataFrame,
    return_col: str = "net_return",
):
    """
    Summarize trade-level performance by year.
    """

    if trades.empty:
        return pd.DataFrame()

    rows = []

    for year, g in trades.groupby("entry_year"):
        summary = summarize_strategy_trades(g, return_col=return_col)
        row = summary.to_dict()
        row["year"] = year
        rows.append(row)

    result = pd.DataFrame(rows)

    cols = ["year"] + [c for c in result.columns if c != "year"]
    result = result[cols].sort_values("year").reset_index(drop=True)

    return result


def summarize_strategy_by_symbol(
    trades: pd.DataFrame,
    return_col: str = "net_return",
):
    """
    Summarize trade-level performance by ETF symbol.
    """

    if trades.empty:
        return pd.DataFrame()

    rows = []

    for symbol, g in trades.groupby("symbol"):
        summary = summarize_strategy_trades(g, return_col=return_col)
        row = summary.to_dict()
        row["symbol"] = symbol

        if "etf_name" in g.columns and g["etf_name"].notna().any():
            row["etf_name"] = g["etf_name"].dropna().astype(str).iloc[0]

        if "category" in g.columns:
            row["category"] = g["category"].dropna().astype(str).iloc[0]

        rows.append(row)

    result = pd.DataFrame(rows)

    result = result.sort_values(
        ["avg_return", "win_rate", "trade_count"],
        ascending=[False, False, False],
    ).reset_index(drop=True)

    return result


def format_strategy_summary_for_display(df: pd.DataFrame):
    """
    Convert return columns into percentage points for display.
    """

    view = df.copy()

    pct_cols = [
        "avg_return",
        "median_return",
        "win_rate",
        "std_return",
        "min_return",
        "max_return",
        "total_return",
        "avg_basket_return",
        "median_basket_return",
        "basket_win_rate",
        "max_drawdown",
    ]

    for col in pct_cols:
        if col in view.columns:
            view[col] = view[col] * 100

    return view