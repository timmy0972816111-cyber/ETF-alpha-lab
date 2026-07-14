from pathlib import Path
from typing import Optional

import pandas as pd


PRICE_DIR = Path("data/raw/prices")
NAV_PATH = Path("data/processed/etf_nav_panel.csv")
OUTPUT_PATH = Path("data/processed/etf_daily_panel.csv")


def build_symbol_map(symbols: Optional[list[str]] = None) -> dict:
    """
    Build symbol recovery map from target symbols.

    Examples
    --------
    symbols = ["0050", "0056", "006208", "00919"]

    map:
    "50"   -> "0050"
    "56"   -> "0056"
    "6208" -> "006208"
    "919"  -> "00919"

    This solves the issue where pandas / Excel may drop leading zeros.
    """

    if symbols is None:
        return {}

    symbol_map = {}

    for symbol in symbols:
        symbol = str(symbol).strip()

        if symbol == "":
            continue

        key = symbol.lstrip("0")

        symbol_map[key] = symbol

    return symbol_map


def normalize_symbol(
    x,
    symbol_map: Optional[dict] = None,
) -> str:
    """
    Normalize ETF symbol and preserve leading zeros.

    Handles:
    - 50      -> 0050
    - 56      -> 0056
    - 6208    -> 006208
    - 919     -> 00919
    - 0050    -> 0050
    - 006208  -> 006208
    - 50.0    -> 0050

    The best recovery comes from symbol_map.
    """

    if pd.isna(x):
        return ""

    x = str(x).strip()

    # Remove Excel-style wrapper: ="0050"
    if x.startswith('="') and x.endswith('"'):
        x = x[2:-1]

    # Remove float artifact: 50.0 -> 50
    if x.endswith(".0"):
        x = x[:-2]

    if symbol_map is not None and x.isdigit():
        key = x.lstrip("0")

        if key in symbol_map:
            return symbol_map[key]

    # Conservative fallback for 4-digit ETFs only.
    # Note: 6208 cannot be recovered to 006208 without symbol_map.
    if x.isdigit() and len(x) < 4:
        return x.zfill(4)

    return x


def load_price_file(
    file_path: Path,
    symbol_map: Optional[dict] = None,
) -> pd.DataFrame:
    """
    Load one ETF price CSV.

    Expected columns:
    date, symbol, open, high, low, close, adj_close, volume

    If symbol column is missing, use file name as symbol.
    """

    df = pd.read_csv(
        file_path,
        dtype={"symbol": str},
    )

    df.columns = [col.lower().strip() for col in df.columns]

    if "date" not in df.columns:
        raise ValueError(f"{file_path} missing date column")

    df["date"] = pd.to_datetime(df["date"])

    # If price csv has no symbol column, infer from filename.
    if "symbol" not in df.columns:
        df["symbol"] = file_path.stem

    df["symbol"] = df["symbol"].map(
        lambda x: normalize_symbol(x, symbol_map=symbol_map)
    )

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
        raise ValueError(f"{file_path} missing columns: {missing_cols}")

    df = df[keep_cols].copy()

    return df


