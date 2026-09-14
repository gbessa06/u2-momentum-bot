#!/usr/bin/env python3
"""
Gera nasdaq100.csv a partir de fontes online.

Tenta várias fontes:
1. stockanalysis.com
2. Wikipedia
3. Fallback estático embutido (nunca falha, mas pode ficar desatualizado)

Depois de gerar, os scripts `u2_bot.py` e `u2_backtest.py` usam o CSV local.
"""

import csv
import re
import sys

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}

# ── Fonte 1: stockanalysis.com ────────────────────────────────────────────────
def fetch_stockanalysis():
    url = "https://stockanalysis.com/list/nasdaq-100-stocks/"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Procura TODAS as tabelas e fica com a maior que tenha tickers válidos
    best = []
    for table in soup.find_all("table"):
        tickers = []
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) >= 2:
                sym = cells[0].text.strip().upper()
                if re.match(r"^[A-Z]{1,5}$", sym):
                    tickers.append(sym)
        if len(tickers) > len(best):
            best = tickers

    return best


# ── Fonte 2: Wikipedia ────────────────────────────────────────────────────────
def fetch_wikipedia():
    url = "https://en.wikipedia.org/wiki/Nasdaq-100"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    best = []

    # Pega QUALQUER tabela com a classe que contenha "wikitable"
    for table in soup.find_all("table", {"class": re.compile(r".*wikitable.*")}):
        tickers = []
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) > 1:
                t = cells[1].text.strip().split("[")[0].strip().upper()
                if re.match(r"^[A-Z]{1,5}$", t):
                    tickers.append(t)
        if len(tickers) > len(best):
            best = tickers

    return best


# ── Fallback estático (100 constituintes aproximados 2025) ──────────────────
FALLBACK_TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA",
    "COST", "NFLX", "AMD", "ADBE", "PEP", "CSCO", "TMUS", "INTC",
    "AMGN", "INTU", "CMCSA", "TXN", "QCOM", "HON", "AMAT", "BKNG",
    "ISRG", "VRTX", "MU", "MDLZ", "ADP", "SBUX", "PANW", "LRCX",
    "ADI", "REGN", "MELI", "GILD", "ASML", "KLAC", "SNPS", "CDNS",
    "CTAS", "FTNT", "MAR", "ORLY", "CSX", "PDD", "ABNB", "PYPL",
    "CHTR", "LULU", "PCAR", "NXPI", "ROP", "MNST", "DASH", "KDP",
    "WDAY", "ADSK", "MCHP", "CPRT", "ROST", "FAST", "ODFL", "BIIB",
    "IDXX", "EXC", "XEL", "EA", "TTWO", "WBD", "FANG", "MDB",
    "ZS", "DDOG", "CRWD", "PLTR", "TEAM", "DXCM", "CSGP", "AZN",
    "KHC", "MRNA", "PAYX", "BKR", "KMI", "ON", "GEHC", "CEG",
    "MRVL", "ARM", "LLY", "COST", "ABBV", "AMT", "CCI", "EQIX",
    "PEP", "KO", "INTU", "WFC", "SBAC",
]


def save_csv(tickers, source_name):
    # Remove duplicados preservando ordem
    seen = set()
    unique = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    with open("nasdaq100.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Ticker", "Company"])
        for t in unique:
            writer.writerow([t, ""])

    print(f"Gerado nasdaq100.csv com {len(unique)} tickers (fonte: {source_name}).")


def main():
    tickers = []

    # 1) Tenta stockanalysis
    for name, fn in [("stockanalysis", fetch_stockanalysis),
                     ("wikipedia", fetch_wikipedia)]:
        try:
            print(f"A tentar fonte: {name}...")
            tickers = fn()
            if len(tickers) >= 80:
                source = f"{name} (dinâmica)"
                break
        except Exception as e:
            print(f"  {name} falhou: {e}")

    # 2) Se nenhuma fonte dinâmica funcionar, usa fallback
    if len(tickers) < 80:
        print("Nenhuma fonte dinâmica funcionou; a usar fallback estático.")
        tickers = FALLBACK_TICKERS
        source = "fallback estático"

    save_csv(tickers, source)


if __name__ == "__main__":
    main()