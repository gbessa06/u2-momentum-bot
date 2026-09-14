#!/usr/bin/env python3
"""
U2 MOMENTUM -- Trading212 Monthly Rebalance (VERSÃO FINAL)

Universo : lido de nasdaq100.csv (local, gerado uma vez).
Sinal    : momentum relativo ao SPY, lookback 126, skip 21.
Carteira : top 7 com momentum positivo, equal weight.
Execução : uma vez por mês, via Trading212 API.

Chaves API : keys.env com T212_API_KEY e T212_API_SECRET.
Por defeito : DRY_RUN=True (não envia ordens).
"""

import base64
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

# ==============================================================================
# CONFIG
# ==============================================================================

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / "keys.env")

API_KEY = os.environ.get("T212_API_KEY", "")
API_SECRET = os.environ.get("T212_API_SECRET", "")

if not API_KEY or not API_SECRET:
    raise SystemExit("Missing API Keys in keys.env.")

AUTH_HEADER = "Basic " + base64.b64encode(
    f"{API_KEY}:{API_SECRET}".encode()
).decode()

# Demo por defeito. Para live muda para:
# BASE_URL = "https://live.trading212.com/api/v0"
BASE_URL = "https://demo.trading212.com/api/v0"

HEADERS = {
    "Authorization": AUTH_HEADER,
    "Content-Type": "application/json",
}

# SEGURANÇA: DRY_RUN=True por defeito
DRY_RUN = True

# ==============================================================================
# PARÂMETROS DA ESTRATÉGIA
# ==============================================================================

UNIVERSE_FILE = HERE / "nasdaq100.csv"
STATE_FILE = HERE / "u2_state.json"
MAP_FILE = HERE / "u2_instrument_map.json"
ALL_INSTRUMENTS_FILE = HERE / "u2_all_instruments.json"
TRADES_CSV = HERE / "u2_trades.csv"
TELEMETRY_CSV = HERE / "u2_telemetria.csv"
LOG_FILE = HERE / "u2_bot.log"

LOOKBACK = 126
SKIP = 21
TOP_N = 7
MIN_NAMES = 3
REBAL_TOLERANCE = 0.10
MAX_DATA_AGE_DAYS = 5

# Ficha de logging
log = logging.getLogger("u2")
log.setLevel(logging.INFO)
log.handlers.clear()
formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
file_handler = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3)
file_handler.setFormatter(formatter)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
log.addHandler(file_handler)
log.addHandler(console_handler)


# ==============================================================================
# UNIVERSO
# ==============================================================================

def load_universe_from_csv() -> list:
    if not UNIVERSE_FILE.exists():
        raise SystemExit(
            "Falta `nasdaq100.csv`. Gera-o com o script `gen_nasdaq100.py`."
        )

    df = pd.read_csv(UNIVERSE_FILE)

    if "Ticker" not in df.columns:
        raise SystemExit("O CSV tem de ter uma coluna 'Ticker'.")

    tickers = [str(t).strip().upper() for t in df["Ticker"].tolist()]
    tickers = [t for t in tickers if t]
    tickers = list(dict.fromkeys(tickers))

    log.info(f"Universo carregado de nasdaq100.csv: {len(tickers)} tickers")
    return tickers


# ==============================================================================
# API T212
# ==============================================================================

def api_get(path: str, max_retries=3):
    for attempt in range(max_retries):
        try:
            r = requests.get(f"{BASE_URL}{path}", headers=HEADERS, timeout=30)
            if r.status_code == 429:
                sleep_s = 60 * (attempt + 1)
                log.warning(f"429 GET {path}. Dormindo {sleep_s}s...")
                time.sleep(sleep_s)
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            raise e
    raise RuntimeError(f"Falhou GET {path} após {max_retries} tentativas")


def api_post(path: str, payload: dict, max_retries=3):
    for attempt in range(max_retries):
        time.sleep(5)
        try:
            r = requests.post(f"{BASE_URL}{path}", headers=HEADERS, json=payload, timeout=30)
            if r.status_code == 429:
                sleep_s = 60 * (attempt + 1)
                log.warning(f"429 POST {path}. Dormindo {sleep_s}s...")
                time.sleep(sleep_s)
                continue
            if r.status_code != 200:
                log.error(f"POST {path} falhou: {r.status_code} {r.text}")
                return None
            return r.json()
        except requests.exceptions.RequestException as e:
            log.error(f"POST {path} excepção: {e}")
            raise e
    return None


