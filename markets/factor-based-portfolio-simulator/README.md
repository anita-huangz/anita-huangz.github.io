# Factor Portfolio Simulator

A point-in-time backtest of cross-sectional equity factor strategies: rank a
universe on value, momentum, size, and low-volatility signals, hold the top N,
rebalance on a fixed cadence, and attribute the result against Fama-French.

```
$ factor-sim --tickers AAPL,MSFT,GOOGL,AMZN,META,NVDA,AVGO,ORCL \
             --factors momentum,low_volatility --top-n 3 --cost-bps 5 --attribution

momentum + low_volatility | top 3 | equal-weighted
47 rebalances, $1,284.31 in costs

  total return       +62.41%
  annualized return  +13.09%
  volatility          24.87%
  Sharpe ratio         0.61
  max drawdown        31.44%
  trading days          1004

Fama-French 3-factor attribution:
  observations       1004
  alpha (daily)      +0.00012  (p = 0.611)
  Mkt-RF             +1.2841  (p = 0.000)
  SMB                -0.3107  (p = 0.001)
  HML                -0.5522  (p = 0.000)
  R-squared           0.694
```

## Install and run

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev,data]"
factor-sim --factors momentum --top-n 3
pytest -q      # 105 tests, no network
ruff check .
```

---

## The look-ahead bug this version fixes

The first version computed factor exposures **once, from the entire sample**, and
reused that single snapshot at every rebalance:

```python
factor_data['12M_Return'] = price_data.pct_change(252).iloc[-1]   # the LAST day
```

`.iloc[-1]` is the final day of the backtest. Every rebalance — including the
first one in 2021 — ranked stocks using returns measured through 2024. The
strategy was picking winners it had already seen win.

`examples/lookahead_demo.py` reproduces both loops over identical synthetic
prices, so the only difference is *when* the factors were measured:

```
                           point-in-time   full-sample (bug)
  total_return                    2.85%              95.43%
  annualized_return               0.95%              25.25%
  max_drawdown                   21.12%              16.91%
  sharpe_ratio                     0.14                1.42

  total return overstated by +92.6%
```

A flat strategy became a 95% winner with a 1.42 Sharpe. This is the single most
important property of the rewrite: `point_in_time_exposures(prices, as_of)`
slices `prices.loc[:as_of]` and cannot see past it, and a test asserts that the
same series produces different exposures at different dates.

```bash
python examples/lookahead_demo.py    # reproduce the table above
```

---

## What the report answers now

A backtest that only reports its own return cannot answer the first question
anyone asks: *was this better than just buying the index?* Three additions,
all in [`metrics.py`](src/factor_sim/metrics.py):

**Benchmark-relative performance** (`--benchmark SPY`, on by default). Beta,
annualised alpha, tracking error, information ratio, and up/down capture from a
regression of the strategy's daily returns on the benchmark's, over their shared
sessions only. A strategy up 300% while the market rose 400% lost money in the
only sense that matters, and total return alone hides that. The report also
flags the specific way a factor backtest flatters itself:

```
Versus SPY:
  strategy total     +337.71%
  SPY                +103.89%
  excess             +233.82%  (beat SPY over 1001 sessions)
  beta               1.38
  alpha (annual)     +15.05%
  information ratio  1.07
  up / down capture  1.53 / 1.38
  note: it beat SPY while carrying 1.38x its market exposure, so leverage
  explains part of the gap.
```

**Drawdown periods, not just a maximum.** A single max-drawdown figure says how
deep the worst loss was and nothing about how long it lasted — and time
underwater is what decides whether a strategy actually gets held. Each period
carries its peak, trough, and recovery date, and an open drawdown is reported as
open rather than silently closed at the sample's end:

```
    depth        peak      trough   recovered  days
   36.18%  2024-07-10  2025-04-08  2025-06-26  351
   18.12%  2026-05-14  2026-06-25     not yet  42+
```

**Turnover against the cost assumption.** Transaction costs were charged but
never reported, so a strategy could look good while its edge was eaten by
trading. One-way turnover is half the sum of absolute weight changes, annualised
from the actual rebalance cadence; at 5 bps a side the default strategy's 733%
annual turnover is a 0.73%/yr drag — worth knowing next to a 15% alpha.

---

## Other corrections

**Metrics were computed on five rows.** `run_simulation` ended with
`return nav_df.tail()`, and `main.py` passed that straight into
`performance_metrics`. Every figure in the old README — "portfolio grew from
$100,000 to ~$156,500, ~56% total return over 3 years" — actually described the
final week of the backtest. `run_backtest` now returns the complete NAV path.

**Score-proportional weighting broke on negative scores.** The optimizer
computed `weight = score / sum(scores)`. Factor scores are routinely negative —
z-scores are centred on zero, and the size factor is negative by construction —
so a negative denominator inverted every weight and produced short positions in
a long-only book. Weighting is now by rank.

**Factors were summed across incomparable units.** Inverse P/E is around 0.03; a
12-month return is around 0.4. Adding them let momentum dominate any combination
it appeared in, regardless of intent. Each factor is now cross-sectionally
z-scored before the sum.

**Cash was forced to zero on every rebalance.** `self.cash = 0` after allocating
meant any unallocated weight or transaction cost silently vanished from — or was
fabricated into — the portfolio value.

**Market cap was used raw in the size factor.** Caps span three orders of
magnitude, so one mega-cap dominated the cross-section. It is log-scaled now.

**`factor_based_portfolio.py` was a verbatim duplicate** of the four other
modules combined, and had already drifted out of sync with them. Deleted.

---

## Layout

```
src/factor_sim/
  factors.py       factor definitions, z-scoring, combination
  optimizer.py     scores -> weights
  portfolio.py     holdings, rebalancing, transaction costs
  simulation.py    point-in-time exposures and the backtest loop
  metrics.py       return, volatility, Sharpe, drawdown
  attribution.py   Fama-French 3-factor regression
  data.py          yfinance / yahooquery / Ken French loaders
  plotting.py      NAV and drawdown charts
  cli.py           argument parsing
examples/          the look-ahead demonstration
tests/             105 tests
```

Simulation does not plot, plotting does not simulate, and neither touches the
network. The whole test suite runs offline on synthetic price paths.

---

## Factors

| Name | Signal | Point-in-time? |
|---|---|---|
| `momentum` | 252-day trailing return | yes |
| `low_volatility` | 21-day realised vol, annualised, negated | yes |
| `value` | inverse trailing P/E | **no** — snapshot |
| `size` | negative log market cap | **no** — snapshot |

All four are oriented so higher is better, which is what makes the combination a
plain sum of z-scores.

**`value` and `size` are not point-in-time.** Free sources only expose
*current* fundamentals, so a historical rebalance would be scored with today's
P/E. That is the same class of bug fixed above, and it cannot be fixed without
a historical fundamentals feed. The CLI prints a warning when either is
requested; `momentum` and `low_volatility` are clean.

---

## Limits

- Daily closes only. No intraday fills, no slippage model beyond flat basis
  points, no borrow costs, no short side.
- Rebalance cadence is a fixed number of trading days, not calendar months.
- The universe is whatever tickers are passed in, so results carry whatever
  survivorship bias that selection has.
- Transaction costs are linear in traded notional, which understates the cost of
  large trades in thin names.
- Attribution uses the daily Fama-French research factors and reports
  heteroskedasticity-naive OLS standard errors.
