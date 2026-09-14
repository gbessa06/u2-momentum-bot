#!/usr/bin/env python3
"""
U2 MOMENTUM -- Block Bootstrap de Robustez Estatística

Em vez de reportar um único CAGR/MaxDD/Sharpe pontual (que é apenas UM
caminho possível da história), este script reamostra a série de retornos
mensais da equity curve em blocos contíguos (preservando parte da
autocorrelação/regime que um bootstrap i.i.d. destruiria) e reconstrói
milhares de "histórias alternativas" da estratégia.

O output é uma distribuição -- não um número -- de CAGR, MaxDD e Sharpe,
reportada como intervalo de percentis (ex: 5%-95%). Isto responde à
pergunta: "quão sensível é o resultado reportado à sorte da sequência
temporal específica que calhou acontecer?"

USO:
    python3 monte_carlo_robustness.py --input u2_backtest_equity.csv

Requer o CSV gerado por backtest_u2_momentum.py (coluna 'equity' indexada
por data). Corre localmente -- não precisa de internet nem de re-simular
a estratégia.
"""
import argparse
import numpy as np
import pandas as pd

N_SIMS = 5000
BLOCK_MONTHS = 6          # preserva ~2 trimestres de regime por bloco
RNG_SEED = 42


def load_monthly_returns(path: str) -> pd.Series:
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    if "equity" not in df.columns:
        raise SystemExit("CSV precisa de uma coluna 'equity' (formato do backtest_u2_momentum.py).")

    equity = df["equity"].dropna()
    monthly = equity.resample("ME").last().dropna()
    rets = monthly.pct_change().dropna()
    rets = rets[np.isfinite(rets)]
    return rets


def block_bootstrap_paths(rets: np.ndarray, n_sims: int, block_size: int, seed: int) -> np.ndarray:
    """Devolve array (n_sims, n_months) de retornos mensais reamostrados em blocos."""
    n_months = len(rets)
    n_blocks = int(np.ceil(n_months / block_size))
    max_start = n_months - block_size

    rng = np.random.default_rng(seed)
    paths = np.empty((n_sims, n_blocks * block_size))

    for i in range(n_sims):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        blocks = [rets[s:s + block_size] for s in starts]
        paths[i] = np.concatenate(blocks)

    return paths[:, :n_months]


def path_metrics(monthly_rets: np.ndarray, months_per_year: int = 12) -> dict:
    equity = np.cumprod(1 + monthly_rets)
    years = len(monthly_rets) / months_per_year

    cagr = equity[-1] ** (1 / years) - 1 if equity[-1] > 0 else -1.0

    running_max = np.maximum.accumulate(equity)
    dd = (running_max - equity) / running_max
    max_dd = dd.max()

    mean_r = monthly_rets.mean()
    std_r = monthly_rets.std()
    sharpe = (mean_r / std_r) * np.sqrt(months_per_year) if std_r > 0 else 0.0

    return {"CAGR": cagr, "MaxDD": max_dd, "Sharpe": sharpe}


def summarize(paths: np.ndarray) -> pd.DataFrame:
    rows = [path_metrics(p) for p in paths]
    df = pd.DataFrame(rows)
    pct = df.quantile([0.05, 0.25, 0.50, 0.75, 0.95])
    pct.index = ["p5", "p25", "p50 (mediana)", "p75", "p95"]
    return pct


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="u2_backtest_equity.csv")
    parser.add_argument("--n-sims", type=int, default=N_SIMS)
    parser.add_argument("--block-months", type=int, default=BLOCK_MONTHS)
    parser.add_argument("--seed", type=int, default=RNG_SEED)
    args = parser.parse_args()

    rets = load_monthly_returns(args.input)
    n_months = len(rets)

    if n_months < args.block_months * 4:
        print(
            f"AVISO: só {n_months} retornos mensais disponíveis para blocos de "
            f"{args.block_months} meses -- os percentis abaixo têm incerteza elevada, "
            f"trata-os como indicativos, não como garantia."
        )

    print(f"Retornos mensais observados: {n_months} ({n_months/12:.1f} anos)")
    print(f"A correr {args.n_sims} simulações de block bootstrap (blocos de {args.block_months} meses)...")

    paths = block_bootstrap_paths(rets.values, args.n_sims, args.block_months, args.seed)
    summary = summarize(paths)

    observed = path_metrics(rets.values)

    print("\n" + "=" * 70)
    print("RESULTADO OBSERVADO (o único caminho histórico real):")
    print("=" * 70)
    print(f"CAGR={observed['CAGR']*100:6.2f}%   MaxDD={observed['MaxDD']*100:6.2f}%   Sharpe={observed['Sharpe']:5.2f}")

    print("\n" + "=" * 70)
    print(f"DISTRIBUIÇÃO BLOCK BOOTSTRAP ({args.n_sims} caminhos alternativos):")
    print("=" * 70)
    display = summary.copy()
    display["CAGR"] = (display["CAGR"] * 100).round(2)
    display["MaxDD"] = (display["MaxDD"] * 100).round(2)
    display["Sharpe"] = display["Sharpe"].round(2)
    display.columns = ["CAGR %", "MaxDD %", "Sharpe"]
    print(display.to_string())

    summary.to_csv("bootstrap_summary.csv")
    pd.DataFrame({"CAGR": [p for p in [path_metrics(p)["CAGR"] for p in paths]],
                  "MaxDD": [path_metrics(p)["MaxDD"] for p in paths],
                  "Sharpe": [path_metrics(p)["Sharpe"] for p in paths]}).to_csv("bootstrap_raw.csv", index=False)
    print("\nExportado bootstrap_summary.csv e bootstrap_raw.csv")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        raw = pd.read_csv("bootstrap_raw.csv")
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))

        axes[0].hist(raw["CAGR"] * 100, bins=60, color="#2563eb", alpha=0.85)
        axes[0].axvline(observed["CAGR"] * 100, color="#dc2626", linestyle="--", label="Observado")
        axes[0].set_title("Distribuição CAGR (block bootstrap)")
        axes[0].set_xlabel("CAGR %")
        axes[0].legend()
        axes[0].grid(alpha=0.3)

        axes[1].hist(raw["MaxDD"] * 100, bins=60, color="#dc2626", alpha=0.85)
        axes[1].axvline(observed["MaxDD"] * 100, color="#1e293b", linestyle="--", label="Observado")
        axes[1].set_title("Distribuição Max Drawdown (block bootstrap)")
        axes[1].set_xlabel("MaxDD %")
        axes[1].legend()
        axes[1].grid(alpha=0.3)

        plt.tight_layout()
        plt.savefig("bootstrap_distribution.png", dpi=120)
        print("Gráfico gravado em bootstrap_distribution.png")
    except ImportError:
        print("matplotlib não instalado -- corre 'pip install matplotlib' para o gráfico (opcional).")


if __name__ == "__main__":
    main()