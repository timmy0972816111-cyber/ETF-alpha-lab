import csv
import re
import time
from io import StringIO
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm


MOPS_NEW_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t78sb35_new"
MOPS_FINAL_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t78sb35"
MOPS_CSV_URL = "https://mopsov.twse.com.tw/server-java/t105sb02"
MOPS_REFERER = "https://mopsov.twse.com.tw/mops/web/t78sb35_new"


STANDARD_COLS = [
    "date",
    "symbol",
    "company",
    "fund_name",
    "nav",
    "prev_nav",
    "nav_change",
    "nav_change_pct",
    "market_price",
    "premium_discount",
]


# ============================================================
# Basic utils
# ============================================================

def clean_text(x) -> str:
    """
    Clean text from MOPS HTML / CSV.
    """

    if x is None or pd.isna(x):
        return ""

    x = str(x).strip()

    x = (
        x.replace("\xa0", "")
        .replace("&nbsp;", "")
        .replace("&nbsp", "")
        .replace("\n", "")
        .replace("\r", "")
        .strip()
    )

    # Excel-style wrapper: ="0050"
    if x.startswith('="') and x.endswith('"'):
        x = x[2:-1]

    return x.strip()


def normalize_symbol(x) -> str:
    """
    Normalize Taiwan ETF symbol and preserve leading zeros.

    Examples
    --------
    ="0050" -> 0050
    50.0 -> 0050
    006208 -> 006208
    """

    x = clean_text(x)

    if x.endswith(".0"):
        x = x[:-2]

    # If accidentally converted to short numeric code, e.g. 50 -> 0050.
    # Note: 006208 is 6 digits and will not be affected by zfill(4).
    if x.isdigit() and len(x) < 4:
        x = x.zfill(4)

    return x


def is_symbol(x: str) -> bool:
    """
    This version only accepts numeric ETF symbols.

    This intentionally excludes:
    - 00981A
    - 00403A
    - 00631L
    - 00632R
    """

    x = normalize_symbol(x)
    return bool(re.fullmatch(r"\d{4,6}", x or ""))


def is_company(x: str) -> bool:
    x = clean_text(x)

    return (
        "投信" in x
        or "華南永昌" in x
        or "證券投資信託" in x
    )


def to_number(x):
    x = clean_text(x)

    if x == "":
        return pd.NA

    x = x.replace(",", "").replace("%", "")

    return pd.to_numeric(x, errors="coerce")


def parse_date(x):
    """
    Parse MOPS date.

    Supports:
    - 2026/05/18
    - 115/05/18
    - ="2026/05/18"
    """

    x = clean_text(x)

    if x == "":
        return pd.NaT

    parts = x.replace("-", "/").split("/")

    if len(parts) == 3:
        try:
            year = int(parts[0])
            month = int(parts[1])
            day = int(parts[2])

            # ROC year
            if year < 1911:
                year += 1911

            return pd.Timestamp(year=year, month=month, day=day)

        except ValueError:
            return pd.NaT

    return pd.to_datetime(x, errors="coerce")


def pad(row: list[str], n: int = 11) -> list[str]:
    row = [clean_text(x) for x in row]

    if len(row) < n:
        row += [""] * (n - len(row))

    return row


# ============================================================
# MOPS crawler
# ============================================================

def get_query_headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
        "Referer": MOPS_REFERER,
        "Origin": "https://mopsov.twse.com.tw",
    }


def get_csv_headers() -> dict:
    """
    t105sb02 is a document download, not XHR.
    Network showed Origin as null, so we follow browser behavior.
    """

    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8,"
            "application/signed-exchange;v=b3;q=0.7"
        ),
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "null",
        "Upgrade-Insecure-Requests": "1",
    }


def build_payload(date: str | pd.Timestamp) -> dict:
    date = pd.to_datetime(date)

    return {
        "encodeURIComponent": "1",
        "step": "1",
        "firstin": "1",
        "off": "1",
        "TYPEK": "sii",
        "year": str(date.year - 1911),
        "month": f"{date.month:02d}",
        "day": f"{date.day:02d}",
    }


