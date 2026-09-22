# Yield Curve Lab

The US Treasury curve is nine numbers a day. This works out what they actually
do, what a curve trade is really exposed to, and whether any of it can be
predicted.

```
$ curve-lab --section trade

WHAT A BUTTERFLY ACTUALLY TRADES
--------------------------------------------------------------------------
  construction                    level    slope  curvature   net DV01
  2s5s10s DV01-neutral           37.4%    61.7%      0.9%     +0.000
  2s5s10s factor-neutral          0.0%     0.0%    100.0%     +0.076
```

A 2s5s10s butterfly is the standard way to trade curvature. Weighted the
standard way, **0.9% of its risk is curvature.** The rest is level and slope —
the two things it was constructed to be immune to.

## Three shapes

Principal components on *daily changes* across 11,261 days, September 1981 to
September 2026:

```
  level      77.10%   cumulative 77.10%
  slope      14.17%   cumulative 91.27%
  curvature   3.86%   cumulative 95.13%

                3MO    6MO      1      2      3      5      7     10     30
  level       +0.25  +0.30  +0.33  +0.36  +0.37  +0.37  +0.37  +0.34  +0.29
  slope       -0.65  -0.47  -0.26  -0.01  +0.10  +0.21  +0.28  +0.29  +0.28
  curvature   +0.50  -0.06  -0.31  -0.44  -0.31  -0.07  +0.14  +0.27  +0.51
```

The names are read off the loadings, not assumed: the first component moves
every tenor the same way, the second pivots the ends against each other, the
third sets the wings against the belly.

Changes rather than levels, deliberately. PCA on levels mostly recovers the
fact that rates were 17% in 1981 and 4% now — the first component is then a
description of forty years of disinflation, not of how the curve moves.

## Why the textbook fly fails, and the one-line fix

Look at where the curvature factor actually bends. Its trough is at the
**2-year** (−0.44), not the 5-year (−0.07). A 2s5s10s fly puts its belly almost
exactly on that factor's zero crossing, so it barely touches the thing it is
named for — and because level and slope carry twenty times the variance, the
small residual exposures to *those* dominate its P&L.

Two different fixes, and they are not equally good:

| fly | level | slope | curvature |
|---|---|---|---|
| 2s5s10s, DV01-neutral | 37.4% | 61.7% | **0.9%** |
| 2s5s10s, factor-neutral | 0.0% | 0.0% | **100.0%** |
| 1s2s5s, DV01-neutral | 2.8% | 1.9% | **95.2%** |

Solving for weights that zero the level and slope exposures works perfectly, and
costs the DV01 neutrality the trade was sized for (+0.076 net). **Moving the fly
onto the 2-year instead gets 95.2% curvature with the plain 50-50 weights and
stays DV01-neutral.** Placement beats weighting.

## What the trade actually earned

Backtested 2000 to 2026, rebalanced monthly, half a basis point of cost per unit
of DV01 traded. Dollars per $1/bp of belly DV01:

| trade | total | IR | max DD | directional | carry | cost |
|---|---|---|---|---|---|---|
| 2s5s10s DV01-neutral | 47 | 0.07 | −229 | **−5** | 497 | −319 |
| 2s5s10s factor-neutral | 143 | 0.24 | −178 | **16** | 571 | −340 |
| 1s2s5s DV01-neutral | 176 | 0.21 | −139 | **−1** | 545 | −319 |

The directional column is what the position earned for being right about where
the curve went. Over twenty-six years it is **−5, +16 and −1 dollars** — noise.
Every dollar of return came from carry, and roughly two thirds of it went back
out in transaction costs.

That is the finding. These are not curve views that happened to earn carry;
they are carry harvests with a curve view attached that contributed nothing.

## Can the factors be forecast? No

```
level      at 5d: out-of-sample R2 -0.5958, directional accuracy 51.6%
slope      at 5d: out-of-sample R2 -0.5405, directional accuracy 50.3%
curvature  at 5d: out-of-sample R2 -0.4866, directional accuracy 52.3%
```

66 engineered features — every tenor's 1, 5, 21 and 63-day changes, its rolling
mean and volatility, and three spreads — into gradient boosting, walk-forward on
an expanding window. The baseline predicts **zero**, because a factor score is
already a change.

A negative R² means the model is worse than that baseline, and the paired test
on squared errors puts t at +25 to +28: it is not close, and it is not luck.
This is consistent with the backtest, which found no directional P&L to capture.

The one caveat worth stating: the forecasts overlap, so their errors are
autocorrelated and the t-statistic overstates significance. It does not matter
here — the sign is wrong, not just the magnitude — but it would if the result
were marginal.

## What the factor model is fitted on

