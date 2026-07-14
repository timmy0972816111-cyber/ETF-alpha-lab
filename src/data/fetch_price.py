from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf
from tqdm import tqdm


RAW_PRICE_DIR = Path("data/raw/prices")


def normalize_symbol(x) -> str:
    """
    Preserve Taiwan ETF leading zeros.

    Examples
    --------
    50 -> 0050
    0050 -> 0050
    6208 -> 006208 only if already given as 006208 originally is safer.
    """

    if pd.isna(x):
        return ""

    x = str(x).strip()

    if x.endswith(".0"):
        x = x[:-2]

    if x.isdigit() and len(x) < 4:
        return x.zfill(4)

    return x


def to_yahoo_symbol(symbol: str) -> str:
    """
    Convert Taiwan stock / ETF symbol to Yahoo Finance format.

    0050 -> 0050.TW
    006208 -> 006208.TW
    """

    symbol = normalize_symbol(symbol)

    if symbol.endswith(".TW"):
        return symbol

    return f"{symbol}.TW"


def fetch_yahoo_price(
    symbol: str,
    start: str,
    end: str,
    auto_adjust: bool = False,
) -> pd.DataFrame:
    """
    Fetch daily price data from Yahoo Finance.

    Parameters
    ----------
    symbol:
        Taiwan ETF symbol, e.g. 0050, 006208.

    start:
        Start date, inclusive.
        Example: 2026-05-01

    end:
        End date, exclusive in yfinance.
        Example: if you want data through 2026-05-18,
        use end='2026-05-19'.

    auto_adjust:
        Whether yfinance adjusts OHLC automatically.

    Returns
    -------
    DataFrame with columns:
    date, symbol, open, high, low, close, adj_close, volume
    """

    symbol = normalize_symbol(symbol)
    yahoo_symbol = to_yahoo_symbol(symbol)

    df = yf.download(
        yahoo_symbol,
        start=start,
        end=end,
        auto_adjust=auto_adjust,
        progress=False,
    )

    if df.empty:
        print(f"[WARN] No price data found for {symbol}")
        return pd.DataFrame(
            columns=[
                "date",
                "symbol",
                "open",
                "high",
                "low",
                "close",
                "adj_close",
                "volume",
            ]
        )

    # yfinance sometimes returns MultiIndex columns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.reset_index()

    df.columns = [str(col).lower().replace(" ", "_") for col in df.columns]

    # yfinance date column may be "date" or "datetime"
    if "date" not in df.columns:
        if "datetime" in df.columns:
            df = df.rename(columns={"datetime": "date"})
        else:
            raise ValueError(f"Date column not found for {symbol}. Columns: {df.columns}")

    rename_map = {
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "adj_close": "adj_close",
        "volume": "volume",
    }

    df = df.rename(columns=rename_map)

    # If auto_adjust=True, yfinance may not return adj_close
    if "adj_close" not in df.columns:
        df["adj_close"] = df["close"]

    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["symbol"] = symbol

    keep_cols = [
        "date",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "adj_close",
        "volume",
    ]

    missing_cols = [col for col in keep_cols if col not in df.columns]

    if missing_cols:
        raise ValueError(f"{symbol} missing columns: {missing_cols}")

    df = df[keep_cols].copy()

    return df


def fetch_price_batch(
    symbols: list[str],
    start: str,
    end: str,
    output_dir: Path = RAW_PRICE_DIR,
    auto_adjust: bool = False,
    save: bool = True,
) -> pd.DataFrame:
    """
    Fetch price data for multiple ETFs.
    """

    output_dir.mkdir(parents=True, exist_ok=True)

    all_data = []

    for symbol in tqdm(symbols, desc="Fetching Yahoo prices"):
        symbol = normalize_symbol(symbol)

        try:
            df = fetch_yahoo_price(
                symbol=symbol,
                start=start,
                end=end,
                auto_adjust=auto_adjust,
            )

            if df.empty:
                continue

            if save:
                output_path = output_dir / f"{symbol}.csv"
                df.to_csv(
                    output_path,
                    index=False,
                    encoding="utf-8-sig",
                )

            all_data.append(df)

        except Exception as e:
            print(f"[WARN] Failed to fetch {symbol}: {e}")

    if len(all_data) == 0:
        return pd.DataFrame(
            columns=[
                "date",
                "symbol",
                "open",
                "high",
                "low",
                "close",
                "adj_close",
                "volume",
            ]
        )

    panel = pd.concat(all_data, ignore_index=True)

    panel["symbol"] = panel["symbol"].astype(str)

    panel = panel.drop_duplicates(
        subset=["date", "symbol"],
        keep="last",
    )

    panel = panel.sort_values(["symbol", "date"]).reset_index(drop=True)

    return panel


if __name__ == "__main__":
    symbols = [
        "0050",
        "0056",
        "00878",
        "00919",
        "006208",
        "0052",
        "00929",
        "00713",
        "00939",
        "00940",
    ]

    # 注意：
    # yfinance 的 end 是「不包含當天」
    # 如果你要抓到 2026-05-18，end 要設 2026-05-19
    price = fetch_price_batch(
        symbols=symbols,
        start="2016-01-01",
        end="2026-05-19",
        output_dir=RAW_PRICE_DIR,
        auto_adjust=False,
        save=True,
    )

    print(price.head())
    print(price.tail())
    print(price.shape)
    print(price["symbol"].unique())