from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PANEL_PATH = Path("data/processed/etf_daily_panel.csv")
OUTPUT_DIR = Path("data/processed/strategies")
OUTPUT_PATH = OUTPUT_DIR / "strategy_0050_006208_rv.csv"


def load_panel(path: Path = PANEL_PATH) -> pd.DataFrame:
    """
    Load ETF daily panel.
    """

    if not path.exists():
        raise FileNotFoundError(f"Panel file not found: {path}")

    panel = pd.read_csv(
        path,
        dtype={"symbol": str},
    )

    panel["date"] = pd.to_datetime(panel["date"])
    panel["symbol"] = panel["symbol"].astype(str)

    return panel


def prepare_pair_data(
    panel: pd.DataFrame,
    symbol_a: str = "0050",
    symbol_b: str = "006208",
    price_col: str = "adj_close",
) -> pd.DataFrame:
    """
    Prepare pair trading dataset.

    We use adj_close by default because ETF splits may distort close price.
    Missing rows are dropped at the strategy-data stage.
    """

    df = panel[panel["symbol"].isin([symbol_a, symbol_b])].copy()

    if df.empty:
        raise ValueError("No data found for selected symbols.")

    required_cols = [
        "date",
        "symbol",
        price_col,
        "close",
        "nav",
        "premium_discount",
        "volume",
    ]

    missing_cols = [col for col in required_cols if col not in df.columns]

    if missing_cols:
        raise ValueError(f"Panel missing columns: {missing_cols}")

    price = df.pivot(
        index="date",
        columns="symbol",
        values=price_col,
    )

    close = df.pivot(
        index="date",
        columns="symbol",
        values="close",
    )

    nav = df.pivot(
        index="date",
        columns="symbol",
        values="nav",
    )

    premium = df.pivot(
        index="date",
        columns="symbol",
        values="premium_discount",
    )

    volume = df.pivot(
        index="date",
        columns="symbol",
        values="volume",
    )

    for s in [symbol_a, symbol_b]:
        if s not in price.columns:
            raise ValueError(f"Missing {price_col} data for {s}")

        if s not in nav.columns:
            raise ValueError(f"Missing NAV data for {s}")

    data = pd.DataFrame(index=price.index)

    data[f"price_{symbol_a}"] = price[symbol_a]
    data[f"price_{symbol_b}"] = price[symbol_b]

    data[f"close_{symbol_a}"] = close[symbol_a]
    data[f"close_{symbol_b}"] = close[symbol_b]

    data[f"nav_{symbol_a}"] = nav[symbol_a]
    data[f"nav_{symbol_b}"] = nav[symbol_b]

    data[f"premium_{symbol_a}"] = premium[symbol_a]
    data[f"premium_{symbol_b}"] = premium[symbol_b]

    data[f"volume_{symbol_a}"] = volume[symbol_a]
    data[f"volume_{symbol_b}"] = volume[symbol_b]

    before_drop = len(data)

    data = data.dropna(
        subset=[
            f"price_{symbol_a}",
            f"price_{symbol_b}",
            f"nav_{symbol_a}",
            f"nav_{symbol_b}",
            f"premium_{symbol_a}",
            f"premium_{symbol_b}",
        ]
    ).copy()

    after_drop = len(data)

    print(f"[INFO] Pair data rows before dropna: {before_drop}")
    print(f"[INFO] Pair data rows after dropna: {after_drop}")
    print(f"[INFO] Dropped rows: {before_drop - after_drop}")

    if data.empty:
        raise ValueError("Pair data is empty after dropping NA rows.")

    return data


def estimate_rolling_beta(
    data: pd.DataFrame,
    symbol_a: str = "0050",
    symbol_b: str = "006208",
    beta_window: int = 60,
) -> pd.Series:
    """
    Estimate rolling beta of symbol_a on symbol_b.

    beta = rolling_cov(ret_a, ret_b) / rolling_var(ret_b)
    """

    log_a = np.log(data[f"price_{symbol_a}"])
    log_b = np.log(data[f"price_{symbol_b}"])

    ret_a = log_a.diff()
    ret_b = log_b.diff()

    rolling_cov = ret_a.rolling(beta_window).cov(ret_b)
    rolling_var = ret_b.rolling(beta_window).var()

    beta = rolling_cov / rolling_var

    return beta


