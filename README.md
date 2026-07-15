## Project Highlights

- Built a Taiwan ETF ex-dividend event study framework covering price, volume, NAV premium/discount, and dividend event data.
- Developed a pre-dividend momentum strategy that enters before ex-dividend dates and exits before Day 0 to avoid price adjustment risk.
- Implemented portfolio-level backtesting with overlapping event allocation, transaction costs, rebalancing, placebo tests, and market filters.
- Research focus: translating Taiwan ETF market microstructure observations into testable trading strategies.

# ETF Alpha Lab

**台灣 ETF 除息事件研究與除息前追息動能策略開發**

本專案研究台灣 ETF 在除息日前後是否存在系統性的價格行為，並進一步檢驗「除息前買盤推升」是否能轉化為可交易的事件驅動策略。

研究核心聚焦於高股息 ETF，透過資料蒐集、資料清洗、事件研究、placebo test、策略回測、交易成本估計與投組層級資金配置，建立一套完整的 ETF 量化研究流程。

---

## 1. 專案概述

近年台灣高股息 ETF 受到投資人高度關注。每逢除息前，部分投資人可能因為想參與配息而提前買進，使 ETF 價格在除息日前出現短期動能。

本專案想驗證的核心假說是：

> 若 ETF 在除息日前存在明顯上漲傾向，且除息後表現轉弱，則可以設計一個「除息前進場、除息日前出場」的事件驅動策略，嘗試捕捉除息前買盤動能，同時避免持有到除息日後的價格調整風險。

目前專案涵蓋：

* 高股息 ETF 除息事件研究
* 全 ETF 除息 Alpha 掃描
* Matched placebo test
* 除息前追息動能策略
* 重疊事件下的投組資金配置
* 交易成本與再平衡影響
* 市場濾網 robustness test
* 0050 與 006208 相對價值策略研究

---

## 2. 研究問題

本專案主要嘗試回答以下問題：

1. 台灣 ETF 在除息日前是否存在異常報酬？
2. 除息前的報酬特徵是否強於除息後？
3. 高股息 ETF 是否比一般 ETF 更容易出現除息前動能？
4. 這個現象是否能轉化為可執行的事件驅動交易策略？
5. 在交易成本與重疊持倉調整後，策略是否仍具有研究價值？
6. 真實除息事件的表現是否優於隨機挑選的 placebo event？

---

## 3. 研究標的

本專案初始聚焦於台灣主要高股息 ETF：

| 代號    | ETF      |
| ----- | -------- |
| 0056  | 元大高股息    |
| 00713 | 元大台灣高息低波 |
| 00878 | 國泰永續高股息  |
| 00919 | 群益台灣精選高息 |
| 00929 | 復華台灣科技優息 |

專案中也包含更廣泛的 ETF 掃描與輔助研究，例如 0050、006208、00939、00940 等。

---

## 4. 主要研究發現

### 4.1 高股息 ETF 除息事件研究

在高股息 ETF 樣本中，最明顯的報酬特徵出現在除息日前。

| 事件視窗             |   平均淨報酬 |  中位數淨報酬 |     勝率 |
| ---------------- | ------: | ------: | -----: |
| Day -5 至 Day -1  | 0.5561% | 0.5713% | 66.15% |
| Day -10 至 Day -1 | 1.8076% | 0.9768% | 66.15% |

結果顯示，除息前視窗的報酬特徵明顯優於除息後視窗。

不過，平均報酬明顯高於中位數報酬，代表部分事件可能對整體績效有較大貢獻。因此，本策略不應被解讀為穩定套利，而應視為一個仍需要進一步驗證的市場現象與策略假說。

### 4.2 成交量變化

除息日前後成交量有明顯增加，尤其集中在 Day -1 與 Day 0 附近。這代表除息事件可能會帶來投資人注意力與短期交易需求。

### 4.3 折溢價變化

ETF 折溢價在除息日前有上升傾向，並在除息後轉弱。這與「投資人為參與配息提前買進，推升市價相對淨值」的假說相符。

### 4.4 除息後表現

除息後 Day 0 至 Day +5 的整體表現較弱，因此本策略設計上不持有到除息日，而是在 Day -1 出場，以避免除息後價格調整與填息不確定性。

---

## 5. 策略設計

### Strategy A：除息前追息動能策略

本專案的核心策略是一個事件驅動、long-only 的 ETF 策略。

### 策略規則