def post_with_retry(
    session: requests.Session,
    url: str,
    headers: dict,
    data: dict,
    timeout: int = 60,
    retries: int = 3,
    sleep_seconds: float = 2.0,
) -> requests.Response:
    """
    POST request with retry.
    MOPS sometimes times out, so retry is necessary.
    """

    last_error = None

    for attempt in range(1, retries + 1):
        try:
            response = session.post(
                url,
                headers=headers,
                data=data,
                timeout=timeout,
            )
            return response

        except requests.exceptions.ReadTimeout as e:
            last_error = e
            print(f"[WARN] Read timeout on attempt {attempt}/{retries}: {url}")
            time.sleep(sleep_seconds)

        except requests.exceptions.ConnectionError as e:
            last_error = e
            print(f"[WARN] Connection error on attempt {attempt}/{retries}: {url}")
            time.sleep(sleep_seconds)

    raise last_error


def extract_auto_form(html: str) -> tuple[str, dict]:
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", {"name": "autoForm1"})

    if form is None:
        return MOPS_FINAL_URL, {}

    action = form.get("action") or MOPS_FINAL_URL
    action_url = urljoin("https://mopsov.twse.com.tw", action)

    payload = {}

    for tag in form.find_all("input"):
        name = tag.get("name")
        value = tag.get("value", "")

        if name:
            payload[name] = value

    return action_url, payload


def fetch_mops_html_and_filename(
    date: str | pd.Timestamp,
    debug: bool = False,
) -> tuple[str, str, requests.Session]:
    """
    1. POST ajax_t78sb35_new
    2. POST ajax_t78sb35
    3. Extract CSV filename from final HTML
    """

    date = pd.to_datetime(date)

    session = requests.Session()
    headers = get_query_headers()
    payload = build_payload(date)

    # Step 1: ajax_t78sb35_new
    r1 = post_with_retry(
        session=session,
        url=MOPS_NEW_URL,
        headers=headers,
        data=payload,
        timeout=60,
        retries=3,
        sleep_seconds=2.0,
    )

    r1.encoding = "utf-8"

    if r1.status_code != 200:
        raise ValueError(f"Step 1 failed: {r1.status_code}")

    action_url, hidden_payload = extract_auto_form(r1.text)

    final_payload = hidden_payload if hidden_payload else payload

    for k, v in payload.items():
        final_payload.setdefault(k, v)

    # Step 2: ajax_t78sb35
    r2 = post_with_retry(
        session=session,
        url=action_url,
        headers=headers,
        data=final_payload,
        timeout=60,
        retries=3,
        sleep_seconds=2.0,
    )

    r2.encoding = "utf-8"

    if r2.status_code != 200:
        raise ValueError(f"Step 2 failed: {r2.status_code}")

    html = r2.text

    if "查無資料" in html:
        return html, "", session

    soup = BeautifulSoup(html, "html.parser")
    filename_input = soup.find("input", {"name": "filename"})

    if filename_input is None:
        raise ValueError("CSV filename input not found in MOPS HTML.")

    filename = filename_input.get("value", "")

    if filename == "":
        raise ValueError("CSV filename is empty.")

    if debug:
        out_dir = Path("data/raw/nav/debug")
        out_dir.mkdir(parents=True, exist_ok=True)

        html_path = out_dir / f"mops_nav_{date:%Y-%m-%d}.html"
        html_path.write_text(html, encoding="utf-8")

        print(f"[DEBUG] HTML saved: {html_path}")
        print(f"[DEBUG] HTML length: {len(html)}")
        print(f"[DEBUG] CSV filename: {filename}")

    return html, filename, session


def decode_csv_response(response: requests.Response) -> str:
    """
    MOPS response header says iso-8859-1,
    but Chinese content usually needs cp950 / big5.
    """

    content = response.content

    for enc in ["cp950", "big5", "utf-8-sig", "utf-8", "iso-8859-1"]:
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue

    return content.decode("cp950", errors="ignore")


