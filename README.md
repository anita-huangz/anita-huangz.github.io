# Anita Huang — Projects

**[View the project site →](https://anita-huangz.github.io/)**

[![The portfolio site](site/docs/screenshot.png)](https://anita-huangz.github.io/)

AI platform engineering, backend systems, and quantitative work. Everything
here lives in one repository, and every project marked ✅ runs its full test
suite offline in [CI](.github/workflows/ci.yml) — no network, no API keys —
across Python 3.11, 3.12, and 3.13.

**3,034 tests** — 2,262 in Python, 738 in the browser, and 34 against the API, most of them
cross-checking the site's TypeScript ports against fixtures the Python
generated. I've noted what each project gets wrong
as well as what it does, because the bugs are usually the more interesting
half.

---

## LLM Platform

### ✅ [Piano Arrangement Lab](llm-platform/piano-arrangement-lab) · 516 tests

Give it a chord chart; get back something a person can actually play, at the
difficulty you asked for, with its working shown.

**In** — a chord chart as text plus a difficulty, voicing style and tempo — or a
sentence like *"an easy jazzy version, slow"*, parsed without a model.
**Out** — a voicing per hand per chord, the cost and hand span of each, every
voice-leading rule broken, every simplification made to fit the level, and a
two-track MIDI file.

A chord symbol names pitch *classes* and never octaves, so `Cmaj7` is several
hundred ways two hands could play it — and the right one depends entirely on the
chord before it. That is a shortest path. Each chord contributes a layer of
candidate voicings with a static cost (hand span, muddy low intervals, missing
chord tones, register), and each adjacent pair carries a transition cost
(part-writing rules broken, hands moved, common tones held). Viterbi finds the
cheapest route exactly in `O(n·k²)` where trying every combination is `O(kⁿ)`.

- **Exactness is measured, not claimed** — against brute force on three-chord
  progressions the two agree exactly; against the greedy baseline that ships
  alongside it, greedy is **5.3%** worse at beginner, 9.6% at intermediate and
  **28.9%** at advanced over eight real progressions.
- **Difficulty is data, not an adjective** — hand span, notes per hand, register,
  whether inversions and extensions are allowed. Which is what makes it
  checkable: a test asserts no arrangement ever exceeds its own limits, across
  every progression, level and style.
- **The MIDI writer is 80 lines**, not a dependency, and the tests parse its
  output back rather than trusting the byte count.
- **The engine is ported to TypeScript** so the browser demo solves live, and the
  port is cross-checked against the Python across 120 combinations of
  progression, level and style — every voicing, every cost, every violation.

No API key needed for any of it. The optional model layer points at free tiers.

**Python · TypeScript · React · Web Audio · MIDI · pytest · vitest**

---

### ✅ [SEC Filing Intelligence](llm-platform/sec-filing-intelligence) · 410 tests

Ask a question about a public company and get an answer with every claim cited
to a specific SEC filing — then independently verified against the evidence that
produced it. Served as **both an HTTP API and an MCP server**.

**In** — a ticker and a plain-English question: `AAPL`, *"What supply chain
risks does Apple disclose?"*
**Out** — a cited answer plus structured findings, each carrying an accession
number and filing date, a verified/unverified verdict, and the run's token
count, dollar cost, and latency.

The agent writes a research plan, then calls up to four tools against SEC
EDGAR — listing filings, pulling a named section out of a 10-K, fetching
reported XBRL figures, measuring the price move after a filing date. A separate
verifier pass re-reads the gathered evidence and checks each citation actually
supports its claim before the answer is returned.

```
plan ─▶ research ⇄ tools ─▶ analyze ─▶ verify
```

- **Multi-provider model access** — Anthropic, AWS Bedrock, and a deterministic
  replay provider behind one interface. Nothing above the provider layer imports
  a vendor SDK, which is what lets CI exercise the whole agent graph with no key
  and no spend.
- **Citations are audited, not trusted** — a verifier node checks each finding
  against gathered evidence and can mark the answer unverified.
- **Bounded execution** — a hard tool-call ceiling plus least-privilege
  capability grants. Tools outside a grant are hidden from the model *and*
  refused if it asks anyway.
- **Telemetry** — tokens, estimated USD, latency percentiles, and failure kinds,
  sliced by model and tool. Cached reads bill at 0.1× the *input* rate, which is
  the usual way cost tables overstate spend.
- **Evaluation harness** — accuracy, consistency, reliability, latency, and cost
  measured separately, because they fail independently.
- **A React UI** that streams the agent's run over server-sent events as it
  happens.

`make demo` runs the whole stack against real SEC EDGAR with **no API key**.

**Python · FastAPI · MCP · Pydantic · LangGraph · Claude · AWS Bedrock · Redis ·
Docker · React · TypeScript**

---

## Systems

Things that run. Ordered by engineering complexity — interacting subsystems,
algorithmic depth, and how much the correctness depends on domain reasoning,
not on line count: the scheduler below has twice the tests of the cache and is
not twice the problem.

### ✅ [Trie Search](systems/trie-search) · 195 tests

Crawls a website, indexes every word into a trie, searches by prefix or
single-character wildcard — and **ranks** the results with BM25.

The index used to map each word to the *set* of pages containing it and return
that set alphabetically. That is retrieval without ranking: a page mentioning
"park" once and a park directory mentioning it nineteen times were
indistinguishable, and a two-word query had no way to prefer pages matching
both. BM25 needs three things the set could not provide — term frequency, page
length, and how many pages hold the term at all.

The subtle part is the IDF floor. Without `max(idf, 0)`, a term appearing on
more than half the pages scores *negative*, and a page improves its rank by
**not** matching the query.

`Trie.__iter__` yielded `(key, value)` tuples — and since `MutableMapping`
builds `keys()`, `values()`, and `items()` on top of `__iter__`, all three
raised and `dict(trie)` didn't work. The class claimed a contract it failed.

**Python · httpx · lxml · data structures**

### ✅ [Course Catalog & Scheduling](systems/course-catalog) · 190 tests

Reads the **live** MPCS catalog at
[mpcs-courses.cs.uchicago.edu](https://mpcs-courses.cs.uchicago.edu/) for any
quarter back to 2015-16, and **builds** a schedule rather than only checking
one. Filtering answers "what still fits?" The question a student asks is the
reverse: given these courses I need and these hours I refuse, what are my
options? That's a search.

The bundled CSV was a snapshot, so it went stale the moment the department
published a new quarter. Going live surfaced three things about the real
listing, each of which cost a wrong guess first — two weekly meetings are one
table cell split by `<br/>`, minutes are omitted when they're zero (the time
parser used to *reject* `6pm`, with a test asserting it), and **a quarter is
published before its times are set.** That last one breaks the solver:

> A course with no meeting time conflicts with nothing, occupies no day and
> leaves no gap — so it scores **zero**, which beats every real timetable. Left
> in, the "best schedule" for a partly-published quarter is the one that
> schedules nothing at all.

Winter 2026-27 is in exactly that state: thirty courses, no times. Unplaceable
courses are now excluded by default, the count is reported, and they stay
searchable.

Sections turned out to be the interesting part. `MPCS 55001-1` and
`MPCS 55001-2` are the same Algorithms course at two different times, so they
deliberately *don't* overlap — and `build_schedule`, which checked only times,
happily enrolled you in Algorithms twice under two different instructors.

The solver is branch-and-bound over sections, scoring preferences in one
interpretable unit — minutes of annoyance. Gaps are the subtle term: they are
**not** monotone, because inserting a class into an idle afternoon *reduces*
total gap time, so a bound that assumed gaps only grow would prune the
gap-filling schedule, which is usually the best one. On a 164-section catalog
the search goes from 137 seconds to 19 exhaustive, or 0.8s inside a node
budget; a test cross-checks the bound against brute force, because a pruning
bug that loses the optimum still hands you a plausible schedule.

It also reports whether its answer is *proven* optimal. "These are the 5 best"
and "these are the 5 best I had time to find" are different claims.

A meeting is a day plus a **half-open** interval, which is the whole conflict
rule: a class ending at 7:30 and one starting at 7:30 are back to back, not a
conflict. Prefix search was actually *substring* search, so `"530"` matched
`MPCS 53014-1` via digits in the middle of the number.

**Python · csv · interval logic**

### ✅ [fastcache](systems/fastcache) · 98 tests

An LRU cache decorator benchmarked against `functools`, plus a general `cached`
decorator with TTL expiry and a choice of eviction policy.

The original called `list.remove` on every cache hit — a linear scan on the one
path a cache exists to make fast. Across cache sizes 128 → 32,768 the
list-based hit path slows **8.7×** while this one stays flat at ~0.45µs.

`lru_cache` answers *has this been computed?* A service needs *has this been
computed recently enough?* Expiry needs no heap: every entry gets the same TTL,
so deadline order is insertion order and the next entry to die is the front of
the dict. An expired entry must not count as a hit — that inflates the number
people judge the cache by — and it still occupies capacity, so eviction takes a
dead entry before a live one.

The project also shipped one eviction policy with no evidence it was the right
one. It now measures LRU against LFU across five access patterns, and
**neither wins everywhere:**

| workload | LRU hit | LFU hit | winner |
|---|---:|---:|---|
| zipf (skewed) | 71.3% | 76.4% | LFU +5 pts |
| uniform (no locality) | 10.1% | 10.1% | tie |
| sequential scan | 0.0% | 0.0% | tie |
| hot set + scans | 14.3% | 24.9% | **LFU +11 pts** |
| shifting hot set | 96.4% | 10.7% | **LRU +86 pts** |

LFU keeps a stable hot set that scans would flush out of an LRU. But when the
hot set *moves*, the old keys carry counts the new ones can't reach — so a new
key is the least frequently used thing in the cache and is evicted immediately,
never cached at all. There's no decay, so it's permanent, and the benchmark
shows what that costs rather than hiding it.

**Python · threading · benchmarking**

### ✅ [Card Game](systems/card-game-system) · 137 tests

A single-player poker-style draw game — now with straights, and with an advisor
that tells you what to throw away.

**Straights were missing entirely,** which in a seven-card game is not a small
omission: a straight is *more likely* than a flush, so hands that should have
scored were scoring nothing and ending the run. Detecting one in seven cards
needs duplicates collapsed first (a pair inside the run otherwise reads as a
gap) and the ace valued at both ends without wrapping, so `A 2 3 4 5` counts
and `K A 2 3 4` doesn't. Straight flushes are checked **per suit**, because
"has a straight and has a flush" is a different question — `5♥ 6♦ 7♥ 8♠ 9♥ K♥
2♥` holds both and is neither.

The game used to ask for discards and give the player nothing to decide with.
The advisor values all 120 legal discards, enumerating exactly where that's
cheap (45 draws for one card, 990 for two) and sampling above it — and says
which. Options within combined sampling error of the leader are reported as
tied rather than ranked, because printing them 1st and 2nd would be reporting
noise as a finding.

Two earlier scoring bugs, both from testing for an *exact* count in a
seven-card hand: six- and seven-card flushes scored as nothing, and two triples
scored as three-of-a-kind rather than a full house.

**Python · rich · OOP**

## Quantitative Finance

Four projects about prices, and the discipline that separates a real edge from
a look-ahead bug. Ordered by complexity, most involved first.

The failure mode they share is that a mistake here does not look like a
mistake: it looks like a profitable strategy. A factor computed one day early,
weights chosen with knowledge of the returns they are scored on, a scaler
fitted on the test set — each turns a flat result into a spectacular one, and
none of them raises an error.

### 1. ✅ [Factor Portfolio Simulator](markets/factor-based-portfolio-simulator) · 105 tests

Point-in-time backtest of cross-sectional equity factor strategies, with
Fama-French 3-factor attribution — reported **against a benchmark**, because a
backtest that only quotes its own return cannot answer the first question
anyone asks.

Fixed a **look-ahead bias that overstated total return by 92 percentage
points** — factors were computed once from the entire sample and reused at
every rebalance, so the 2021 allocation was picked using 2024 returns.
[`examples/lookahead_demo.py`](markets/factor-based-portfolio-simulator/examples/lookahead_demo.py)
reproduces both loops over identical prices:

| | point-in-time | full-sample (bug) |
|---|---:|---:|
| total return | 2.85% | **95.43%** |
| Sharpe | 0.14 | **1.42** |

The report now carries beta, annualised alpha, tracking error, information
ratio and up/down capture against SPY; drawdown *periods* with peak, trough
and recovery dates, since a single max-drawdown number says nothing about time
underwater; and turnover annualised from the real rebalance cadence, so the
transaction costs it was already charging finally appear in the output. It also
flags the way a factor backtest flatters itself: the default strategy beats SPY
by 234 points while carrying 1.38× its market exposure, and says so.

**Python · pandas · NumPy · statsmodels · yfinance**

### 2. ✅ [Bitcoin Price Forecasting](markets/bitcoin-and-asset-trading) · 64 tests
The conclusion was right; none of the evidence for it was.

| forecast | RMSE | R²(returns) | directional |
|---|---:|---:|---|
| LSTM (honest) | 22,283 | **−206** | 49.0% [46%, 52%] |
| LSTM (as written) | 13,867 | −58 | 49.7% |
| naive | **1,401** | 0.0 | makes no call |

**Diebold-Mariano: DM = +18.03, p = 7.9e-63** — "16× worse" becomes a
hypothesis test with a HAC correction, because forecast errors on consecutive
days are correlated. RMSE on a *level* is a statement about the level: across
21 rolling origins the same forecaster scores **$5 in one fold and $2,076 in
another**. R² on returns is the real question, and predicting "no change"
scores exactly 0.

`MinMaxScaler` was fitted on the whole series before splitting, so **36.2% of
the scaled axis was territory training never reached** — the model was told how
high the price would eventually go. And AR(5) turns +158% into **+8%** once you
pay 30 bps to trade 291 times; nothing beats buy-and-hold.
**Python · NumPy · pandas · SciPy · TensorFlow**

### 3. ✅ [Stock-Bond Portfolio Optimisation](markets/stock-bond-portfolio-analysis) · 29 tests
Mean-variance allocation across five ETFs, evaluated **out of sample** and
against the benchmark that keeps winning.

| strategy | ann return | Sharpe | turnover |
|---|---:|---:|---:|
| **equal weight (1/N)** | **+6.50%** | 0.83 | 1.8% |
| risk parity | +4.98% | 1.13 | 5.7% |
| maximum Sharpe | +1.80% | **0.32** | 14.9% |

**1/N earns the most, and it's the only rule that estimates nothing** —
DeMiguel, Garlappi and Uppal (2009), reproduced. **Maximum Sharpe comes last
on the Sharpe ratio it optimises**, because expected returns can't be estimated
well enough to optimise against. In sample it reports **5.61**, a 17× collapse
— and the notebook reported the in-sample number. The mechanism is visible
directly: it rewrites 15% of the book every quarter chasing a sample mean.

Gone: `adjust_factor_weights_based_on_regression`, which multiplied a loading
by 1.5 above 0.5 and 1.2 above 0.2 — six unjustified constants.
**Python · NumPy · pandas · SciPy · scikit-learn (tests only)**

### 4. ✅ [Yield Curve Lab](markets/yield-curve-lab) · 209 tests

Nine Treasury tenors, 1981 to 2026. What the curve actually does, what a curve
trade is really exposed to, and whether any of it can be forecast.

**In** — a strategy in plain English: *"factor-neutral 1s2s5s since 2010,
weekly, 1bp"*, parsed by keyword into a range-checked config.
**Out** — the curve's factor decomposition, what share of a trade's risk sits in
each factor, a P&L backtest split into direction, carry, roll-down and cost, and
a walk-forward forecast scored against a random walk.

Three principal components on daily changes explain **95.1%** of every move the
curve made in forty-five years — level, slope and curvature, read off the
loadings rather than assumed.

- **The standard butterfly does not trade what it is named for.** A DV01-neutral
  2s5s10s fly puts **0.9%** of its risk in curvature; 99.1% is level and slope.
  The curvature factor's trough is at the 2-year, not the 5-year, so the fly is
  centred on that factor's zero crossing.
- **Placement beats weighting.** Solving for factor-neutral weights gets 100%
  curvature but loses DV01 neutrality. Just moving the fly to 1s2s5s gets
  **95.2%** with the plain 50-50 weights and stays DV01-neutral.
- **The return was never directional.** Over 2000–2026 the three flies earned
  −5, +16 and −1 dollars from direction, against 497–571 from carry. They are
  carry harvests with a curve view attached that contributed nothing.
- **66 features and gradient boosting lose to a random walk** at every factor —
  out-of-sample R² of −0.49 to −0.60, directional accuracy ~51%.
- **DuckDB, not Snowflake**, so it runs offline in CI with no credentials. The
  SQL ports; the setup cost does not.

**Python · DuckDB · SQL · XGBoost · scikit-learn · pandas · NumPy · SciPy · pytest**

---

### 5. ✅ [Earnings Drift Tracker](markets/earnings-drift-tracker) · 79 tests

Measures post-earnings-announcement drift against the size of the analyst
surprise — **as abnormal return**, not raw return, because a stock that rose 2%
in a week the market rose 2% did not drift.

Across 8 companies and 311 announcements the raw 10-day drift is +1.43% and the
market-adjusted drift is **+0.43%** — two thirds of the apparent effect was
just the market. The top-minus-bottom surprise quintile spread is +3.33%
(t = +2.18), significant but **not monotonic**, and the report says so rather
than quoting only the spread.

Announcements landing on a non-trading day now fall back to the prior session's
close; requiring an exact index match silently dropped a large and non-random
slice of events.

**Python · pandas · NumPy · REST APIs**

## Statistical Inference

Whether an effect is real, and how you would know. Ordered by complexity, most
involved first: depth of method, how much domain reasoning the result rests on,
and how easy it is to get quietly wrong. Each is an engineered, tested package;
the original notebooks are kept beside them, marked superseded, as the record
of what they replaced.

**Three of these five datasets are synthetic** — fake news (4,000 distinct
headlines collapse to one template once digits are stripped), cybersecurity
threats (every numeric column flat, every column independent of every other),
and e-commerce (the browsing field contains the purchase in 100% of rows).
Establishing that rigorously — permutation tests, power analyses, comparison
against a null — is most of the work in those projects. Showing that something
*isn't* there is harder than finding something that is.

### 1. ✅ [Customer Churn Prediction](inference/customer-churn-prediction) · 105 tests
Telco churn treated as what it actually is: **right-censored survival data
driving a spending decision**, not a binary score. 73.5% of these customers
hadn't left when the data was cut, so their lifetime is *at least* their
current tenure — and a classifier reads a one-month customer who stayed and a
six-year customer who stayed as the same row.

Kaplan-Meier, the log-rank test and Cox regression are implemented from
scratch and checked against statsmodels to 1e-8. **The median lifetime is
undefined, and that's the right answer** — more than half are still
subscribed, so it hasn't happened yet; the restricted mean says 46.8 of the
next 60 months. The Cox model reaches concordance **0.870** against the
classifier's 0.845 AUC, because it can see *when* people left. The
proportional-hazards assumption then fails for 16 of 20 covariates, which is
reported next to the hazard ratios rather than in a footnote.

Three bugs in the original notebook: `roc_curve(y_test_numeric, y_prob)`
referenced a variable assigned nowhere; eleven customers with a blank
`TotalCharges` were filled with the column mean, $2,283, when all eleven have
tenure 0 and the answer is exactly 0; and six one-hot columns were exact
duplicates of another column, leaving the design matrix at rank 21 of 27.

**The finding I didn't expect:** the data leak everyone names was worth
**+0.0002** of AUC. Reporting one lucky 80/20 split as an estimate was worth
**0.017**. And class rebalancing — SMOTE, which the notebook used — changed
the ranking by 0.0001 of AUC while making the probabilities twice too large
(calibration error 0.149 against 0.012). AUC can't see that, and it stops
being harmless the moment the score is multiplied by money:

| same budget of 1,000 calls | net |
|---|---:|
| rank by probability × value | **$61,496** |
| rank by probability | $46,317 |
| call everyone | $5,602 |
| call at random | $1,172 |

Ranking by value needs to know how long each customer *would* have stayed —
the area under their own survival curve, which a classifier cannot produce.
**Python · NumPy · pandas · scikit-learn · statsmodels (tests only)**

### 2. ✅ [Fake News Detection](inference/fake-news-detection) · 38 tests
A null result, established properly.

Every title is `Breaking News {i}`; every body is one sentence with the index
substituted. **Strip the digits and 4,000 distinct titles collapse to one** —
so the notebook's TF-IDF model was a model of the row number. That check is
three lines and now runs first.

The labels being random is harder to show:

```
observed AUC             0.5145
shuffled-label null      0.4991 ± 0.0120
95% of shuffles fall in  [0.4749, 0.5179]     p = 0.119

4,000 rows would detect AUC ≥ 0.526 at 80% power.
```

The permutation null has to be *simulated* — the null distribution of a
cross-validated AUC depends on sample size, fold count and overfitting capacity
in ways no formula captures. And the power analysis is what turns "we found
nothing" into **"there is nothing bigger than 0.526 to find"**.
**Python · scikit-learn · SciPy**

### 3. ✅ [E-commerce Recommendations](inference/personalized-recommendations-for-e-commerce) · 33 tests
A content-based recommender with **ranking metrics** and a leave-one-out
protocol.

| recommender | recall@5 | NDCG@5 |
|---|---:|---:|
| browsing (ORACLE) | **1.0000** | 0.6369 |
| different category | 0.2734 | 0.1609 |
| random | 0.2083 | 0.1234 |
| same category | 0.0232 | **0.0090** |

There is **no user-item interaction matrix** — purchase history is a list of
subcategory *names* — so collaborative filtering is undefined here, not merely
hard. Every customer's purchases sit in **distinct categories**, so holding one
out leaves a history entirely in other categories and "more of the same" ranks
the held-out item's category *last*: **14× worse than random**.

The oracle hits recall@5 = 1.0000 because browsing history names the answer for
all 10,000 customers. It's included to be seen doing that — a result that good
is a bug report.
**Python · NumPy · pandas**

### 4. ✅ [Cybersecurity Threat Analysis](inference/global-security-threats) · 30 tests
Six unsupervised methods, and the question that has to come first: **does this
dataset have any structure?**

All three numerics are indistinguishable from uniform (KS p = 0.42, 0.51,
0.80), the categories are equally likely, and the strongest association between
any pair of columns is a Cramér's V of 0.062. Every column is an independent
draw.

The clusters then fail three ways:

- silhouette **0.0796** against **0.0810** on independently shuffled columns —
  marginally *worse* than noise
- bootstrap stability **ARI 0.484** against the usual 0.75 bar
- **the gap statistic picks k = 1**, falling monotonically with k

That last one matters because it's the only criterion here that *can* say
"none" — silhouette and elbow plots are undefined at k = 1, which is why an
elbow plot of noise still has an elbow.

The two outlier detectors agree 4× more than chance, and that is **not**
validation: both rank distance from the centre of the same cloud, so they agree
on noise too.
**Python · scikit-learn · SciPy**

### 5. ✅ [Weather Trends & Forecast](inference/weather-trends-and-forecast) · 24 tests
The slope was never the problem. **The error bar was.**

OLS assumes independent residuals; temperature doesn't oblige, because a warm
year follows a warm year. The lag-1 residual correlation is significantly
positive in all six cities:

| city | lag-1 | effective n | OLS SE understated by |
|---|---:|---:|---:|
| Tokyo | +0.403 | 32/75 | **53%** |
| Reykjavik | +0.367 | 35/75 | 47% |
| London | +0.200 | 50/75 | 23% |

Three corrections that share no assumptions — Newey-West, a moving-block
bootstrap, and rank-based Mann-Kendall with Sen's slope — **all agree on the
slope; only OLS disagrees on the width.** Every city is warming, London fastest
at +0.244 °C/decade, and the year-to-year variation exceeds a decade of trend
everywhere, which is why nobody notices it from memory.

Gone: a synthetic `generate_dummy_legislation_influence` regressor, and a trend
fitted through 90 days of daily maxima, which measures the seasons.
**Python · NumPy · SciPy · statsmodels (tests only)**

## Data sources

Every analysis links its source in the site's project panel. The datasets:

| Project | Source |
|---|---|
| Churn | [Telco Customer Churn](https://www.kaggle.com/datasets/blastchar/telco-customer-churn) |
| Fake news | [Fake News Detection](https://www.kaggle.com/datasets/khushikyad001/fake-news-detection) |
| Threats | [Global Cybersecurity Threats 2015-2024](https://www.kaggle.com/datasets/atharvasoundankar/global-cybersecurity-threats-2015-2024) |
| E-commerce | [Personalized Recommendations](https://www.kaggle.com/datasets/suvroo/personalized-recommendations-for-e-commerce) |
| Bitcoin | [Bitcoin Historical Data](https://www.kaggle.com/datasets/mczielinski/bitcoin-historical-data) |
| Stock-bond | [Yahoo Finance](https://finance.yahoo.com/), [Kenneth French Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html), [FRED](https://fred.stlouisfed.org/) |
| Weather | [Open-Meteo ERA5](https://open-meteo.com/en/docs/historical-weather-api) |
| SEC platform | [SEC EDGAR](https://www.sec.gov/edgar/sec-api-documentation), Yahoo Finance |
| Factor sim / drift | [Yahoo Finance](https://finance.yahoo.com/) |
| Course catalog | [UChicago MPCS courses](https://mpcs-courses.cs.uchicago.edu/) |

## Repository layout

```
llm-platform/       infrastructure around language models
systems/            things that run: a cache, a crawler, a solver, a game
markets/            prices, backtests, and not fooling yourself with them
inference/          whether an effect is real, and how you would know
site/               the portfolio site (React + Vite)
.github/workflows/  CI and GitHub Pages deployment
```

The folders are named for what the work does rather than for a job title.
`inference/` is statistical inference — establishing whether a result holds —
not model serving.

Each engineered project is self-contained: its own `pyproject.toml`, its own
test suite, its own README explaining the design decisions and what was wrong
before.

## Running anything locally

Every Python project follows the same shape:

```bash
cd <project>
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
pytest -q
ruff check .
```

The portfolio site:

```bash
cd site && npm install && npm run dev
```

## Conventions

- **Pure logic is separated from I/O.** Computation modules don't print, fetch,
  or plot — which is what makes the arithmetic directly testable.
- **Tests run offline.** Network calls are faked at the transport layer
  (`httpx.MockTransport`) and model calls through a replay provider. No test
  needs a key or a connection.
- **Failures are typed and reported, not swallowed.** A bare
  `except: continue` makes a broken run look like an empty one.
- **Exit codes mean something.** `2` is the caller's mistake — a bad flag, a
  missing key, an unparseable input. `1` is the program's — something it tried
  and could not finish.
- **Coverage has a floor CI enforces.** Every project sets `fail_under` on
  branch coverage in its `pyproject.toml`, so a drop fails the build. The floors
  sit a couple of points under what each suite measures today: a ratchet against
  silent rot rather than a number to game.
- **READMEs state the limits.** Every project has a "notes" or "limits" section
  covering what it doesn't do and where the numbers shouldn't be trusted.
