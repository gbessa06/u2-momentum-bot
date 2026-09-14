#!/usr/bin/env python3
"""
U2 Momentum — Backtest HONESTO (aviso de survivorship)

ATENÇÃO:
   Este backtest usa a lista ATUAL do Nasdaq-100 (nasdaq100.csv).
   NÃO usa constituents históricos ponto-a-ponto.
   Os resultados podem estar inflacionados por survivorship bias:
   empresas que saíram do índice ao longo dos anos não estão no universo.

   Por isso, compare sempre com o QQQ Buy & Hold (que é o índice
   ajustado à sobrevivência). Este backtest serve para desenvolver o
   motor U2; não é uma validação final para live trading.
"""

import warnings
warnings.filterwarnings("ignore")

import argparse
import csv
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("u2_backtest")

START = "2013-06-01"
START_EVAL = "2014-06-01"
END = "2026-12-31"
SPLIT = "2022-01-01"

LOOKBACK = 126
SKIP = 21
TOP_N = 7
MIN_NAMES = 3
COST_BPS = 5.0

BENCHMARK = "SPY"
QQQ_SYMBOL = "QQQ"

# NOTA: era hardcoded para "universe_2012.csv" (só reproduzia o teste das
# 28 mega-caps). Agora é escolhido via --universe, default nasdaq100.csv
# (o mesmo ficheiro usado pelo u2_bot.py em produção), para os dois
# backtests do README serem reproduzíveis a partir deste único script:
#   python3 backtest_u2_momentum.py --universe nasdaq100.csv
#   python3 backtest_u2_momentum.py --universe universe_2012.csv
UNIVERSE_FILE = Path("nasdaq100.csv")


def load_universe_from_csv() -> list:
    df = pd.read_csv(UNIVERSE_FILE)
    tickers = [str(t).strip().upper() for t in df["Ticker"].tolist()]
    tickers = [t for t in tickers if t]
    return list(dict.fromkeys(tickers))


def download_ohlc(tickers: list):
    raw = yf.download(
        tickers,
        start=START,
        end=END,
        interval="1d",
        auto_adjust=True,
        group_by="ticker",
        progress=False,
        threads=True,
    )

    closes, opens = {}, {}
    for t in tickers:
        try:
            closes[t] = raw[t]["Close"]
            opens[t] = raw[t]["Open"]
        except Exception:
            pass

    close = pd.DataFrame(closes).dropna(how="all").ffill()
    open_df = pd.DataFrame(opens).dropna(how="all").ffill()
    return close, open_df


def metrics(eq: pd.Series, label=""):
    eq = eq.dropna()
    eq = eq[eq > 0]
    rets = eq.pct_change().dropna()
    rets = rets[np.isfinite(rets)]

    if len(rets) < 30:
        return {}

    years = (eq.index[-1] - eq.index[0]).days / 365.25
    total = eq.iloc[-1] / eq.iloc[0] - 1
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    vol = rets.std() * np.sqrt(252)
    sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0
    dd = ((eq.cummax() - eq) / eq.cummax()).max()
    calmar = cagr / dd if dd > 0 else 0

    return {
        "label": label,
        "Return%": total * 100,
        "CAGR%": cagr * 100,
        "MaxDD%": dd * 100,
        "Vol%": vol * 100,
        "Sharpe": sharpe,
        "Calmar": calmar,
    }