def download_mops_csv(
    filename: str,
    session: Optional[requests.Session] = None,
    debug: bool = False,
) -> str:
    """
    Real CSV download endpoint:
    https://mopsov.twse.com.tw/server-java/t105sb02

    Payload:
    firstin=true&step=10&filename=t78sb35_YYYYMMDD.csv
    """

    if session is None:
        session = requests.Session()

    payload = {
        "firstin": "true",
        "step": "10",
        "filename": filename,
    }

    headers = get_csv_headers()

    response = post_with_retry(
        session=session,
        url=MOPS_CSV_URL,
        headers=headers,
        data=payload,
        timeout=60,
        retries=3,
        sleep_seconds=2.0,
    )

    csv_text = decode_csv_response(response)

    content_type = response.headers.get("content-type", "")
    content_disposition = response.headers.get("content-disposition", "")

    if debug:
        out_dir = Path("data/raw/nav/debug")
        out_dir.mkdir(parents=True, exist_ok=True)

        raw_path = out_dir / filename
        raw_path.write_text(csv_text, encoding="utf-8-sig")

        print(f"[DEBUG] CSV status: {response.status_code}")
        print(f"[DEBUG] CSV content-type: {content_type}")
        print(f"[DEBUG] CSV content-disposition: {content_disposition}")
        print(f"[DEBUG] CSV saved: {raw_path}")
        print("[DEBUG] CSV preview:")
        print(csv_text[:500])

    if response.status_code != 200:
        raise ValueError(f"CSV download failed: {response.status_code}")

    if "<html" in csv_text.lower() or "step參數傳入錯誤" in csv_text:
        raise ValueError("CSV download returned HTML error page, not CSV.")

    if "公司名稱" not in csv_text or "基金代碼" not in csv_text:
        raise ValueError("Downloaded content does not look like MOPS NAV CSV.")

    return csv_text


# ============================================================
# CSV parser
# ============================================================

def is_index_row(row: list[str]) -> bool:
    """
    Identify index information rows.

    Important:
    ETF fund names may contain the word '指數', e.g. 0052:
    富邦台灣科技指數證券投資信託基金

    So we cannot simply skip rows where row[2] contains '指數'.
    We should only treat a row as index row when it is NOT an ETF data row.
    """

    row = pad(row, 11)
    text = " ".join(row)

    # If row[1] is an ETF symbol, this is an ETF data row.
    # Do not skip it just because fund name contains '指數'.
    if is_symbol(row[1]):
        return False

    return (
        "標的指數名稱" in text
        or "指數收盤日期" in text
        or "收盤指數" in text
    )