| 項目       | 規則                       |
| -------- | ------------------------ |
| 投資範圍     | 高股息 ETF                  |
| 進場日      | 除息日前 10 個交易日             |
| 出場日      | 除息日前 1 個交易日              |
| 是否持有到除息日 | 否                        |
| 策略方向     | Long-only                |
| 持倉配置     | 當日 active positions 等權配置 |
| 交易成本     | 納入                       |
| 再平衡      | 當持倉數量變化時重新等權             |

策略目標是捕捉除息前買盤動能，同時避免持有到 Day 0 後面臨除息價格調整與填息不確定性。

---

## 6. 投組資金配置邏輯

由於多檔 ETF 的除息事件可能重疊，本專案不是將每個事件都視為獨立交易，而是用投組層級的方式處理資金配置。

當同一天有多檔 ETF 處於持倉期間，資金會在 active positions 之間等權分配。

| Active Positions | 資金配置                  |
| ---------------: | --------------------- |
|          1 檔 ETF | 100%                  |
|          2 檔 ETF | 50% / 50%             |
|          3 檔 ETF | 33.3% / 33.3% / 33.3% |

若其中一檔 ETF 出場，剩餘持倉會重新等權分配。

這樣可以避免重複使用資金，讓回測結果更接近真實投組執行狀況。

---

## 7. 專案架構

```text
ETF-alpha-lab/
│
├── README.md
├── requirements.txt
├── .gitignore
│
├── config/
│   └── etf_universe.yaml
│
├── data/
│   ├── processed/
│   │   ├── etf_daily_panel.csv
│   │   ├── etf_daily_panel_2024-2025.csv
│   │   ├── etf_dividend_events.csv
│   │   ├── etf_nav_panel.csv
│   │   └── strategies/
│   │
│   ├── research/
│   │   ├── high_dividend_ex_dividend_event_data.csv
│   │   ├── high_dividend_ex_dividend_event_summary.csv
│   │   ├── all_etf_ex_dividend_alpha_rank_by_symbol.csv
│   │   ├── all_etf_ex_dividend_alpha_rank_by_category.csv
│   │   ├── all_etf_matched_placebo_table_target_window.csv
│   │   ├── strategy_A_baseline_trades.csv
│   │   └── strategy_A_holding_period_optimization.csv
│   │
│   └── strategy/
│       ├── high_dividend_core_trades.csv
│       ├── high_dividend_core_daily_portfolio_v2.csv
│       ├── high_dividend_core_rebalance_log_v2.csv
│       ├── strategy_trade_summary.csv
│       └── strategy_basket_summary.csv
│
├── notebooks/
│   ├── 0050 與 006208 相對價值策略研究.ipynb
│   ├── ETF除息前入場策略_1.ipynb
│   ├── ETF除息前入場策略_2.ipynb
│   ├── 全 ETF 除息事件 Alpha 掃描研究.ipynb
│   ├── 除息前追息策略統計顯著性驗證.ipynb
│   ├── 高股息 ETF 相對折溢價策略研究.ipynb
│   ├── 高股息 ETF 除息事件研究.ipynb
│   └── 高股息 ETF 除息前追息動能策略開發.ipynb
│
├── report/
│   └── etf_strategy_report.md
│
└── src/
    ├── analysis/
    │   └── check_etf_daily_panel.py
    │
    ├── backtest/
    │   ├── cost.py
    │   └── engine.py
    │
    ├── data/
    │   ├── build_etf_panel.py
    │   ├── etf_loader.py
    │   ├── event_study.py
    │   ├── fetch_etf_dividend_events.py
    │   ├── fetch_etf_nav.py
    │   ├── fetch_price.py
    │   └── symbol_utils.py
    │
    ├── metrics/
    │   └── performance.py
    │
    ├── strategies/
    │   ├── ex_dividend_strategy.py
    │   └── strategy_0050_006208_rv.py
    │
    └── visualization/
        └── plots.py
```

---

## 8. 資料說明

本專案使用以下幾類資料：

### 8.1 ETF 價格資料

用於計算日報酬、事件視窗報酬、策略報酬與投組績效。

### 8.2 ETF NAV 資料

用於分析 ETF 在除息日前後的折溢價變化。

### 8.3 除息事件資料

用於定義 ex-dividend date，並建立事件研究中的 Day 0。

### 8.4 處理後資料

主要處理後資料包括：

```text
data/processed/etf_daily_panel.csv
data/processed/etf_nav_panel.csv
data/processed/etf_dividend_events.csv
```

原始資料檔案未放入 GitHub，以避免 repository 過大，並讓專案聚焦在研究流程與成果展示。

