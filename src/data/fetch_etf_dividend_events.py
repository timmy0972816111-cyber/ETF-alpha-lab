# src/data/fetch_etf_dividend_events.py

from __future__ import annotations

import io
import re
import time
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup


# ============================================================
# Config
# ============================================================

TWSE_DIVIDEND_LIST_URL = "https://www.twse.com.tw/zh/ETFortune/dividendList"

# 研究用 ETF universe
# 之後要擴充全 ETF，只要改這裡即可
DEFAULT_SYMBOLS = [
    "0050",
    "0052",
    "0056",
    "006208",
    "00713",
    "00878",
    "00919",
    "00929",
    "00939",
    "00940",
]

# 已知 ETF 名稱，用於補缺值與修正被 fallback parser 污染的名稱
# 注意：這裡不是過濾清單，不會因為名稱不在這裡就刪掉
DEFAULT_NAME_MAP = {
    "0050": "元大台灣50",
    "0052": "富邦科技",
    "0056": "元大高股息",
    "006208": "富邦台50",
    "00713": "元大台灣高息低波",
    "00878": "國泰永續高股息",
    "00919": "群益台灣精選高息",
    "00929": "復華台灣科技優息",
    "00939": "統一台灣高息動能",
    "00940": "元大台灣價值高息",
}

DEFAULT_START_YEAR = 2016
DEFAULT_END_YEAR = 2026

RAW_OUTPUT_PATH = Path("data/raw/events/etf_dividend_events_raw.csv")
PROCESSED_OUTPUT_PATH = Path("data/processed/etf_dividend_events.csv")

REQUEST_SLEEP_SECONDS = 1.0
REQUEST_TIMEOUT = 20
MAX_RETRIES = 3


# ============================================================
# Utility functions
# ============================================================

def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def normalize_symbol(symbol: object) -> str:
    """
    Normalize ETF symbol and preserve leading zeros.

    Examples:
    - 50 -> 0050
    - 56 -> 0056
    - 713 -> 0713 by pure zfill, but later symbol_alias_map can fix to 00713
    - 006208 -> 006208
    """
    if symbol is None or pd.isna(symbol):
        return ""

    s = str(symbol).strip()

    # 清掉可能的 .0，例如 Excel / pandas 把 0050 讀成 50.0
    if re.fullmatch(r"\d+\.0", s):
        s = s.split(".")[0]

    # 只針對純數字做前導零處理
    # 台灣 ETF 可能是 4 碼或 6 碼，例如 0050 / 006208
    if s.isdigit() and len(s) < 4:
        s = s.zfill(4)

    return s


def parse_roc_date(value: object) -> Optional[pd.Timestamp]:
    """
    Parse Taiwan ROC date formats.

    Supported examples:
    - 115年03月20日
    - 114/03/20
    - 2025-03-20
    - 2025/03/20
    """
    if value is None or pd.isna(value):
        return pd.NaT

    s = str(value).strip()

    if s in ["", "-", "nan", "NaN", "None"]:
        return pd.NaT

    s = re.sub(r"\s+", "", s)

    # ROC format: 115年03月20日
    m = re.match(r"^(\d{2,4})年(\d{1,2})月(\d{1,2})日$", s)
    if m:
        year_raw = int(m.group(1))
        month = int(m.group(2))
        day = int(m.group(3))

        year = year_raw + 1911 if year_raw < 1911 else year_raw

        try:
            return pd.Timestamp(year=year, month=month, day=day)
        except Exception:
            return pd.NaT

    # ROC slash or Gregorian slash: 115/03/20 or 2025/03/20
    m = re.match(r"^(\d{2,4})/(\d{1,2})/(\d{1,2})$", s)
    if m:
        year_raw = int(m.group(1))
        month = int(m.group(2))
        day = int(m.group(3))

        year = year_raw + 1911 if year_raw < 1911 else year_raw

        try:
            return pd.Timestamp(year=year, month=month, day=day)
        except Exception:
            return pd.NaT

    try:
        return pd.to_datetime(s, errors="coerce")
    except Exception:
        return pd.NaT


def safe_float(value: object) -> float:
    if value is None or pd.isna(value):
        return float("nan")

    s = str(value).strip().replace(",", "")

    if s in ["", "-", "nan", "NaN", "None"]:
        return float("nan")

    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
    if not m:
        return float("nan")

    try:
        return float(m.group(0))
    except Exception:
        return float("nan")


def flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flatten MultiIndex columns and clean column names.
    """
    df = df.copy()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            "_".join([str(x) for x in col if str(x) != "nan"]).strip()
            for col in df.columns
        ]
    else:
        df.columns = [str(c).strip() for c in df.columns]

    df.columns = [
        re.sub(r"\s+", "", str(c).replace("\n", "").replace("\r", ""))
        for c in df.columns
    ]

    return df


def find_column(columns: Iterable[str], candidates: list[str]) -> Optional[str]:
    """
    Find first column that contains any candidate keyword.
    """
    columns = list(columns)

    for keyword in candidates:
        for col in columns:
            if keyword in col:
                return col

    return None


def normalize_target_symbols(symbols: list[str]) -> list[str]:
    """
    Normalize target symbols and handle known 5-digit / 6-digit ETF codes.
    """
    out = []

    for s in symbols:
        symbol = normalize_symbol(s)

        # 常見被截斷或錯讀的高股息 ETF
        alias_map = {
            "713": "00713",
            "0713": "00713",
            "878": "00878",
            "0878": "00878",
            "919": "00919",
            "0919": "00919",
            "929": "00929",
            "0929": "00929",
            "939": "00939",
            "0939": "00939",
            "940": "00940",
            "0940": "00940",
            "6208": "006208",
        }

        symbol = alias_map.get(symbol, symbol)
        out.append(symbol)

    return sorted(set(out))


def sanitize_etf_name(symbol: str, etf_name: object, name_map: dict[str, str]) -> str:
    """
    Fix ETF name if parser creates polluted name.

    Important:
    - Do not drop rows only because ETF name differs.
    - If known expected name exists, use it to fill missing or obviously polluted names.
    """
    symbol = normalize_symbol(symbol)
    raw_name = "" if etf_name is None or pd.isna(etf_name) else str(etf_name).strip()

    if raw_name.lower() in ["", "nan", "none"]:
        raw_name = ""

    expected_name = name_map.get(symbol)

    if expected_name is None:
        return raw_name

    # 如果名稱空白，直接補標準名
    if raw_name == "":
        return expected_name

    # 如果名稱中本來就含標準名，保留標準名
    if expected_name in raw_name:
        return expected_name

    # fallback parser 偶爾會把整段表格文字塞進名稱
    # 特徵：名稱過長、含多個 ETF 代號、含民國日期、含網址或大量數字
    suspicious = (
        len(raw_name) > 30
        or bool(re.search(r"\d{2,3}年\d{1,2}月\d{1,2}日", raw_name))
        or bool(re.search(r"\b00\d{2,4}\b", raw_name))
        or "http" in raw_name.lower()
        or "TWSE" in raw_name
    )

    if suspicious:
        return expected_name

    # 名稱不同但不明顯污染：不要刪資料，保守用 expected name
    return expected_name


# ============================================================
# Fetch TWSE ETF dividend list
# ============================================================

def fetch_twse_dividend_html(
    year: int,
    symbol: Optional[str] = None,
    session: Optional[requests.Session] = None,
) -> tuple[str, str]:
    """
    Fetch TWSE ETF eFortune dividend list page.
    """
    if session is None:
        session = requests.Session()

    params = {
        "startDate": str(year),
        "endDate": str(year),
    }

    if symbol is not None:
        params["stkNo"] = normalize_symbol(symbol)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(
                TWSE_DIVIDEND_LIST_URL,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.text, resp.url

        except Exception as e:
            last_error = e
            print(
                f"[WARN] TWSE request failed "
                f"year={year}, symbol={symbol}, attempt={attempt}: {e}"
            )
            time.sleep(REQUEST_SLEEP_SECONDS * attempt)

    raise RuntimeError(
        f"TWSE request failed after retries. "
        f"year={year}, symbol={symbol}, error={last_error}"
    )


# ============================================================
# Parse TWSE dividend data
# ============================================================

def parse_twse_tables(
    html: str,
    source_url: str,
    target_symbols: Optional[set[str]] = None,
) -> pd.DataFrame:
    """
    Try parsing TWSE dividend data using pandas.read_html.
    """
    rows = []

    try:
        tables = pd.read_html(io.StringIO(html))
    except Exception:
        return pd.DataFrame()

    for table in tables:
        table = flatten_columns(table)

        if table.empty:
            continue

        symbol_col = find_column(
            table.columns,
            ["證券代號", "股票代號", "ETF代號", "代號", "證券代碼"],
        )

        name_col = find_column(
            table.columns,
            ["證券名稱", "股票名稱", "ETF名稱", "名稱"],
        )

        ex_col = find_column(
            table.columns,
            ["除息交易日", "除息日"],
        )

        record_col = find_column(
            table.columns,
            ["收益分配基準日", "分配基準日", "基準日"],
        )

        pay_col = find_column(
            table.columns,
            ["收益分配發放日", "現金股利發放日", "發放日"],
        )

        dividend_col = find_column(
            table.columns,
            ["收益分配金額", "每1受益權益單位", "現金股利", "股利合計", "配息"],
        )

        required = [symbol_col, ex_col, pay_col, dividend_col]

        if any(col is None for col in required):
            continue

        for _, r in table.iterrows():
            symbol = normalize_symbol(r.get(symbol_col))

            if target_symbols is not None and symbol not in target_symbols:
                continue

            ex_date = parse_roc_date(r.get(ex_col))
            pay_date = parse_roc_date(r.get(pay_col))
            record_date = parse_roc_date(r.get(record_col)) if record_col else pd.NaT
            dividend = safe_float(r.get(dividend_col))

            if pd.isna(ex_date) or pd.isna(pay_date):
                continue

            row = {
                "symbol": symbol,
                "etf_name": str(r.get(name_col, "")).strip() if name_col else "",
                "ex_date": ex_date,
                "record_date": record_date,
                "pay_date": pay_date,
                "dividend": dividend,
                "source": "TWSE ETF eFortune dividendList table",
                "source_url": source_url,
                "scraped_at": pd.Timestamp.now(),
                "parser": "table",
            }

            rows.append(row)

    return pd.DataFrame(rows)


def parse_twse_text_fallback(
    html: str,
    source_url: str,
    target_symbols: Optional[set[str]] = None,
) -> pd.DataFrame:
    """
    Fallback parser.

    TWSE dividendList page sometimes appears as server-rendered HTML text.

    This parser extracts rows like:
    115 00929 復華台灣科技優息 115年03月18日 115年03月24日 115年04月15日 0.11
    """
    soup = BeautifulSoup(html, "html.parser")

    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)

    # 修正：原本只支援 4~5 碼，這裡改為 4~6 碼，才能支援 006208
    pattern = re.compile(
        r"(?P<year_label>\d{2,4})\s+"
        r"(?P<symbol>\d{4,6}[A-Z]?)\s+"
        r"(?P<name>.+?)\s+"
        r"(?P<ex_date>\d{2,4}年\d{1,2}月\d{1,2}日)\s+"
        r"(?P<record_date>\d{2,4}年\d{1,2}月\d{1,2}日)\s+"
        r"(?P<pay_date>\d{2,4}年\d{1,2}月\d{1,2}日)\s+"
        r"(?P<dividend>\d+(?:\.\d+)?)"
    )

    rows = []

    for m in pattern.finditer(text):
        symbol = normalize_symbol(m.group("symbol"))

        if target_symbols is not None and symbol not in target_symbols:
            continue

        ex_date = parse_roc_date(m.group("ex_date"))
        record_date = parse_roc_date(m.group("record_date"))
        pay_date = parse_roc_date(m.group("pay_date"))

        if pd.isna(ex_date) or pd.isna(pay_date):
            continue

        row = {
            "symbol": symbol,
            "etf_name": m.group("name").strip(),
            "ex_date": ex_date,
            "record_date": record_date,
            "pay_date": pay_date,
            "dividend": safe_float(m.group("dividend")),
            "source": "TWSE ETF eFortune dividendList text_fallback",
            "source_url": source_url,
            "scraped_at": pd.Timestamp.now(),
            "parser": "text_fallback",
        }

        rows.append(row)

    return pd.DataFrame(rows)


def parse_twse_dividend_html(
    html: str,
    source_url: str,
    target_symbols: Optional[set[str]] = None,
) -> pd.DataFrame:
    """
    Parse TWSE dividend data using table parser first,
    then fallback to text parser.

    If both parsers return the same event, table parser is preferred.
    """
    df_table = parse_twse_tables(
        html=html,
        source_url=source_url,
        target_symbols=target_symbols,
    )

    df_text = parse_twse_text_fallback(
        html=html,
        source_url=source_url,
        target_symbols=target_symbols,
    )

    frames = []

    if not df_table.empty:
        frames.append(df_table)

    if not df_text.empty:
        frames.append(df_text)

    if not frames:
        return pd.DataFrame(
            columns=[
                "symbol",
                "etf_name",
                "ex_date",
                "record_date",
                "pay_date",
                "dividend",
                "source",
                "source_url",
                "scraped_at",
                "parser",
            ]
        )

    out = pd.concat(frames, ignore_index=True)

    out["symbol"] = out["symbol"].map(normalize_symbol)
    out["ex_date"] = pd.to_datetime(out["ex_date"], errors="coerce")
    out["record_date"] = pd.to_datetime(out["record_date"], errors="coerce")
    out["pay_date"] = pd.to_datetime(out["pay_date"], errors="coerce")
    out["dividend"] = pd.to_numeric(out["dividend"], errors="coerce")

    # table parser 通常比 text fallback 乾淨
    out["parser_priority"] = out["parser"].map(
        {
            "table": 2,
            "text_fallback": 1,
        }
    ).fillna(0)

    out = out.sort_values(
        ["symbol", "ex_date", "pay_date", "dividend", "parser_priority"],
        ascending=[True, True, True, True, False],
    )

    out = out.drop_duplicates(
        subset=["symbol", "ex_date", "pay_date", "dividend"],
        keep="first",
    )

    out = out.drop(columns=["parser_priority"])

    return out.reset_index(drop=True)


# ============================================================
# Main crawler
# ============================================================

def fetch_etf_dividend_events(
    symbols: list[str],
    start_year: int,
    end_year: int,
    query_by_symbol: bool = False,
    sleep_seconds: float = REQUEST_SLEEP_SECONDS,
) -> pd.DataFrame:
    """
    Fetch ETF dividend events from TWSE ETF eFortune dividendList.

    Parameters
    ----------
    symbols:
        ETF symbols to fetch.
    start_year:
        Gregorian start year.
    end_year:
        Gregorian end year.
    query_by_symbol:
        If True, request each symbol-year separately.
        If False, request each year and filter symbols locally.
    sleep_seconds:
        Sleep between requests.

    Returns
    -------
    DataFrame with standardized dividend event data.
    """
    symbols = normalize_target_symbols(symbols)
    target_symbols = set(symbols)

    session = requests.Session()
    all_rows = []

    for year in range(start_year, end_year + 1):
        query_symbols = symbols if query_by_symbol else [None]

        for symbol in query_symbols:
            print(f"[INFO] Fetching TWSE dividend events: year={year}, symbol={symbol}")

            html, source_url = fetch_twse_dividend_html(
                year=year,
                symbol=symbol,
                session=session,
            )

            df_year = parse_twse_dividend_html(
                html=html,
                source_url=source_url,
                target_symbols=target_symbols,
            )

            if not df_year.empty:
                all_rows.append(df_year)

            time.sleep(sleep_seconds)

    if not all_rows:
        return pd.DataFrame(
            columns=[
                "symbol",
                "etf_name",
                "ex_date",
                "record_date",
                "pay_date",
                "dividend",
                "source",
                "source_url",
                "scraped_at",
                "parser",
            ]
        )

    out = pd.concat(all_rows, ignore_index=True)

    out["symbol"] = out["symbol"].map(normalize_symbol)
    out["ex_date"] = pd.to_datetime(out["ex_date"], errors="coerce")
    out["record_date"] = pd.to_datetime(out["record_date"], errors="coerce")
    out["pay_date"] = pd.to_datetime(out["pay_date"], errors="coerce")
    out["dividend"] = pd.to_numeric(out["dividend"], errors="coerce")

    out = out.dropna(subset=["symbol", "ex_date", "pay_date"])

    out = out.drop_duplicates(
        subset=["symbol", "ex_date", "pay_date", "dividend"],
        keep="first",
    )

    out = out.sort_values(["symbol", "ex_date", "pay_date"]).reset_index(drop=True)

    return out


def clean_dividend_events(
    df: pd.DataFrame,
    target_symbols: Optional[list[str]] = None,
    name_map: Optional[dict[str, str]] = None,
) -> pd.DataFrame:
    """
    Clean ETF dividend event data.

    Key fixes:
    1. target_symbols comes from DEFAULT_SYMBOLS, not from high-dividend-only name_map.
    2. ETF names are corrected instead of deleting rows aggressively.
    3. 0050 / 0052 / 006208 will not be removed.
    """
    df = df.copy()

    if name_map is None:
        name_map = DEFAULT_NAME_MAP.copy()

    if target_symbols is None:
        target_symbols = DEFAULT_SYMBOLS

    target_symbols = normalize_target_symbols(target_symbols)
    target_symbol_set = set(target_symbols)

    # --------------------------------------------------------
    # 0. Remove duplicated columns
    # --------------------------------------------------------
    if df.columns.duplicated().any():
        print("[WARN] Duplicated columns found:")
        print(df.columns[df.columns.duplicated()].tolist())
        df = df.loc[:, ~df.columns.duplicated()].copy()

    # --------------------------------------------------------
    # 1. Required columns
    # --------------------------------------------------------
    if "symbol" not in df.columns:
        raise ValueError("Missing required column: symbol")

    required_cols = ["ex_date", "pay_date", "dividend"]
    missing_cols = [col for col in required_cols if col not in df.columns]

    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    # --------------------------------------------------------
    # 2. Normalize symbol
    # --------------------------------------------------------
    symbol_alias_map = {
        "50": "0050",
        "52": "0052",
        "56": "0056",
        "713": "00713",
        "0713": "00713",
        "878": "00878",
        "0878": "00878",
        "919": "00919",
        "0919": "00919",
        "929": "00929",
        "0929": "00929",
        "939": "00939",
        "0939": "00939",
        "940": "00940",
        "0940": "00940",
        "6208": "006208",
    }

    df["symbol"] = df["symbol"].astype(str).str.strip()
    df["symbol"] = df["symbol"].map(normalize_symbol)
    df["symbol"] = df["symbol"].map(lambda x: symbol_alias_map.get(x, x))

    # 這裡才是正確過濾：使用 DEFAULT_SYMBOLS / 外部傳入清單
    before_count = len(df)
    df = df[df["symbol"].isin(target_symbol_set)].copy()
    after_count = len(df)

    print(f"[INFO] Target symbol filter: {before_count} -> {after_count}")

    # --------------------------------------------------------
    # 3. ETF name cleaning
    # --------------------------------------------------------
    if "etf_name" not in df.columns:
        df["etf_name"] = ""

    df["etf_name"] = df.apply(
        lambda r: sanitize_etf_name(
            symbol=r["symbol"],
            etf_name=r.get("etf_name", ""),
            name_map=name_map,
        ),
        axis=1,
    )

    # --------------------------------------------------------
    # 4. Convert dates and dividend
    # --------------------------------------------------------
    if "record_date" not in df.columns:
        df["record_date"] = pd.NaT

    df["ex_date"] = pd.to_datetime(df["ex_date"], errors="coerce")
    df["record_date"] = pd.to_datetime(df["record_date"], errors="coerce")
    df["pay_date"] = pd.to_datetime(df["pay_date"], errors="coerce")
    df["dividend"] = pd.to_numeric(df["dividend"], errors="coerce")

    # --------------------------------------------------------
    # 5. Build sorting helpers
    # --------------------------------------------------------
    if "source_url" not in df.columns:
        df["source_url"] = ""

    if "source" not in df.columns:
        df["source"] = "TWSE ETF eFortune dividendList"

    if "scraped_at" not in df.columns:
        df["scraped_at"] = pd.Timestamp.now()

    if "parser" not in df.columns:
        df["parser"] = ""

    df["source_start_year"] = (
        df["source_url"]
        .astype(str)
        .str.extract(r"startDate=(\d{4})")[0]
    )

    df["source_start_year"] = pd.to_numeric(
        df["source_start_year"],
        errors="coerce",
    )

    df["ex_year"] = df["ex_date"].dt.year

    df["year_match"] = (
        df["source_start_year"] == df["ex_year"]
    ).astype(int)

    df["dividend_notna"] = df["dividend"].notna().astype(int)

    df["parser_priority"] = df["parser"].map(
        {
            "table": 2,
            "text_fallback": 1,
        }
    ).fillna(0)

    # --------------------------------------------------------
    # 6. Drop invalid rows
    # --------------------------------------------------------
    before_drop = len(df)

    df = df.dropna(
        subset=[
            "symbol",
            "etf_name",
            "ex_date",
            "pay_date",
            "dividend",
        ]
    ).copy()

    # 排除明顯不合理配息，例如 <= 0
    df = df[df["dividend"] > 0].copy()

    after_drop = len(df)
    print(f"[INFO] Drop invalid rows: {before_drop} -> {after_drop}")

    # --------------------------------------------------------
    # 7. Prefer better rows and deduplicate
    # --------------------------------------------------------
    # 同一個 symbol + ex_date + pay_date 如果有重複：
    # 1. 優先保留 dividend 非空
    # 2. 優先保留 source year 與 ex_date year 一致者
    # 3. 優先保留 table parser
    df = df.sort_values(
        [
            "symbol",
            "ex_date",
            "pay_date",
            "dividend_notna",
            "year_match",
            "parser_priority",
        ],
        ascending=[True, True, True, False, False, False],
    )

    df = df.drop_duplicates(
        subset=["symbol", "ex_date", "pay_date"],
        keep="first",
    )

    # --------------------------------------------------------
    # 8. Keep standard columns
    # --------------------------------------------------------
    standard_cols = [
        "symbol",
        "etf_name",
        "ex_date",
        "record_date",
        "pay_date",
        "dividend",
        "source",
        "source_url",
        "scraped_at",
    ]

    for col in standard_cols:
        if col not in df.columns:
            df[col] = ""

    df = df[standard_cols].copy()
    df = df.sort_values(["symbol", "ex_date"]).reset_index(drop=True)

    return df


def save_dividend_events(raw_df: pd.DataFrame, processed_df: pd.DataFrame) -> None:
    """
    Save raw and processed dividend events separately.
    """
    ensure_parent_dir(RAW_OUTPUT_PATH)
    ensure_parent_dir(PROCESSED_OUTPUT_PATH)

    raw_df.to_csv(
        RAW_OUTPUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    processed_cols = [
        "symbol",
        "etf_name",
        "ex_date",
        "record_date",
        "pay_date",
        "dividend",
        "source",
        "source_url",
        "scraped_at",
    ]

    for col in processed_cols:
        if col not in processed_df.columns:
            processed_df[col] = ""

    processed_df = processed_df[processed_cols].copy()

    processed_df.to_csv(
        PROCESSED_OUTPUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    print(f"[INFO] Saved raw file: {RAW_OUTPUT_PATH}")
    print(f"[INFO] Saved processed file: {PROCESSED_OUTPUT_PATH}")


def main() -> None:
    symbols = DEFAULT_SYMBOLS
    start_year = DEFAULT_START_YEAR
    end_year = DEFAULT_END_YEAR

    print("[INFO] Start fetching ETF dividend events")
    print("[INFO] Symbols:", symbols)
    print("[INFO] Years:", start_year, "to", end_year)

    raw_df = fetch_etf_dividend_events(
        symbols=symbols,
        start_year=start_year,
        end_year=end_year,
        query_by_symbol=False,
        sleep_seconds=REQUEST_SLEEP_SECONDS,
    )

    print("[INFO] Raw result shape:", raw_df.shape)

    if raw_df.empty:
        print("[WARN] No dividend events fetched.")
        return

    print("[INFO] Raw symbol counts:")
    print(raw_df["symbol"].astype(str).map(normalize_symbol).value_counts().sort_index())

    print("[INFO] Raw head:")
    print(raw_df.head(20))

    processed_df = clean_dividend_events(
        raw_df,
        target_symbols=symbols,
        name_map=DEFAULT_NAME_MAP,
    )

    print("[INFO] Processed result shape:", processed_df.shape)

    print("[INFO] Processed head:")
    print(
        processed_df[
            ["symbol", "etf_name", "ex_date", "pay_date", "dividend"]
        ].head(30)
    )

    print("[INFO] Processed symbol counts:")
    print(processed_df["symbol"].value_counts().sort_index())

    print("[INFO] Processed NA counts:")
    print(processed_df.isna().sum())

    missing_symbols = sorted(set(normalize_target_symbols(symbols)) - set(processed_df["symbol"].unique()))
    if missing_symbols:
        print("[WARN] Target symbols with no processed events:", missing_symbols)

    save_dividend_events(
        raw_df=raw_df,
        processed_df=processed_df,
    )


if __name__ == "__main__":
    main()