def parse_csv_rows(
    csv_text: str,
    symbols: Optional[list[str]] = None,
    debug: bool = False,
) -> pd.DataFrame:
    """
    Parse MOPS CSV.

    CSV ETF row format:
    公司名稱, 基金代碼, 基金名稱, 淨值日期, 淨值, 前一日淨值,
    淨值漲跌, 淨值漲跌%, 當日收盤價, 折溢價%
    """

    if debug:
        print("[DEBUG] csv_text length:", len(csv_text))
        print("[DEBUG] contains 0052:", "0052" in csv_text)
        print("[DEBUG] contains 富邦科技:", "富邦科技" in csv_text)
        print("[DEBUG] contains 富邦台灣科技:", "富邦台灣科技" in csv_text)
        print("[DEBUG] contains 富邦臺灣科技:", "富邦臺灣科技" in csv_text)
        print("[DEBUG] contains 富邦台灣摩根:", "富邦台灣摩根" in csv_text)
        print("[DEBUG] contains 富邦臺灣摩根:", "富邦臺灣摩根" in csv_text)
        print("[DEBUG] contains MSCI台灣指數:", "MSCI台灣指數" in csv_text)
        print("[DEBUG] contains MSCI臺灣指數:", "MSCI臺灣指數" in csv_text)

    reader = csv.reader(StringIO(csv_text))

    records = []
    current_company = ""

    for i, raw in enumerate(reader):
        row = pad(raw, 11)

        if debug:
            row_text = " ".join(row)

            if (
                i < 40
                or "0052" in row_text
                or "富邦科技" in row_text
                or "富邦台灣科技" in row_text
                or "富邦臺灣科技" in row_text
                or "富邦台灣摩根" in row_text
                or "富邦臺灣摩根" in row_text
                or "MSCI台灣指數" in row_text
                or "MSCI臺灣指數" in row_text
            ):
                print(f"[CSV ROW {i}] {row}")

        # Header row
        if row[0] == "公司名稱" and row[1] == "基金代碼":
            continue

        # Update company block
        if is_company(row[0]):
            current_company = row[0]

        # Skip index rows
        if is_index_row(row):
            continue

        symbol = normalize_symbol(row[1])

        # This version excludes ETF symbols containing letters.
        if not is_symbol(symbol):
            continue

        company = row[0] if row[0] != "" else current_company
        fund_name = row[2]

        nav_date = parse_date(row[3])
        nav = to_number(row[4])
        prev_nav = to_number(row[5])
        nav_change = to_number(row[6])
        nav_change_pct = to_number(row[7])
        market_price = to_number(row[8])
        premium = to_number(row[9])

        if pd.isna(nav_date) or pd.isna(nav):
            continue

        # ETF data row should have market price or premium.
        # Index rows usually have both empty.
        if pd.isna(market_price) and pd.isna(premium):
            continue

        records.append({
            "date": nav_date,
            "symbol": symbol,
            "company": company,
            "fund_name": fund_name,
            "nav": nav,
            "prev_nav": prev_nav,
            "nav_change": nav_change,
            "nav_change_pct": (
                nav_change_pct / 100 if not pd.isna(nav_change_pct) else pd.NA
            ),
            "market_price": market_price,
            "premium_discount": (
                premium / 100 if not pd.isna(premium) else pd.NA
            ),
        })

    df = pd.DataFrame(records)

    if df.empty:
        return pd.DataFrame(columns=STANDARD_COLS)

    df = df[STANDARD_COLS]

    # Preserve leading zeros
    df["symbol"] = df["symbol"].astype(str)

    df = df.drop_duplicates(subset=["date", "symbol"], keep="first")

    if symbols is not None:
        symbols = [str(s) for s in symbols]
        df = df[df["symbol"].isin(symbols)].copy()

    df = df.sort_values(["date", "symbol"]).reset_index(drop=True)

    if debug:
        print("[DEBUG] Parsed CSV result:")
        print(df)
        print("[DEBUG] Shape:", df.shape)
        print("[DEBUG] Symbols:", df["symbol"].unique())

    return df


# ============================================================
# Public API
# ============================================================

def fetch_mops_nav_by_date(
    date: str | pd.Timestamp,
    symbols: Optional[list[str]] = None,
    save_daily: bool = True,
    output_dir: str = "data/raw/nav",
    debug: bool = False,
) -> pd.DataFrame:
    date = pd.to_datetime(date)

    html, filename, session = fetch_mops_html_and_filename(
        date=date,
        debug=debug,
    )

    if "查無資料" in html or filename == "":
        return pd.DataFrame(columns=STANDARD_COLS)

    csv_text = download_mops_csv(
        filename=filename,
        session=session,
        debug=debug,
    )

    df = parse_csv_rows(
        csv_text=csv_text,
        symbols=symbols,
        debug=debug,
    )

    if save_daily and not df.empty:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        path = output_dir / f"mops_nav_{date:%Y-%m-%d}.csv"

        df.to_csv(path, index=False, encoding="utf-8-sig")

    return df


def fetch_mops_nav_by_date_with_retry(
    date: str | pd.Timestamp,
    symbols: Optional[list[str]] = None,
    save_daily: bool = True,
    output_dir: str = "data/raw/nav",
    debug: bool = False,
    retries: int = 3,
    sleep_seconds: float = 3.0,
) -> pd.DataFrame:
    """
    Fetch one date with retry.

    This handles:
    - timeout
    - temporary MOPS server error
    - CSV download error
    - temporary empty result
    """

    date = pd.to_datetime(date)
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            df = fetch_mops_nav_by_date(
                date=date,
                symbols=symbols,
                save_daily=save_daily,
                output_dir=output_dir,
                debug=debug,
            )

            if not df.empty:
                return df

            print(f"[WARN] Empty NAV on {date:%Y-%m-%d}, attempt {attempt}/{retries}")

        except Exception as e:
            last_error = e
            print(f"[WARN] Failed on {date:%Y-%m-%d}, attempt {attempt}/{retries}: {e}")

        time.sleep(sleep_seconds)

    if last_error is not None:
        print(f"[ERROR] Give up on {date:%Y-%m-%d}: {last_error}")
    else:
        print(f"[ERROR] Give up on {date:%Y-%m-%d}: empty dataframe")

    return pd.DataFrame(columns=STANDARD_COLS)