def get_account_cash() -> float:
    return float(api_get("/equity/account/cash").get("free", 0.0))


def get_t212_positions() -> dict:
    return {p["ticker"]: p for p in api_get("/equity/portfolio")}


def place_order(t212_ticker: str, quantity: float):
    if DRY_RUN:
        log.info(f"[DRY_RUN] ORDER {t212_ticker} qty={quantity:+.6f}")
        return {"id": "DRY_RUN", "ticker": t212_ticker, "quantity": quantity}
    payload = {"ticker": t212_ticker, "quantity": float(quantity)}
    return api_post("/equity/orders/market", payload)


# ==============================================================================
# MAPA
# ==============================================================================

def get_all_instruments_cached():
    if ALL_INSTRUMENTS_FILE.exists():
        try:
            with open(ALL_INSTRUMENTS_FILE) as f:
                return json.load(f)
        except Exception:
            pass

    log.info("A obter instrumentos do T212...")
    instruments = api_get("/equity/metadata/instruments")
    with open(ALL_INSTRUMENTS_FILE, "w") as f:
        json.dump(instruments, f)

    return instruments


def build_instrument_map():
    log.info("A construir mapa dinâmico Yahoo -> T212...")
    universe = load_universe_from_csv()
    instruments = get_all_instruments_cached()

    lookup = {}
    for ins in instruments:
        if ins.get("type") != "STOCK":
            continue
        lookup[str(ins.get("ticker", ""))] = ins

    mapping = {}
    missing = []

    for y in universe:
        found = None
        for candidate in [f"{y}_US_EQ", f"{y}_EQ"]:
            if candidate in lookup:
                found = lookup[candidate]
                break

        if found is None:
            # fallback por shortName
            for t212_t, ins in lookup.items():
                if str(ins.get("shortName", "")).upper() == y:
                    found = ins
                    break

        if found is None:
            missing.append(y)
            continue

        mapping[y] = {
            "t212": found.get("ticker", ""),
            "currency": found.get("currencyCode", "USD"),
            "name": found.get("name", y),
            "min_qty": float(found.get("minTradeQuantity", 0.01)),
            "precision": int(found.get("quantityPrecision", 2)),
        }

    with open(MAP_FILE, "w") as f:
        json.dump(mapping, f, indent=2)

    log.info(f"Mapeados {len(mapping)}/{len(universe)}. Em falta: {missing}")
    return mapping


def load_instrument_map() -> dict:
    if not MAP_FILE.exists():
        raise SystemExit("Sem u2_instrument_map.json. Corre: python3 u2_bot.py --map")
    with open(MAP_FILE) as f:
        return json.load(f)


def round_to_precision(quantity: float, precision: int) -> float:
    if precision < 0:
        precision = 2
    return float(np.floor(quantity * 10**precision) / 10**precision)


# ==============================================================================
# TAXA DE CÂMBIO
# ==============================================================================

def get_eurusd_rate() -> float:
    log.info("A obter taxa EURUSD...")
    try:
        data = yf.download(
            "EURUSD=X",
            period="5d",
            interval="1d",
            auto_adjust=True,
            progress=False,
        )
        if data is not None and not data.empty:
            close_data = data["Close"]
            if isinstance(close_data, pd.DataFrame):
                close_data = close_data.iloc[:, 0]
            if isinstance(close_data, pd.Series):
                fx = float(close_data.iloc[-1])
            else:
                fx = float(close_data)
            if 0.5 < fx < 1.5:
                log.info(f"EURUSD do Yahoo: {fx:.4f}")
                return fx
    except Exception as e:
        log.warning(f"Yahoo EURUSD falhou: {e}")

    try:
        import urllib.request

        with urllib.request.urlopen(
            "https://api.frankfurter.app/latest?from=EUR&to=USD",
            timeout=10,
        ) as response:
            fx = float(json.loads(response.read())["rates"]["USD"])
            log.info(f"EURUSD da Frankfurter: {fx:.4f}")
            return fx
    except Exception as e:
        log.warning(f"Frankfurter falhou: {e}")

    log.warning("A usar 0.92")
    return 0.92


# ==============================================================================
# MOMENTUM
# ==============================================================================