def run_backtest():
    universe = load_universe_from_csv()
    tickers = sorted(set(universe + [BENCHMARK, QQQ_SYMBOL]))
    close, open_df = download_ohlc(tickers)

    bench = close[BENCHMARK].dropna()
    avail = [t for t in universe if t in close.columns]

    rs = close[avail].div(bench.reindex(close.index).ffill(), axis=0)
    mom = rs.pct_change(LOOKBACK).shift(SKIP)

    start_ts = pd.Timestamp(START_EVAL)
    dates = close.index[close.index >= start_ts]

    rebal_dates = pd.DatetimeIndex(
        pd.Series(index=dates, data=1)
        .resample("MS")
        .first()
        .dropna()
        .index
    )

    cash = 10_000.0
    qty: dict = {}
    cost = COST_BPS / 1e4
    records = []

    for i, t in enumerate(dates):
        if t in rebal_dates and i > 0:
            prev = dates[dates.get_loc(t) - 1]
            score = mom.loc[prev].dropna()
            score = score[score > 0].sort_values(ascending=False)
            targets = [s for s in score.index[:TOP_N]]

            # vender
            for sym in list(qty.keys()):
                if sym not in targets and sym in open_df.columns:
                    px = open_df.at[t, sym]
                    if px > 0:
                        cash += qty[sym] * px * (1 - cost)
                        del qty[sym]

            # comprar
            if targets:
                per = cash / len(targets)
                for sym in targets:
                    if sym in open_df.columns and t in open_df.index:
                        px = open_df.at[t, sym]
                        if px > 0:
                            q = (per * (1 - cost)) / px
                            if q > 0:
                                qty[sym] = qty.get(sym, 0.0) + q
                                cash -= q * px

        invested = sum(
            q * close.at[t, sym]
            for sym, q in qty.items()
            if sym in close.columns and pd.notna(close.at[t, sym])
        )
        equity = cash + invested
        records.append((t, equity))

    eq = pd.Series([r[1] for r in records], index=[r[0] for r in records])

    spy_bh = close[BENCHMARK] / close[BENCHMARK].iloc[0] * 10_000
    qqq_bh = close[QQQ_SYMBOL] / close[QQQ_SYMBOL].iloc[0] * 10_000

    return eq, spy_bh, qqq_bh


def print_block(title, items):
    print(f"\n{title}")
    print("=" * 80)
    for r in items:
        if r:
            print(
                f"{r['label']:<18} "
                f"CAGR={r['CAGR%']:7.2f}%  "
                f"MaxDD={r['MaxDD%']:7.2f}%  "
                f"SHARPE={r['Sharpe']:6.2f}  "
                f"CALMAR={r['Calmar']:6.2f}"
            )


def main():
    global UNIVERSE_FILE
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", default=str(UNIVERSE_FILE),
                         help="CSV com coluna 'Ticker' (default: nasdaq100.csv)")
    args = parser.parse_args()
    UNIVERSE_FILE = Path(args.universe)

    print(
        "=" * 80
        + f"\nAVISO: Backtest com universo de '{UNIVERSE_FILE.name}'.\n"
          "Se for a lista atual do Nasdaq-100, pode conter survivorship bias.\n"
          "Compare sempre com QQQ B&H.\n"
        + "=" * 80
    )

    eq, spy, qqq = run_backtest()

    split = pd.Timestamp(SPLIT)
    is_mask = eq.index < split
    oos_mask = eq.index >= split

    print_block(
        "PERÍODO COMPLETO (2014-2026)",
        [
            metrics(eq, "U2 Momentum"),
            metrics(spy.reindex(eq.index).ffill(), "SPY B&H"),
            metrics(qqq.reindex(eq.index).ffill(), "QQQ B&H"),
        ],
    )

    print_block(
        "IN-SAMPLE (< 2022)",
        [
            metrics(eq[is_mask], "U2 Momentum"),
            metrics(qqq.reindex(eq.index).ffill()[is_mask], "QQQ B&H"),
        ],
    )

    print_block(
        "OUT-OF-SAMPLE (>= 2022)",
        [
            metrics(eq[oos_mask], "U2 Momentum"),
            metrics(qqq.reindex(eq.index).ffill()[oos_mask], "QQQ B&H"),
        ],
    )

    pd.DataFrame({"equity": eq}).to_csv("u2_backtest_equity.csv")
    print("\nExportado u2_backtest_equity.csv")


if __name__ == "__main__":
    main()