def fetch_mops_nav_range(
    start: str,
    end: str,
    symbols: Optional[list[str]] = None,
    sleep_seconds: float = 2.0,
    save_daily: bool = True,
    save_panel: bool = True,
    raw_output_dir: str = "data/raw/nav",
    processed_output_path: str = "data/processed/etf_nav_panel.csv",
    debug: bool = False,
    retries_per_date: int = 3,
) -> pd.DataFrame:
    dates = pd.date_range(start=start, end=end, freq="D")

    all_data = []
    failed_dates = []

    for date in tqdm(dates, desc="Fetching MOPS ETF NAV"):
        df = fetch_mops_nav_by_date_with_retry(
            date=date,
            symbols=symbols,
            save_daily=save_daily,
            output_dir=raw_output_dir,
            debug=debug,
            retries=retries_per_date,
            sleep_seconds=3.0,
        )

        if not df.empty:
            all_data.append(df)
        else:
            failed_dates.append(date)

        time.sleep(sleep_seconds)

    if len(all_data) == 0:
        print("[WARN] No NAV data fetched.")
        return pd.DataFrame(columns=STANDARD_COLS)

    panel = pd.concat(all_data, ignore_index=True)

    panel["date"] = pd.to_datetime(panel["date"])
    panel["symbol"] = panel["symbol"].astype(str)

    panel = panel.drop_duplicates(subset=["date", "symbol"], keep="last")
    panel = panel.sort_values(["date", "symbol"]).reset_index(drop=True)

    if save_panel:
        processed_output_path = Path(processed_output_path)
        processed_output_path.parent.mkdir(parents=True, exist_ok=True)

        panel.to_csv(
            processed_output_path,
            index=False,
            encoding="utf-8-sig",
        )

    if failed_dates:
        print("\n[WARN] Failed / empty dates:")
        for d in failed_dates:
            print(d.strftime("%Y-%m-%d"))

    return panel


# ============================================================
# Missing date check and backfill
# ============================================================

