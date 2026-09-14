# U2 Momentum: Nasdaq-100 Relative Momentum Bot

Bot de rebalanceamento mensal que aplica uma estratégia de **momentum relativo** sobre o universo Nasdaq-100, executada automaticamente na Trading212 via API.

## Estratégia

- **Universo**: constituintes do Nasdaq-100 (`nasdaq100.csv`, gerado por `gen_nasdaq100.py`).
- **Sinal**: momentum de cada ação relativo ao SPY: `(preço / SPY) ` ao longo de um lookback de 126 sessões, com skip dos últimos 21 dias (evita reversão de curto prazo / efeito momentum-crash imediato).
- **Seleção**: top 7 ações com momentum positivo, peso igual.
- **Execução**: rebalanceamento mensal via API da Trading212 (`DRY_RUN=True` por defeito, até manualmente posto em `False` apenas faz *paper trading*).
- **Câmbio**: conversão USD para EUR automática através do yfinance para distinguir o tamanho das ordens dependendo se o ticker é em EUR ou USD.

## Arquitetura

| Ficheiro | Função |
|---|---|
| `gen_nasdaq100.py` | Gera os tickers que atualmente constituem o *Nasdaq100*, guardado em `nasdaq100.csv` |
| `u2_bot.py` | Lógica de produção: acrescenta _US_EQ ao ticker Yahoo para ser compatível com o equivalente no T212, calcula ranking de momentum, executa rebalanceamento mensal, regista *trades* e telemetria |
| `backtest_u2_momentum.py` | *Backtest* histórico da estratégia vs. SPY/QQQ *buy-and-hold*, apresenta *CAGR, MaxDD, Sharpe ratio* e *Calmar ratio* para o período completo, *OOS (Out of Sample)* e *IS (In Sample)* |
| `monte_carlo_robustness.py` | *Block bootstrap* sobre a *equity curve* do *backtest*, quantifica a incerteza estatística à volta do *CAGR/MaxDD/Sharpe* reportados |

Modos de execução do `u2_bot.py`:
```bash
python3 u2_bot.py --map     # constrói o mapa de instrumentos
python3 u2_bot.py --rank    # mostra o ranking de momentum atual, sem operar
python3 u2_bot.py           # corre o rebalanceamento mensal
```

O `backtest_u2_momentum.py` aceita `--universe` para escolher o ficheiro do universo de tickers, o que torna os testes abaixo reproduzíveis a partir do seguinte script:
```bash
python3 backtest_u2_momentum.py --universe nasdaq100.csv      # Teste 1
python3 backtest_u2_momentum.py --universe universe_2012.csv  # Teste 2
```

## Resultados de Backtest

Dois backtests, sobre dois universos diferentes, cada um com diferentes utilidades de interpretação:

### 1) Nasdaq-100 atual (lista de hoje aplicada ao período de 2014-2026)

| | CAGR | MaxDD | Sharpe | Calmar |
|---|---|---|---|---|
| **U2 Momentum (completo)** | 37.97% | 48.14% | 1.05 | 0.79 |
| U2 Momentum (in-sample, <2022) | 49.31% | 33.44% | 1.29 | 1.47 |
| **U2 Momentum (out-of-sample, ≥2022)** | **23.11%** | 35.74% | 0.73 | 0.65 |
| SPY B&H | 13.76% | 33.72% | 0.83 | 0.41 |
| QQQ B&H | 19.16% | 35.12% | 0.92 | 0.55 |
| QQQ B&H (in-sample, <2022) | 22.51% | 28.56% | 1.10 | 0.79 |
| QQQ B&H (out-of-sample, ≥2022) | 13.65% | 34.83% | 0.67 | 0.39 |

### 2) 28 *mega-caps* fixas (universo estático de 2013)