def load_all_prices(
    price_dir: Path = PRICE_DIR,
    symbols: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Load all ETF price CSV files under data/raw/prices.
    """

    files = sorted(price_dir.glob("*.csv"))

    if len(files) == 0:
        raise FileNotFoundError(f"No price csv files found in {price_dir}")

    symbol_map = build_symbol_map(symbols)
    target_symbols = list(symbol_map.values()) if symbols is not None else None

    all_data = []

    for file_path in files:
        df = load_price_file(
            file_path=file_path,
            symbol_map=symbol_map,
        )

        if target_symbols is not None:
            df = df[df["symbol"].isin(target_symbols)].copy()

        if not df.empty:
            all_data.append(df)

    if len(all_data) == 0:
        return pd.DataFrame()

    price = pd.concat(all_data, ignore_index=True)

    price["symbol"] = price["symbol"].map(
        lambda x: normalize_symbol(x, symbol_map=symbol_map)
    )

    price = price.drop_duplicates(
        subset=["date", "symbol"],
        keep="last",
    )

    price = price.sort_values(["symbol", "date"]).reset_index(drop=True)

    return price


def load_nav(
    nav_path: Path = NAV_PATH,
    symbols: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Load ETF NAV panel.

    Expected columns:
    date, symbol, nav, prev_nav, nav_change, nav_change_pct,
    market_price, premium_discount
    """

    if not nav_path.exists():
        raise FileNotFoundError(f"NAV file not found: {nav_path}")

    symbol_map = build_symbol_map(symbols)

    nav = pd.read_csv(
        nav_path,
        dtype={"symbol": str},
    )

    nav.columns = [col.lower().strip() for col in nav.columns]

    if "date" not in nav.columns:
        raise ValueError(f"NAV file missing date column: {nav_path}")

    if "symbol" not in nav.columns:
        raise ValueError(f"NAV file missing symbol column: {nav_path}")

    nav["date"] = pd.to_datetime(nav["date"])

    nav["symbol"] = nav["symbol"].map(
        lambda x: normalize_symbol(x, symbol_map=symbol_map)
    )

    keep_cols = [
        "date",
        "symbol",
        "nav",
        "prev_nav",
        "nav_change",
        "nav_change_pct",
        "market_price",
        "premium_discount",
    ]

    missing_cols = [col for col in keep_cols if col not in nav.columns]

    if missing_cols:
        raise ValueError(f"NAV file missing columns: {missing_cols}")

    nav = nav[keep_cols].copy()

    nav = nav.drop_duplicates(
        subset=["date", "symbol"],
        keep="last",
    )

    return nav


def build_etf_daily_panel(
    price_dir: Path = PRICE_DIR,
    nav_path: Path = NAV_PATH,
    output_path: Path = OUTPUT_PATH,
    symbols: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Merge ETF price data and NAV data.

    Inputs
    ------
    data/raw/prices/*.csv
    data/processed/etf_nav_panel.csv

    Output
    ------
    data/processed/etf_daily_panel.csv
    """

    symbol_map = build_symbol_map(symbols)
    target_symbols = list(symbol_map.values()) if symbols is not None else None

    price = load_all_prices(
        price_dir=price_dir,
        symbols=symbols,
    )

    if price.empty:
        raise ValueError("Price data is empty after loading/filtering.")

    nav = load_nav(
        nav_path=nav_path,
        symbols=symbols,
    )

    if nav.empty:
        raise ValueError("NAV data is empty after loading/filtering.")

    if target_symbols is not None:
        price = price[price["symbol"].isin(target_symbols)].copy()
        nav = nav[nav["symbol"].isin(target_symbols)].copy()

    panel = pd.merge(
        price,
        nav,
        on=["date", "symbol"],
        how="left",
    )

    panel["symbol"] = panel["symbol"].map(
        lambda x: normalize_symbol(x, symbol_map=symbol_map)
    )

    # Derived fields
    panel["close_to_nav"] = panel["close"] / panel["nav"] - 1
    panel["market_price_to_nav"] = panel["market_price"] / panel["nav"] - 1

    # Returns
    panel = panel.sort_values(["symbol", "date"]).reset_index(drop=True)

    panel["close_ret"] = panel.groupby("symbol")["close"].pct_change()
    panel["nav_ret"] = panel.groupby("symbol")["nav"].pct_change()
    panel["price_nav_ret_spread"] = panel["close_ret"] - panel["nav_ret"]

    # Final safety check
    panel["symbol"] = panel["symbol"].astype(str)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    panel.to_csv(
        output_path,
        index=False,
        encoding="utf-8-sig",
    )

    return panel


if __name__ == "__main__":
    # 範例：台灣大型股票型 ETF
    # 條件：
    # 1. 排除槓桿 / 反向 ETF
    # 2. 排除債券 ETF
    # 3. 排除代號含英文字母 ETF
    symbols = [
        "0050",    # 元大台灣50
        "0056",    # 元大高股息
        "00878",   # 國泰永續高股息
        "00919",   # 群益台灣精選高息
        "006208",  # 富邦台50
        "0052",    # 富邦科技
        "00929",   # 復華台灣科技優息
        "00713",   # 元大台灣高息低波
        "00939",   # 統一台灣高息動能
        "00940",   # 元大台灣價值高息
    ]

    panel = build_etf_daily_panel(
        price_dir=PRICE_DIR,
        nav_path=NAV_PATH,
        output_path=OUTPUT_PATH,
        symbols=symbols,
    )

    print(panel.head())
    print(panel.tail())
    print(panel.shape)

    print("\nSymbols:")
    print(panel["symbol"].unique())

    print("\nLatest rows:")
    print(
        panel[
            [
                "date",
                "symbol",
                "close",
                "nav",
                "market_price",
                "premium_discount",
                "close_to_nav",
            ]
        ].tail(30)
    )