def get_expected_dates_from_price(
    price_path: str = "data/raw/prices/0050.csv",
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DatetimeIndex:
    """
    Use ETF price dates as expected trading dates.

    This avoids checking weekends and holidays.
    """

    price_path = Path(price_path)

    if not price_path.exists():
        raise FileNotFoundError(f"Price file not found: {price_path}")

    price = pd.read_csv(price_path)

    if "date" not in price.columns:
        raise ValueError(f"Price file missing date column: {price_path}")

    price["date"] = pd.to_datetime(price["date"])

    if start is not None:
        price = price[price["date"] >= pd.to_datetime(start)]

    if end is not None:
        price = price[price["date"] <= pd.to_datetime(end)]

    expected_dates = pd.DatetimeIndex(sorted(price["date"].dropna().unique()))

    return expected_dates


def find_missing_nav_dates(
    start: str,
    end: str,
    nav_path: str = "data/processed/etf_nav_panel.csv",
    symbols: Optional[list[str]] = None,
    expected_price_path: str = "data/raw/prices/0050.csv",
    min_symbols_per_day: Optional[int] = None,
) -> list[pd.Timestamp]:
    """
    Find trading dates that are missing NAV data.

    A date is considered missing if:
    1. date does not exist in NAV file, or
    2. number of symbols on that date is less than min_symbols_per_day
    """

    expected_dates = get_expected_dates_from_price(
        price_path=expected_price_path,
        start=start,
        end=end,
    )

    nav_path = Path(nav_path)

    if not nav_path.exists():
        return list(expected_dates)

    nav = pd.read_csv(nav_path, dtype={"symbol": str})

    if nav.empty:
        return list(expected_dates)

    nav["date"] = pd.to_datetime(nav["date"])
    nav["symbol"] = nav["symbol"].astype(str)

    if symbols is not None:
        symbols = [str(s) for s in symbols]
        nav = nav[nav["symbol"].isin(symbols)].copy()

    if min_symbols_per_day is None:
        min_symbols_per_day = len(symbols) if symbols is not None else 1

    daily_counts = nav.groupby("date")["symbol"].nunique()

    missing_dates = []

    for date in expected_dates:
        count = daily_counts.get(date, 0)

        if count < min_symbols_per_day:
            missing_dates.append(pd.Timestamp(date))

    return missing_dates


def backfill_missing_nav_dates(
    start: str,
    end: str,
    symbols: Optional[list[str]] = None,
    nav_path: str = "data/processed/etf_nav_panel.csv",
    expected_price_path: str = "data/raw/prices/0050.csv",
    sleep_seconds: float = 2.0,
    retries_per_date: int = 5,
    debug: bool = False,
) -> pd.DataFrame:
    """
    Backfill missing NAV dates and merge with existing NAV panel.
    """

    nav_path = Path(nav_path)

    missing_dates = find_missing_nav_dates(
        start=start,
        end=end,
        nav_path=str(nav_path),
        symbols=symbols,
        expected_price_path=expected_price_path,
        min_symbols_per_day=len(symbols) if symbols is not None else 1,
    )

    print(f"[INFO] Missing dates count: {len(missing_dates)}")

    if len(missing_dates) == 0:
        print("[INFO] No missing NAV dates.")

        if nav_path.exists():
            panel = pd.read_csv(nav_path, dtype={"symbol": str})
            panel["date"] = pd.to_datetime(panel["date"])
            return panel

        return pd.DataFrame(columns=STANDARD_COLS)

    print("[INFO] Missing dates:")
    for d in missing_dates:
        print(d.strftime("%Y-%m-%d"))

    new_data = []

    for date in tqdm(missing_dates, desc="Backfilling missing NAV"):
        df = fetch_mops_nav_by_date_with_retry(
            date=date,
            symbols=symbols,
            save_daily=True,
            output_dir="data/raw/nav",
            debug=debug,
            retries=retries_per_date,
            sleep_seconds=3.0,
        )

        if not df.empty:
            new_data.append(df)

        time.sleep(sleep_seconds)

    if nav_path.exists():
        old_panel = pd.read_csv(nav_path, dtype={"symbol": str})

        if not old_panel.empty:
            old_panel["date"] = pd.to_datetime(old_panel["date"])
            old_panel["symbol"] = old_panel["symbol"].astype(str)
    else:
        old_panel = pd.DataFrame(columns=STANDARD_COLS)

    if new_data:
        new_panel = pd.concat(new_data, ignore_index=True)
    else:
        new_panel = pd.DataFrame(columns=STANDARD_COLS)

    combined = pd.concat([old_panel, new_panel], ignore_index=True)

    if not combined.empty:
        combined["date"] = pd.to_datetime(combined["date"])
        combined["symbol"] = combined["symbol"].astype(str)

        combined = combined.drop_duplicates(
            subset=["date", "symbol"],
            keep="last",
        )

        combined = combined.sort_values(["date", "symbol"]).reset_index(drop=True)

    nav_path.parent.mkdir(parents=True, exist_ok=True)

    combined.to_csv(
        nav_path,
        index=False,
        encoding="utf-8-sig",
    )

    return combined


# ============================================================
# Main
# ============================================================

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

    # --------------------------------------------------------
    # Mode 1: First full fetch
    # --------------------------------------------------------
    
    panel = fetch_mops_nav_range(
        start="2016-01-01",
        end="2026-05-18",
        symbols=symbols,
        sleep_seconds=2.0,
        save_daily=True,
        save_panel=True,
        debug=False,
        retries_per_date=3,
    )

    #--------------------------------------------------------
    #Mode 2: Backfill missing dates
    #After first full fetch, you can comment Mode 1 and use this.
    #--------------------------------------------------------
    # panel = backfill_missing_nav_dates(
    #     start="2024-01-01",
    #     end="2026-05-18",
    #     symbols=symbols,
    #     nav_path="data/processed/etf_nav_panel.csv",
    #     expected_price_path="data/raw/prices/0050.csv",
    #     sleep_seconds=2.0,
    #     retries_per_date=5,
    #     debug=False,
    # )

    print(panel)
    print(panel.shape)