The backtest above refits the PCA on the window it trades, so the weights use
only data a trader would have had. Fitting it once on all 45 years instead — the
obvious shortcut — is look-ahead, and on the factor-neutral 2s5s10s from 2000 it
is the difference between:

| factor model fitted on | total | IR | max drawdown |
|---|---|---|---|
| the 2000–2026 window | **+$143** | +0.24 | −$178 |
| all 45 years | **−$232** | −0.37 | −$299 |

Same trade, same data, same costs; the only difference is which curve taught the
weights. `--look-ahead` turns it on, and the browser demo has it as a checkbox so
you can watch the sign change.

## Regimes and cycles

K-means on curve *shapes* (each day standardised across tenors, so a 16% curve
and a 4% curve with the same slope cluster together) finds real structure:
silhouette 0.43 at k=4 against 0.30 for the same data with each tenor shuffled
independently, z = +31.

An FFT on the factor scores mostly does not:

```
level: strongest period 179 days, power 9.12 vs threshold 12.94 — nothing clears it
slope: strongest period 5 days, power 12.98 — clears it, but only just
curvature: strongest period 63 days, power 15.24 — clears it
```

The threshold is the tallest peak *white noise of the same length* produces,
at the 1−0.05/3 quantile because three factors are being tested at once. A
periodogram of pure noise is exponentially distributed, so the largest of a few
thousand bins is several times the mean by construction — reading the tallest
spike off one and calling it a cycle is the standard way to find a business
cycle in a random walk. The 63-day peak in curvature is about a quarter, which
is the Treasury refunding cycle; the 5-day one is a pixel above the line and
should not be traded.

## Running it as a service

The CLI answers one question at a time. The service answers them over HTTP, and
does one thing the browser demo on the portfolio site cannot: **refit the
walk-forward forecast on request**, for any window, factor and horizon. XGBoost
does not train in a browser, so there the grid is precomputed; here it is not.

```bash
make up          # everything in Docker, on http://localhost:8080
```

Three pieces, and each is there for a reason:

```
web/    React + Vite      the client
api/    Node + Express    cache, validation, fan-out, and it serves the client
src/    Python + FastAPI  the quant engine, and the only thing that computes
```

**The engine** holds the curve and does the maths. It is the same `curve_lab`
the CLI imports, so there is one implementation of a DV01 in this repo.

**The BFF** holds no domain logic at all — if it ever computes a DV01 there are
two implementations and they will drift. What it does:

- *Caches.* Every answer is a deterministic function of a committed file, so a
  repeated request is free. Measured: a backtest goes 0.64s → 0.6ms and a
  forecast 0.98s → 0.7ms. The cache is bounded and LRU, because the key space
  is every combination of legs, dates, rebalance and cost; and it reports its
  hit rate on `/api/health`, because a cache nobody measures is a memory leak
  with extra steps.
- *Validates at the edge.* A 90bp cost is a 400 from Node rather than a round
  trip and a stack unwind in Python. The bounds are the engine's bounds, so a
  request that passes here cannot fail validation there.
- *Fans out.* The overview page needs factors, the decomposition and a
  backtest: three engine calls issued together, one browser round trip.
- *Serves the client*, so there is no CORS in production.

Honest note on the shape: a single FastAPI service would also work and would be
one fewer thing to run. The BFF earns its place on the caching and the fan-out,
and those are measured above rather than asserted — but it is a real trade for
a second process.

```
GET  /api/health              engine status and cache hit rate
GET  /api/curve/summary       coverage per tenor, from DuckDB
POST /api/factors             PCA over a window
POST /api/trade               the risk decomposition
POST /api/backtest            P&L split by source
POST /api/carry               carry and roll-down per tenor
POST /api/forecast            walk-forward XGBoost, refit per request
POST /api/cycles              the FFT, against its noise threshold
POST /api/strategy/parse      plain English to the validated object
POST /api/overview            factors + trade + backtest in one round trip
```

Without Docker, three shells:

```bash
make serve   # the engine on :8000
make api     # the BFF on :8080
make web     # Vite on :5173, proxying /api to :8080
```

## The stack

```
src/curve_lab/
  service/       FastAPI over everything below
  data.py        loading, and refusing a curve with a hole in it
  warehouse.py   DuckDB: the long table, and features as window functions
  pca.py         level / slope / curvature, with the eigenvector signs pinned
  trades.py      par-bond DV01, and the two ways to weight a butterfly
  carry.py       carry and roll-down, kept apart from each other
  backtest.py    deterministic execution, P&L split by source
  risk.py        drawdown, information ratio, hit rate
  regimes.py     k-means on shapes, against a shuffled null
  spectrum.py    FFT, against a white-noise null
  predict.py     walk-forward XGBoost against a random walk
  intent.py      plain English to a validated config, no model
  cli.py         the command line above

api/src/         the Express BFF: cache, validation, fan-out
web/src/         the React client the BFF serves
```