| | CAGR | MaxDD | Sharpe | Calmar |
|---|---|---|---|---|
| **U2 Momentum (completo)** | 18.80% | 25.67% | 0.92 | 0.73 |
| **U2 Momentum (in-sample, <2022)** | **17.87%** | 25.67% | 0.89 | 0.70 |
| U2 Momentum (out-of-sample, ≥2022) | 20.30% | 21.56% | 0.95 | 0.94 |
| SPY B&H | 13.76% | 33.72% | 0.83 | 0.41 |
| QQQ B&H | 19.16% | 35.12% | 0.92 | 0.55 |
| QQQ B&H (in-sample, <2022) | 22.51% | 28.56% | 1.10 | 0.79 |
| QQQ B&H (out-of-sample, ≥2022) | 13.65% | 34.83% | 0.67 | 0.39 |

### Como interpretar os dois testes

Nenhum dos dois é um resultado viável visto que são dois testes com prós e contras diferentes:

- **Teste 1 (lista atual)** usa a composição de hoje do Nasdaq-100 aplicada a todo o período, isto introduz **survivorship bias** quanto aos resultados: as ações que sobrevivem para entrar na lista atual são, naturalmente, as que tiveram bom desempenho, o que infla o CAGR in-sample (49%). O período out-of-sample é o mais recente e o mais informativo sobre performance real esperada, mesmo assim não é realista pois é a lista de 2026 e não a lista correta de cada ano.
- **Teste 2 (28 mega-caps fixas de 2013)** não sofre da mesma maneira que o teste 1, o universo é fixo e conhecido antes do período testado, no entanto é um universo pequeno, e principalmente desatualizado, ao olhar somente para *mega-caps* obtém-se naturalmente um resultado mais estável, tanto em CAGR como em MaxDD, visto que não incluímos as ações vencedoras de cada período.

**Análise**: o teste 1 é mais robusto no período out-of-sample recente (mais parecido com as condições atuais de mercado), mas carrega mais survivorship bias, especialmente com o mercado em alta que o período participou. O teste 2 é mais limpo e no in-sample, mas usa um universo desatualizado. Ambos vencem o QQQ *buy-and-hold* no CAGR ajustado a Sharpe/Calmar na maioria dos períodos, mas o *max drawdown* da estratégia (25-48%) é elevado e deve pesar tanto quanto o CAGR na avaliação, e mais importantemente, mostra que a estratégia muda drasticamente baseado ao universo que está exposta. Nenhum destes números deve ser lido como retorno esperado garantido, são o resultado de dois testes imperfeitos.

## Robustez estatística: Block Bootstrap

Os números acima são **um único caminho histórico**. Para saber quão sensível o resultado é à sequência específica de meses que calhou acontecer, `monte_carlo_robustness.py` reamostra os retornos mensais da equity curve em **blocos de 6 meses**, esta quantidade de tempo foi escolhida pois preserva parte do regime que o periodo se apresenta que blocos mês-a-mês destruiria e reconstrói aleatoriamente milhares de histórias alternativas.

```bash
python3 backtest_u2_momentum.py --universe nasdaq100.csv   # gera u2_backtest_equity.csv
python3 monte_carlo_robustness.py --input u2_backtest_equity.csv
```

Output: percentis de CAGR, MaxDD e Sharpe sobre os caminhos reamostrado e um histograma (`bootstrap_distribution.png`). Isto responde à pergunta que um único backtest não responde: *"se a história tivesse uma ordem ligeiramente diferente, o resultado seria parecido ou foi sorte de sequência?"*

### Resultados (5000 simulações, blocos de 6 meses, 147 retornos mensais / 12.2 anos)

**Teste 1 (Nasdaq-100 atual)**

| | CAGR % | MaxDD % | Sharpe |
|---|---|---|---|
| Observado | 38.06 | 40.78 | 1.04 |
| p5 | 18.41 | 22.91 | 0.67 |
| p25 | 29.98 | 30.76 | 0.92 |
| p50 (mediana) | 38.78 | 37.06 | 1.08 |
| p75 | 48.15 | 43.60 | 1.24 |
| p95 | 63.34 | 56.23 | 1.46 |

