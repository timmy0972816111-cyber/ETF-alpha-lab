import pandas as pd


PANEL_PATH = "data/processed/etf_daily_panel.csv"


def quality_flags(panel: pd.DataFrame):
    print("\n========== Quality Flags ==========")

    missing_ratio = (
        panel.groupby("symbol")["nav"]
        .apply(lambda x: x.isna().mean())
        .sort_values(ascending=False)
    )

    bad_missing = missing_ratio[missing_ratio > 0.02]

    if bad_missing.empty:
        print("[PASS] NAV missing ratio looks fine.")
    else:
        print("[WARN] High NAV missing ratio:")
        print(bad_missing)

    panel["premium_diff"] = panel["market_price_to_nav"] - panel["premium_discount"]

    max_abs_diff = panel["premium_diff"].abs().max()

    if pd.isna(max_abs_diff):
        print("[WARN] premium_diff is all NaN.")
    elif max_abs_diff < 0.0002:
        print("[PASS] premium_discount matches market_price_to_nav.")
    else:
        print(f"[WARN] Large premium_diff detected: {max_abs_diff:.6f}")

        print(
            panel.loc[
                panel["premium_diff"].abs() > 0.0002,
                [
                    "date",
                    "symbol",
                    "nav",
                    "market_price",
                    "premium_discount",
                    "market_price_to_nav",
                    "premium_diff",
                ],
            ].head(30)
        )

    weird_premium = panel[
        panel["premium_discount"].abs() > 0.02
    ]

    if weird_premium.empty:
        print("[PASS] No extreme premium/discount detected.")
    else:
        print("[WARN] Extreme premium/discount rows:")
        print(
            weird_premium[
                [
                    "date",
                    "symbol",
                    "nav",
                    "market_price",
                    "premium_discount",
                ]
            ].head(30)
        )

def main():
    panel = pd.read_csv(
        PANEL_PATH,
        dtype={"symbol": str},
    )

    panel["date"] = pd.to_datetime(panel["date"])

    print("========== Basic Info ==========")
    print("Shape:", panel.shape)
    print("Date range:", panel["date"].min(), "to", panel["date"].max())
    print("Symbols:", sorted(panel["symbol"].unique()))

    print("\n========== Missing NAV ratio by symbol ==========")
    print(
        panel.groupby("symbol")["nav"]
        .apply(lambda x: x.isna().mean())
        .sort_values(ascending=False)
    )

    print("\n========== Missing rows ==========")
    missing = panel[panel["nav"].isna()]
    print(missing[["date", "symbol", "close", "nav"]].head(50))
    print("Missing count:", len(missing))

    print("\n========== Premium discount summary ==========")
    print(
        panel.groupby("symbol")["premium_discount"]
        .describe()
    )

    print("\n========== Check market_price_to_nav vs premium_discount ==========")
    panel["premium_diff"] = panel["market_price_to_nav"] - panel["premium_discount"]

    print(
        panel.groupby("symbol")["premium_diff"]
        .describe()
    )

    print("\n========== Latest rows ==========")
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
                "market_price_to_nav",
            ]
        ].tail(30)
    )
    quality_flags(panel)


if __name__ == "__main__":
    main()