**DuckDB, not Snowflake.** This has to run offline in CI with no credentials, and
a 30-day trial is not a foundation for something that should still work in a
year. The SQL is ordinary — window functions, a join, an `UNPIVOT` — so the
schema ports unchanged. What does not port is the setup cost, which is zero.

The warehouse is load-bearing rather than decorative: feature engineering over a
term structure is lags, rolling windows and cross-tenor differences, and
`ROWS BETWEEN 21 PRECEDING AND 1 PRECEDING` says what it means. Writing
`CURRENT ROW` there instead is the single easiest way to build a model that
looks brilliant and predicts nothing, and a test asserts it does not.

## Install and use

```bash
pip install -e ".[dev]"      # add [predict] for XGBoost alone
pytest -q                    # 209 tests

curve-lab                                    # every section
curve-lab --section trade
curve-lab --strategy "factor-neutral 1s2s5s since 2010, weekly, 1bp"
curve-lab --section backtest --look-ahead    # refit on everything, and see
```

The strategy sentence is parsed by keyword, not by a model, into a `Strategy`
whose every field is range-checked. Execution downstream only ever sees the
validated object, so it stays deterministic however the request was phrased —
and if a model layer is added it maps text to the *same* object, where the worst
a bad completion can do is fail validation.

```python
from curve_lab import load
from curve_lab.pca import fit_factors
from curve_lab.trades import factor_neutral_weights, residual_risk

curve = load()
factors = fit_factors(curve)
fly = factor_neutral_weights(factors, ("DGS2", "DGS10"), "DGS5")
print(residual_risk(fly, factors, factors.scores(curve.changes).var().to_numpy()).describe())
```

## The data, and the hole that is not in it

Nine constant-maturity tenors from FRED, committed as a 594 KB snapshot so
everything runs offline. `scripts/build_snapshot.py` regenerates it.

**The 20-year is excluded.** Treasury stopped issuing 20-year bonds at the end of
1986 and resumed in October 1993, and FRED's DGS20 has nothing in between.
Inner-joining it with the rest silently deletes 6.75 years and leaves two dates
sitting next to each other in the index that are **2,466 days apart** — after
which one row of carry gets booked across most of a decade. `load()` refuses any
curve with a gap over ten days for that reason, rather than leaving it as a
comment nobody reads.

**The 30-year is fine, despite the story.** Treasury suspended the bond between
2002 and 2006, but FRED's DGS30 carries a published long-term rate through the
suspension and only holidays are missing. Worth saying because the obvious
assumption — that it must have a gap too — would have it dropped for no reason.

## Notes and limits

- **Par-bond DV01, not a real bond.** Every position is priced as a par bond at
  the quoted constant-maturity yield. Real Treasuries trade away from par, carry
  specific repo, and the on-the-run issue is not the constant-maturity point.
  Directionally this is right and the level is approximate.
- **Roll-down uses linear interpolation in maturity.** Fine between adjacent
  quoted points, worst across the 10y–30y gap where the two anchors are twenty
  years apart. A proper job bootstraps a discount curve and prices the aged bond
  off it.
- **No financing.** Carry here is the coupon, with no repo cost subtracted. A
  real curve trade is funded, and in an inverted curve that funding is the
  difference between a profitable carry trade and an unprofitable one. The
  backtest's carry column is therefore an upper bound.
- **Costs are a flat half basis point per unit of DV01.** Real bid-offer varies
  by tenor, by issue, and by how much the market is moving; the 3-month bill and
  the 30-year bond do not trade at the same spread.
- **The factor model is refitted on the backtest window, and it matters.** An
  earlier version of this README asserted that fitting it on the whole sample
  "changes little". Measured, it does not: fitting on all 45 years and then
  trading only 2000 onwards takes the factor-neutral 2s5s10s from **+$143 to
  −$232**, a sign flip rather than a rounding difference. The curve of the early
  1980s was a different animal, and loadings fitted across both eras fit
  neither. The default is now the honest construction — weights use only the
  window being traded — and `--look-ahead` reproduces the other one, with a
  warning. An expanding-window refit would be better still and is not done.
- **95.1% is not 100%.** Three factors leave 4.9% of curve variance unexplained,
  and a trade reported as "100% curvature" is 100% of the part the model sees.
- **The FFT peaks are marginal and this is one dataset.** Two of three clear a
  corrected threshold, one of them by 0.04. That is a reason to look further, not
  a result.
