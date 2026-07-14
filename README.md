# Quant Project

A Python-based quantitative trading research and paper trading project for strategy development, backtesting, parameter optimization, train/test validation, and execution workflow simulation.

## Overview

This project was built to organize the full workflow of a quantitative trading system into a modular and extensible structure.  
Instead of keeping strategy ideas scattered across notebooks, the project separates research, backtesting, optimization, diagnostics, and execution into independent modules.

Current capabilities include:

- Historical market data fetching
- Strategy research and modular strategy design
- Stateful backtesting
- Performance metrics and strategy diagnosis
- Parameter optimization
- Train/Test validation workflow
- Paper trading execution flow
- Git-based project version control

## Project Goals

The main goal of this project is not just to test one trading strategy, but to build a reusable framework that can support:

1. Strategy research
2. Robust backtesting
3. Parameter tuning
4. Out-of-sample validation
5. Transition from research to execution

## Features

### 1. Data Layer
- Fetch historical data through Yahoo Finance
- Store and manage raw / processed data
- Prepare for future extension to intraday or broker-based data sources

### 2. Strategy Layer
- Modular strategy design under `src/strategies/`
- Research-oriented notebook workflow
- Strategy rules separated from execution logic

### 3. Backtesting Engine
- Supports stateful backtesting logic
- Tracks position, trades, returns, transaction costs, and equity curve
- Designed to work with strategy-generated entry / exit / stop signals

### 4. Metrics & Diagnosis
- Standard performance metrics:
  - Total Return
  - CAGR
  - Volatility
  - Sharpe Ratio
  - Sortino Ratio
  - Max Drawdown
  - Calmar Ratio
  - Win Rate
  - Profit Factor
  - Payoff Ratio
  - Expectancy
- Strategy diagnosis module for scored and descriptive evaluation

### 5. Parameter Optimization
- Grid search workflow
- Heatmap and 3D visualization support
- Train/Test split for more robust validation

### 6. Execution Layer
- Paper broker implementation
- Position manager
- Risk manager
- Paper trading workflow via `run_paper.py`

## Project Structure

```text
Quant_project/
├─ config/
│  ├─ strategy.yaml
│  └─ optimization.yaml
├─ notebooks/
│  └─ CCI_Strategy.ipynb
├─ src/
│  ├─ data/
│  │  ├─ fetchers.py
│  │  └─ storage.py
│  ├─ strategies/
│  │  ├─ base.py
│  │  └─ ma_cross.py
│  ├─ backtest/
│  │  ├─ engine.py
│  │  ├─ metrics.py
│  │  └─ diagnosis.py
│  ├─ optimization/
│  │  ├─ grid_search.py
│  │  └─ visualization.py
│  ├─ execution/
│  │  ├─ base_broker.py
│  │  └─ paper_broker.py
│  ├─ portfolio/
│  │  ├─ position_manager.py
│  │  └─ risk_manager.py
│  ├─ live/
│  │  └─ run_paper.py
│  └─ utils/
│     └─ config.py
├─ 0.Run_optimization.py
├─ 0.Store_data.py
├─ 0.run_paper.py
├─ Strategy_ma_cross.py
├─ requirements.txt
└─ README.md
```

## Workflow

Research in notebooks  
→ formalize strategy in `src/strategies`  
→ validate with backtest engine  
→ evaluate performance with metrics/diagnosis  
→ optimize parameters  
→ validate on train/test split  
→ run paper trading workflow  
→ prepare for live execution

## Example Strategy Research

The project currently includes research and experimentation on strategies such as:

- Moving Average Cross strategy
- CCI + MA + Volume + ATR trailing stop strategy (research notebook)

The framework is designed so that strategy rules can be changed at the research layer while keeping the backtesting and execution layers reusable.

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/timmy0972816111-cyber/quant-project.git
cd quant-project
```

### 2. Create virtual environment
```bash
python -m venv .venv
```

### 3. Activate virtual environment
#### Windows PowerShell
```bash
.venv\Scripts\Activate.ps1
```
#### Windows CMD
```bash
.venv\Scripts\activate.bat
```
### 4. Install dependencies
```bash
pip install -r requirements.txt
```
## Example Usage
### Run parameter optimization
```bash
python 0.Run_optimization.py
```
### Run paper trading workflow
```bash
python -m src.live.run_paper
```
### Open research notebook

Open:
 `notebooks/CCI_Strategy.ipynb` 
in Jupyter Notebook or VS Code Notebook.

## Design Principles

This project follows several core design principles:

- **Separation of concerns**  
  Strategy logic, backtesting logic, and execution logic are separated.

- **Reusable research framework**  
  New strategies should ideally reuse the same backtest and evaluation framework.

- **Execution-aware research**  
  Strategy development is not limited to backtesting only, but also considers the path toward paper/live execution.

- **Extensibility**  
  The structure is designed to support future additions such as more strategies, more robust portfolio logic, and broker API integration.

## Future Improvements

Planned improvements include:

- Walk-forward validation
- Multi-asset portfolio backtesting
- Broker state persistence
- Order logging system
- Live broker API integration
- More robust intraday data pipeline
- Enhanced execution simulation (slippage / partial fills / order types)

## Notes

This project is currently intended for research and educational use. It is not production-ready for live trading yet.

## Author

Built by Timmy as a personal quantitative trading research project.