def compute_ranking(universe):
    tickers = universe + ["SPY"]
    log.info(f"A descarregar {len(tickers)} tickers Yahoo...")

    raw = yf.download(
        tickers,
        period="1y",
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    closes = {}
    for t in tickers:
        try:
            closes[t] = raw[t]["Close"]
        except Exception:
            log.warning(f"Sem dados Yahoo para {t}")

    close = pd.DataFrame(closes).dropna(how="all").ffill()

    if "SPY" not in close.columns:
        raise RuntimeError("SPY indisponível.")

    last_date = close.index[-1]
    if last_date.tz is None:
        last_date_utc = last_date.tz_localize("UTC")
    else:
        last_date_utc = last_date.tz_convert("UTC")

    age = (pd.Timestamp.now(tz="UTC").normalize() - last_date_utc.normalize()).days
    if age > MAX_DATA_AGE_DAYS:
        raise RuntimeError(f"Dados velhos: {last_date.date()} ({age} dias)")

    avail = [
        t for t in universe
        if t in close.columns and pd.notna(close[t].iloc[-1])
    ]
    if len(avail) < 30:
        raise RuntimeError(f"Só {len(avail)} tickers válidos.")

    rs = close[avail].div(close["SPY"], axis=0)
    mom = rs.pct_change(LOOKBACK).shift(SKIP).iloc[-1].dropna()
    mom = mom[np.isfinite(mom)]
    mom = mom[mom > 0].sort_values(ascending=False)

    fx = get_eurusd_rate()
    if fx <= 0 or not np.isfinite(fx):
        fx = 0.92

    log.info(f"EURUSD usada: {fx:.4f}")
    return mom, last_date, close.iloc[-1], fx


# ==============================================================================
# REBALANCE
# ==============================================================================

def run_monthly_rebalance():
    log.info("=" * 80)
    log.info("U2 MOMENTUM MONTHLY REBALANCE")
    log.info(
        f"BASE_URL={BASE_URL} | DRY_RUN={DRY_RUN} | "
        f"TOP_N={TOP_N} | LB={LOOKBACK} | SKIP={SKIP}"
    )
    log.info("=" * 80)

    if BASE_URL.startswith("https://live") and DRY_RUN:
        log.error("LIVE + DRY_RUN=True — a corrigir manualmente.")
        return

    state = load_state()
    now = datetime.now(timezone.utc)
    month_key = now.strftime("%Y-%m")

    if state.get("last_rebalance_month") == month_key:
        log.info(f"Já rebalanceado em {month_key}. Nada a fazer.")
        return
    if now.weekday() >= 5:
        log.info("Fim de semana: não rebalanceia.")
        return

    instrument_map = load_instrument_map()
    universe = list(instrument_map.keys())

    mom, signal_date, last_prices, fx = compute_ranking(universe)

    targets = [t for t in mom.index if t in instrument_map][:TOP_N]
    if len(targets) < MIN_NAMES:
        log.warning(f"Só {len(targets)} nomes com momentum > 0.")

    log.info(
        f"Sinal close {signal_date.date()} | "
        f"Momentum positivos: {len(mom)} | Targets: {targets}"
    )

    log.info("A ler cash e posições T212...")
    cash = get_account_cash()
    live_positions = get_t212_positions()

    t212_to_yahoo = {v["t212"]: k for k, v in instrument_map.items()}

    held_values = {}
    for t212_t, p in live_positions.items():
        y = t212_to_yahoo.get(t212_t)
        if not y:
            continue
        try:
            q = float(p["quantity"])
            px = float(p["currentPrice"])
        except Exception:
            continue
        if q > 0 and px > 0:
            held_values[y] = q * px

    invested = sum(held_values.values())
    equity = cash + invested
    log.info(
        f"Equity≈{equity:.2f} | Cash={cash:.2f} | "
        f"Invested≈{invested:.2f} | Held={list(held_values.keys())}"
    )

    # 1. Vender não-target
    for y, val in list(held_values.items()):
        if y in targets:
            continue

        t212_t = instrument_map[y]["t212"]
        qty = float(live_positions.get(t212_t, {}).get("quantity", 0.0))
        if abs(qty) <= 0:
            continue

        log.info(f"SELL {y:<6} ({t212_t}) qty={qty:.6f} val≈{val:.2f}")
        res = place_order(t212_t, -qty)

        if res:
            append_trade_log({
                "date": now.isoformat(),
                "month": month_key,
                "action": "SELL",
                "yahoo": y,
                "t212": t212_t,
                "quantity": -qty,
                "estimated_value": -val,
                "dry_run": DRY_RUN,
            })
            cash = get_account_cash() if not DRY_RUN else cash + val

    # 2. Comprar novas posições
    pending_buys = [y for y in targets if y not in held_values]
    SAFETY_MARGIN = 1.05

    for i, y in enumerate(pending_buys):
        if cash < 20:
            break

        t212_t = instrument_map[y]["t212"]
        precision = int(instrument_map[y].get("precision", 2))
        min_qty = float(instrument_map[y].get("min_qty", 0.01))

        if t212_t in live_positions:
            px = float(live_positions[t212_t]["currentPrice"])
        else:
            usd_px = float(last_prices[y])
            px = (usd_px / fx) * SAFETY_MARGIN

        if px <= 0:
            log.warning(f"Preço inválido para {y}. Skip.")
            continue

        remaining = len(pending_buys) - i
        desired = min(cash / remaining, cash * 0.98)

        raw_qty = desired / px
        quantity = round_to_precision(raw_qty, precision)

        if quantity < min_qty:
            log.info(f"SKIP {y:<6}: qty {quantity:.6f} < min {min_qty}")
            continue

        final_cost = quantity * px

        if final_cost > cash:
            raw_qty = (cash * 0.98) / px
            quantity = round_to_precision(raw_qty, precision)
            if quantity < min_qty:
                log.info(f"SKIP {y:<6}: qty recalculada {quantity:.6f} < min {min_qty}")
                continue
            final_cost = quantity * px

        log.info(
            f"BUY {y:<6} ({t212_t}) qty={quantity:+.6f} "
            f"px≈{px:.4f} EUR | custo≈{final_cost:.2f}"
        )

        res = place_order(t212_t, quantity)

        if res:
            append_trade_log({
                "date": now.isoformat(),
                "month": month_key,
                "action": "BUY",
                "yahoo": y,
                "t212": t212_t,
                "quantity": quantity,
                "estimated_value": round(final_cost, 2),
                "dry_run": DRY_RUN,
            })
            cash = get_account_cash() if not DRY_RUN else cash - final_cost

    # 3. Estado e telemetria
    cash_final = cash
    state["last_rebalance_month"] = month_key
    state.setdefault("history", []).append({
        "month": month_key,
        "signal_date": str(signal_date.date()),
        "targets": targets,
        "equity_before": equity,
        "momentum_top": mom.head(TOP_N).round(4).to_dict(),
    })
    save_state(state)

    append_telemetry({
        "date": now.isoformat(),
        "equity": round(equity, 2),
        "cash": round(cash_final, 2),
        "invested": round(equity - cash_final, 2),
        "targets": ",".join(targets),
        "dry_run": DRY_RUN,
    })

    log.info(f"Cash final: {cash_final:.2f}")
    log.info("Rebalance concluído.")
    log.info("=" * 80)


# ==============================================================================
# ESTADO / LOGS
# ==============================================================================

def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_rebalance_month": None, "history": []}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def append_trade_log(row):
    fields = [
        "date", "month", "action", "yahoo", "t212",
        "quantity", "estimated_value", "dry_run",
    ]
    is_new = not TRADES_CSV.exists()
    with open(TRADES_CSV, mode="a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if is_new:
            w.writeheader()
        w.writerow(row)


def append_telemetry(row):
    fields = [
        "date", "equity", "cash", "invested",
        "targets", "dry_run",
    ]
    is_new = not TELEMETRY_CSV.exists()
    with open(TELEMETRY_CSV, mode="a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if is_new:
            w.writeheader()
        w.writerow(row)


# ==============================================================================
# MAIN
# ==============================================================================

if __name__ == "__main__":
    if "--map" in sys.argv:
        build_instrument_map()
        sys.exit(0)

    if "--rank" in sys.argv:
        imap = load_instrument_map()
        universe = list(imap.keys())
        mom, d, _, fx = compute_ranking(universe)
        print(f"Sinal close {d.date()}:")
        print(mom.head(20).round(4))
        print(f"\nTaxa EURUSD: {fx:.4f}")
        sys.exit(0)

    try:
        run_monthly_rebalance()
    except Exception as e:
        log.exception(f"ERRO: {e}")
        sys.exit(1)