def add_spread_and_signal(
    data: pd.DataFrame,
    symbol_a: str = "0050",
    symbol_b: str = "006208",
    beta_window: int = 60,
    z_window: int = 20,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    allow_beta_fill: bool = False,
) -> pd.DataFrame:
    """
    Add NAV-adjusted spread, z-score, and trading signal.

    signal:
      1  = long symbol_a, short symbol_b
     -1  = short symbol_a, long symbol_b
      0  = flat
    """

    df = data.copy()

    log_price_a = np.log(df[f"price_{symbol_a}"])
    log_price_b = np.log(df[f"price_{symbol_b}"])

    log_nav_a = np.log(df[f"nav_{symbol_a}"])
    log_nav_b = np.log(df[f"nav_{symbol_b}"])

    df["beta"] = estimate_rolling_beta(
        data=df,
        symbol_a=symbol_a,
        symbol_b=symbol_b,
        beta_window=beta_window,
    )

    if allow_beta_fill:
        df["beta"] = df["beta"].fillna(1.0)

    df["price_spread"] = log_price_a - df["beta"] * log_price_b
    df["nav_spread"] = log_nav_a - df["beta"] * log_nav_b

    # ETF trader version:
    # remove NAV-relative movement, only keep market-price relative mispricing.
    df["mispricing_spread"] = df["price_spread"] - df["nav_spread"]

    # Direct premium spread, used as an intuitive reference.
    df["premium_spread"] = df[f"premium_{symbol_a}"] - df[f"premium_{symbol_b}"]

    df["spread_mean"] = df["mispricing_spread"].rolling(z_window).mean()
    df["spread_std"] = df["mispricing_spread"].rolling(z_window).std()

    df["z_score"] = (
        df["mispricing_spread"] - df["spread_mean"]
    ) / df["spread_std"]

    signals = []
    current_pos = 0

    for z in df["z_score"]:
        if pd.isna(z):
            signals.append(0)
            continue

        if current_pos == 0:
            if z > entry_z:
                # 0050 relatively expensive vs NAV-adjusted 006208
                # short A, long B
                current_pos = -1

            elif z < -entry_z:
                # 0050 relatively cheap vs NAV-adjusted 006208
                # long A, short B
                current_pos = 1

        else:
            if abs(z) < exit_z:
                current_pos = 0

        signals.append(current_pos)

    df["signal"] = signals

    return df


def add_strategy_returns(
    data: pd.DataFrame,
    symbol_a: str = "0050",
    symbol_b: str = "006208",
    fee_rate: float = 0.0008,
) -> pd.DataFrame:
    """
    Calculate long-short strategy returns.

    Assumptions:
    - Signal is generated after close.
    - Position is applied from next day.
    - Dollar neutral:
        50% long side
        50% short side
    """

    df = data.copy()

    df[f"ret_{symbol_a}"] = df[f"price_{symbol_a}"].pct_change()
    df[f"ret_{symbol_b}"] = df[f"price_{symbol_b}"].pct_change()

    # Avoid look-ahead bias.
    df["position"] = df["signal"].shift(1).fillna(0)

    # position = 1: long A, short B
    # position = -1: short A, long B
    df["gross_ret"] = (
        df["position"]
        * 0.5
        * (df[f"ret_{symbol_a}"] - df[f"ret_{symbol_b}"])
    )

    df["turnover"] = df["position"].diff().abs().fillna(0)

    df["cost"] = df["turnover"] * fee_rate

    df["strategy_ret"] = df["gross_ret"] - df["cost"]

    df["equity"] = (1 + df["strategy_ret"].fillna(0)).cumprod()

    df["peak"] = df["equity"].cummax()
    df["drawdown"] = df["equity"] / df["peak"] - 1

    return df