**Teste 2 (28 mega-caps fixas (2013))**

| | CAGR % | MaxDD % | Sharpe |
|---|---|---|---|
| Observado | 18.85 | 21.79 | 0.95 |
| p5 | 12.00 | 14.48 | 0.67 |
| p25 | 16.12 | 18.37 | 0.86 |
| p50 (mediana) | 19.17 | 21.79 | 0.98 |
| p75 | 22.16 | 25.60 | 1.11 |
| p95 | 26.82 | 32.22 | 1.30 |

![Distribuição do bootstrap — Nasdaq-100 atual](bootstrap_nasdaq100.png)
![Distribuição do bootstrap — 28 mega-caps (2013)](bootstrap_megacaps.png)

**Análise:** em ambos os testes, mesmo o percentil 5, que é o cenário mais pessimista quanto à ordem, fica com CAGR positivo e acima do QQQ B&H, não há um único caminho reamostrado, em 5000 simulações, que aponte para prejuízo. Isto é evidência de que o resultado observado não depende de uma sequência de meses particularmente sortuda. Dito isto, o intervalo é largo entre o valor máximo e mínimo dos parâmetros, a estratégia, para obter melhor CAGR, também sofre maior MaxDD, o que é consistente com a teoria, se seguimos ações que são mais voláteis com maior possibilidade de retorno, temos maior chance dessa mesma volatilidade levar-nos abaixo. O Teste 2 tem intervalos mais estreitos e um Sharpe mediano semelhante ao QQQ, refletindo o universo mais pequeno, menos volátil e menos concentrado em poucos vencedores.

Com 12.2 anos de retornos mensais, o bootstrap tem as suas próprias limitações, não inventa dados novos, só quantifica a incerteza dentro do que já foi observado. Trata o intervalo p5-p95 como uma faixa plausível, não como garantia, e nota que ele **não corrige** o survivorship bias do Teste 1, que é um problema dos dados de entrada, não da reamostragem.

## Limitações conhecidas


- Survivorship bias no universo do Teste 1 (ver acima).
- Custos de transação modelados de forma simples: 5 bps por operação (compra e venda), sem modelar slippage nem spread. Na prática, para ações líquidas do Nasdaq-100 é uma aproximação razoável, mas otimista para nomes mais ilíquidos.
- Execução real depende da liquidez e do spread da Trading212 para os tickers específicos, não testado em produção com capital real além de dry-run/demo.
- O yfinance pode alterar dados históricos retroativamente (ajustes de dividendos/*splits*); resultados podem variar ligeiramente entre execuções do *backtest*.
- O universo de tickers tem que ser manualmente corrigido sempre que a composição do Nasdaq-100 mudar (`gen_nasdaq100.py` vai sempre para o fallback estático, logo esse teria que ser atualizado), ou o bot opera sobre uma lista desatualizada e perde o timing de novas entradas no índice.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt   # pandas, numpy, requests, yfinance, python-dotenv, beautifulsoup4, matplotlib

python3 gen_nasdaq100.py          # gera nasdaq100.csv
python3 u2_bot.py --map           # mapeia universo para tickers T212
python3 backtest_u2_momentum.py   # corre o backtest (default = nasdaq100.csv)
```

Cria um `keys.env` (não versionado, ver `.gitignore`) com:
```
T212_API_KEY=...
T212_API_SECRET=...
```

`DRY_RUN=True` por defeito em `u2_bot.py`, nenhuma ordem real é enviada sem alteração explícita do código, tal como o `BASE_URL` está por defeito direcionado para a conta demo do Trading212, nunca vai executar em live sem a alteração explícita do `BASE_URL` para o ambiente live.

## Disclaimer

Projeto pessoal com fins educativos e de portefólio. Não é aconselhamento financeiro. Performance passada (mesmo em backtest sem viés) não garante performance futura.