---

## 9. 研究方法

### 9.1 Event Study

本專案將每一個除息日定義為 Day 0，並將報酬、成交量與折溢價依照 event day 對齊。

常用事件視窗包括：

* Day -10 至 Day -1
* Day -5 至 Day -1
* Day 0 至 Day +5
* Day -10 至 Day +10

每個事件視窗會計算：

* 平均報酬
* 中位數報酬
* 勝率
* 累積報酬
* 樣本數
* ETF-level contribution

### 9.2 Matched Placebo Test

為了檢驗除息事件是否真的具備特殊性，本專案使用 matched placebo test。

方法是在同一檔 ETF 內隨機抽取 pseudo-event date，並避免抽到太接近真實除息日的日期，再將真實除息事件表現與隨機事件視窗比較。

這可以幫助判斷除息前報酬是否只是一般市場波動，或確實與除息事件有關。

### 9.3 Strategy Backtest

策略回測將 event study 的發現轉化為實際交易規則，並進一步計算投組層級績效。

回測包含：

* 事件驅動進出場
* Active position tracking
* 等權資金配置
* 交易成本調整
* 每日投組報酬計算
* 持倉變化時再平衡
* trade-level 與 portfolio-level output

---

## 10. 主要輸出檔案

### 研究輸出

```text
data/research/high_dividend_ex_dividend_event_summary.csv
data/research/all_etf_ex_dividend_alpha_rank_by_symbol.csv
data/research/all_etf_ex_dividend_alpha_rank_by_category.csv
data/research/all_etf_matched_placebo_table_target_window.csv
data/research/strategy_A_holding_period_optimization.csv
```

### 策略輸出

```text
data/strategy/high_dividend_core_trades.csv
data/strategy/high_dividend_core_daily_portfolio_v2.csv
data/strategy/high_dividend_core_rebalance_log_v2.csv
data/strategy/strategy_trade_summary.csv
data/strategy/strategy_basket_summary.csv
```

### 研究報告

```text
report/etf_strategy_report.md
```

---

## 11. 如何執行

### 11.1 Clone repository

```bash
git clone https://github.com/timmy0972816111-cyber/ETF-alpha-lab.git
cd ETF-alpha-lab
```

### 11.2 建立虛擬環境

```bash
python -m venv .venv
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
```

macOS / Linux：

```bash
source .venv/bin/activate
```

### 11.3 安裝套件

```bash
pip install -r requirements.txt
```

### 11.4 閱讀 notebooks

建議閱讀順序：

1. 高股息 ETF 除息事件研究
2. 高股息 ETF 除息前追息動能策略開發
3. 除息前追息策略統計顯著性驗證
4. 09_ex_dividend_strategy_backtest_daily_portfolio_v2_cost_rebalance
5. 09_ex_dividend_strategy_backtest_daily_portfolio_v3_market_filter
6. 0050 與 006208 相對價值策略研究

---

## 12. 目前限制

本專案仍屬於研究型 prototype，主要限制包括：

1. 高股息 ETF 除息事件樣本數仍有限。
2. 部分 ETF 上市時間較短，歷史資料長度不一致。
3. 交易成本雖已納入，但尚未完整反映 slippage 與 market impact。
4. 回測結果可能受到 ETF universe 與事件篩選方式影響。
5. 策略尚未納入實盤執行限制。
6. 尚未完整處理配息稅務、流動性限制與容量問題。
7. 若市場參與者逐漸注意到此現象，策略效果可能下降。

---

## 13. 後續優化方向

未來可以進一步改善：

* 建立自動化資料更新流程
* 補上 event window 與 portfolio allocation 的 unit tests
* 整理 notebook 命名與閱讀順序
* 將圖表輸出整理至 `report/figures/`
* 在 README 加入策略績效圖
* 擴大 ETF universe
* 加入不同市場狀態下的 robustness check
* 加入流動性與策略容量分析
* 與 benchmark ETF 進行績效比較
* 將研究流程整理成更完整的 production-style pipeline

---

## 14. 免責聲明

本專案僅供研究與學習用途，不構成任何投資建議、交易建議或金融商品買賣邀約。

過去績效不代表未來報酬。任何交易策略皆存在風險，投資人應自行評估並承擔相關風險。

---

## 15. 作者

Created by Timmy.

本專案是個人 ETF 量化研究流程的一部分，目標是結合台灣 ETF 市場觀察、事件研究方法與投組層級回測，建立可延伸、可驗證的交易研究框架。