def calculate_metrics(df: pd.DataFrame) -> dict:
    """
    Calculate basic performance metrics.
    """

    ret = df["strategy_ret"].dropna()
    equity = df["equity"].dropna()

    if ret.empty or equity.empty:
        return {}

    total_return = equity.iloc[-1] - 1

    annual_return = equity.iloc[-1] ** (252 / len(df)) - 1

    annual_vol = ret.std() * np.sqrt(252)

    sharpe = annual_return / annual_vol if annual_vol != 0 else np.nan

    max_drawdown = df["drawdown"].min()

    trade_count = int((df["position"].diff().abs() > 0).sum())

    exposure_ratio = (df["position"] != 0).mean()

    active_ret = df.loc[df["position"] != 0, "strategy_ret"].dropna()

    if len(active_ret) > 0:
        win_rate_active_days = (active_ret > 0).mean()
        avg_active_daily_return = active_ret.mean()
    else:
        win_rate_active_days = np.nan
        avg_active_daily_return = np.nan

    return {
        "total_return": total_return,
        "annual_return": annual_return,
        "annual_vol": annual_vol,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "trade_count": trade_count,
        "exposure_ratio": exposure_ratio,
        "win_rate_active_days": win_rate_active_days,
        "avg_active_daily_return": avg_active_daily_return,
    }


def print_metrics(metrics: dict) -> None:
    """
    Print metrics in a readable format.
    """

    print("\n========== Strategy Metrics ==========")

    if not metrics:
        print("No metrics available.")
        return

    for key, value in metrics.items():
        if isinstance(value, float):
            print(f"{key}: {value:.6f}")
        else:
            print(f"{key}: {value}")


def plot_results(df: pd.DataFrame) -> None:
    """
    Plot equity, drawdown, and z-score.
    """

    plt.figure(figsize=(12, 5))
    plt.plot(df.index, df["equity"])
    plt.title("0050 vs 006208 NAV-adjusted RV Strategy - Equity")
    plt.xlabel("Date")
    plt.ylabel("Equity")
    plt.grid(True)
    plt.show()

    plt.figure(figsize=(12, 5))
    plt.plot(df.index, df["drawdown"])
    plt.title("Drawdown")
    plt.xlabel("Date")
    plt.ylabel("Drawdown")
    plt.grid(True)
    plt.show()

    plt.figure(figsize=(12, 5))
    plt.plot(df.index, df["z_score"])
    plt.axhline(2.0, linestyle="--")
    plt.axhline(-2.0, linestyle="--")
    plt.axhline(0.5, linestyle=":")
    plt.axhline(-0.5, linestyle=":")
    plt.title("Mispricing Spread Z-Score")
    plt.xlabel("Date")
    plt.ylabel("Z-Score")
    plt.grid(True)
    plt.show()


def main():
    symbol_a = "0050"
    symbol_b = "006208"

    # Parameters
    price_col = "adj_close"
    beta_window = 60
    z_window = 20
    entry_z = 2.0
    exit_z = 0.5
    fee_rate = 0.0008

    panel = load_panel(PANEL_PATH)

    data = prepare_pair_data(
        panel=panel,
        symbol_a=symbol_a,
        symbol_b=symbol_b,
        price_col=price_col,
    )

    data = add_spread_and_signal(
        data=data,
        symbol_a=symbol_a,
        symbol_b=symbol_b,
        beta_window=beta_window,
        z_window=z_window,
        entry_z=entry_z,
        exit_z=exit_z,
        allow_beta_fill=False,
    )

    data = add_strategy_returns(
        data=data,
        symbol_a=symbol_a,
        symbol_b=symbol_b,
        fee_rate=fee_rate,
    )

    metrics = calculate_metrics(data)

    print_metrics(metrics)

    print("\n========== Latest Rows ==========")
    print(
        data[
            [
                f"price_{symbol_a}",
                f"price_{symbol_b}",
                f"close_{symbol_a}",
                f"close_{symbol_b}",
                f"nav_{symbol_a}",
                f"nav_{symbol_b}",
                f"premium_{symbol_a}",
                f"premium_{symbol_b}",
                "beta",
                "price_spread",
                "nav_spread",
                "mispricing_spread",
                "premium_spread",
                "z_score",
                "signal",
                "position",
                "gross_ret",
                "cost",
                "strategy_ret",
                "equity",
                "drawdown",
            ]
        ].tail(30)
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    data.to_csv(
        OUTPUT_PATH,
        index=True,
        encoding="utf-8-sig",
    )

    print(f"\nSaved strategy result to: {OUTPUT_PATH}")

    plot_results(data)


if __name__ == "__main__":
    main()