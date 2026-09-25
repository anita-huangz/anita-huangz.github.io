import type { Project } from "./types";

/**
 * Every project in the repository. Terminal output in `output` is real -- it
 * was captured by running the project, not written by hand.
 */
export const PROJECTS: Project[] = [
  {
    "slug": "sec-filing-intelligence",
    "title": "SEC Filing Intelligence",
    "category": "llm-platform",
    "featured": true,
    "summary": "Ask a question about a public company and get an answer with every claim cited to a specific SEC filing \u2014 then independently verified against the evidence that produced it.",
    "detail": "You send a ticker and a question. The agent writes a research plan, then calls up to four tools against SEC EDGAR \u2014 listing filings, pulling a specific section out of a 10-K, fetching reported XBRL figures, measuring the price move after a filing date. It drafts findings with accession-number citations, and a separate verifier pass re-reads the gathered evidence and checks that each citation actually supports its claim before the answer is returned. Every model and tool call is metered, so each response carries its own token count, dollar cost, and latency.",
    "tech": [
      "Python",
      "FastAPI",
      "MCP",
      "Pydantic",
      "LangGraph",
      "Claude",
      "AWS Bedrock",
      "Redis",
      "Docker",
      "React",
      "TypeScript"
    ],
    "path": "llm-platform/sec-filing-intelligence",
    "tests": 410,
    "highlights": [
      "Multi-provider model access: Anthropic, AWS Bedrock, and a deterministic replay provider behind one interface, switched by config",
      "A verifier node audits every citation against gathered evidence and can mark the answer unverified",
      "Least-privilege capability grants plus a hard tool-call ceiling bound what the agent loop can reach and how long it runs",
      "Telemetry on every model and tool call: tokens, estimated USD, latency percentiles, failure kinds, sliced by model and tool",
      "An eval harness measuring accuracy, consistency, reliability, latency, and cost as separate numbers, because they fail independently",
      "A React UI that streams the agent's run over server-sent events as it happens"
    ],
    "images": [
      {
        "src": "sec-filing-light.png",
        "alt": "The research UI showing the agent's run timeline, quoted filing passages, and cost telemetry"
      }
    ],
    "io": {
      "input": "A ticker and a plain-English question \u2014 e.g. AAPL, \"What supply chain risks does Apple disclose?\"",
      "output": "A cited answer plus structured findings, each with an accession number and filing date, a verified/unverified verdict, and the run's token, cost, and latency figures.",
      "scale": "410 tests, all offline. Four tools, three model providers, one MCP server."
    },
    "sources": [
      {
        "label": "SEC EDGAR",
        "url": "https://www.sec.gov/edgar/sec-api-documentation",
        "note": "Company submissions, filing documents, and XBRL company facts."
      },
      {
        "label": "Yahoo Finance",
        "url": "https://finance.yahoo.com/",
        "note": "Daily closes, for measuring the price reaction to a filing."
      }
    ]
  },
  {
    "slug": "piano-arrangement-lab",
    "title": "Piano Arrangement Lab",
    "category": "llm-platform",
    "summary": "A chord chart in, a playable piano arrangement out, at the difficulty you ask for — solved as a shortest path through every way two hands could voice the chords, not looked up.",
    "detail": "A chord symbol names pitch classes and never octaves, so \"Cmaj7\" is several hundred ways two hands could play it, and the right one depends entirely on the chord before it: a lovely voicing that leaves the hand a tenth from the next chord is the wrong voicing. Written out that is a shortest path. Each chord contributes a layer of candidate voicings, each candidate carries a static cost (hand span, muddy low intervals, missing chord tones, register), and each pair across adjacent layers carries a transition cost (part-writing rules broken, hands moved, common tones held). Viterbi finds the cheapest route exactly in O(n·k²) where trying every combination is O(kⁿ). Against brute force on three-chord progressions the two agree exactly; against the greedy baseline that ships alongside it, greedy is 5.3% worse at beginner and 28.9% worse at advanced over eight real progressions. Difficulty is data rather than an adjective — hand span, notes per hand, register, whether inversions and extensions are allowed — which is what makes it checkable: a test asserts no arrangement ever exceeds its own limits across every progression, level and style.",
    "tech": [
      "Python",
      "TypeScript",
      "React",
      "Web Audio",
      "pytest",
      "vitest"
    ],
    "path": "llm-platform/piano-arrangement-lab",
    "featured": true,
    "rank": 1,
    "images": [
      {
        "src": "piano-light.png",
        "alt": "The arranger's keyboard with a B7 voicing lit \u2014 the left hand's B2 in orange, the right hand's F#3, A3, B3 and D#4 in blue \u2014 above the chord-by-chord table of hand positions, stretch and cost"
      }
    ],
    "io": {
      "input": "A chord chart as text, plus the difficulty, voicing style and tempo — or a sentence like \"an easy jazzy version, slow\", which is parsed without a model.",
      "output": "A voicing per chord for each hand, the cost and hand span of each, every voice-leading rule broken, every simplification made to fit the level, and a two-track MIDI file.",
      "scale": "516 Python tests and 514 in the browser. The engine is ported to TypeScript so the demo solves live, and the port is cross-checked against the Python across 120 combinations of progression, level and style — every voicing, every cost, every violation."
    },
    "sources": [
      {
        "label": "Standard MIDI File 1.0 specification",
        "url": "https://midi.org/standard-midi-files",
        "note": "The output format, written by hand in 80 lines rather than pulled in as a dependency."
      },
      {
        "label": "Groq / Google AI Studio free tiers",
        "url": "https://console.groq.com/",
        "note": "Where the optional model layer points. Both issue free keys; the arranger works fully without one."
      }
    ],
    "tests": 516,
    "highlights": [
      "Arrangement as a shortest path rather than a lookup: Viterbi over a lattice of candidate voicings, checked against brute force and beating the greedy baseline by 5.3% / 9.6% / 28.9% at the three difficulty levels",
      "Difficulty stated as enforceable numbers, so \"beginner\" is a promise a test can check rather than an adjective — and chords that cannot be played at a level are simplified with the reason shown, not swapped silently",
      "The AI layer never chooses a note. It fills in four validated fields, so a bad completion fails validation and falls back to the keyword parser — which is also why the demo works for every visitor with no API key",
      "Styles could once loosen hard constraints, so a \"jazzy\" beginner arrangement bought a fourth right-hand note; they can no longer touch the limits, and capping \"sparse\" at two notes turned out to make Dm7 unvoiceable because its root, third and seventh are three tones",
      "The MIDI header omitted its four-byte length field — a file of exactly the right size that no parser would open. Caught by parsing the output back rather than checking it was non-empty",
      "Keyword conflicts resolved by dictionary order rather than sentence order, so \"jazzy but gentle\" and \"gentle but jazzy\" gave the same answer, and the test that should have caught it passed for the same wrong reason",
      "A candidate cap of 60 measured as identical to 200 across all 120 corpus arrangements at seven times the speed; with two profiling fixes a seven-chord advanced arrangement went from 2.18s to 0.070s"
    ],
    "output": {
      "caption": "arrange \"Dm7 G7 Cmaj7\" --level beginner",
      "text": "  chord     left hand            right hand                     span   cost\n  -------------------------------------------------------------------------\n  Dm7       D3                   F4 C5 D5                          9   1.45\n  G7        G2                   F4 G4 B4                          6   7.85\n  Cmaj7     C3                   E4 B4 C5                          8   3.45\n\n  total cost 12.75   hand travel 13 semitones   widest stretch 9 semitones\n  92 transitions evaluated (exact, not greedy)\n\n  voice-leading notes:\n    G7: voice overlap — voice 4 falls to 71, below voice 3's 72"
    }
  },
  {
    "slug": "yield-curve-lab",
    "title": "Yield Curve Lab",
    "category": "markets",
    "summary": "Nine Treasury tenors over forty-five years \u2014 what the curve actually does, what a curve trade is really exposed to, and whether any of it can be forecast. The standard butterfly turns out to trade 0.9% curvature.",
    "detail": "Principal components on daily changes across 11,261 days recover level, slope and curvature, and three of them account for 95.1% of every move the curve made since 1981. That decomposition is then used to audit the trade built on it. A 2s5s10s butterfly weighted the textbook way \u2014 legs sized so the position has no net DV01 \u2014 is sold as a pure curvature bet, and 0.9% of its P&L variance is curvature; 37.4% is level and 61.7% is slope. The reason is placement: the curvature factor's trough sits at the 2-year, not the 5-year, so the conventional fly centres its belly almost exactly on that factor's zero crossing. Solving for factor-neutral weights gets 100% curvature and loses the DV01 neutrality it was sized for; simply moving the fly to 1s2s5s gets 95.2% with the plain 50-50 weights and keeps it. The backtest then asks what any of it earned: over 2000\u20132026 the three flies made \u22125, +16 and \u22121 dollars from direction against 497\u2013571 from carry, so they are carry harvests with a curve view attached that contributed nothing \u2014 which is consistent with 66 engineered features and gradient boosting losing to a random walk at every factor, out-of-sample R\u00b2 of \u22120.49 to \u22120.60.",
    "tech": [
      "Python",
      "DuckDB",
      "SQL",
      "XGBoost",
      "scikit-learn",
      "pandas",
      "NumPy",
      "SciPy",
      "pytest"
    ],
    "path": "markets/yield-curve-lab",
    "rank": 2,
    "tests": 209,
    "highlights": [
      "Three principal components on daily changes explain 95.1% of forty-five years of curve movement, with level, slope and curvature read off the loadings rather than assumed",
      "A DV01-neutral 2s5s10s butterfly carries 0.9% curvature risk and 99.1% level and slope \u2014 it does not trade the thing it is named for",
      "The curvature factor's trough is at the 2-year, so moving the fly to 1s2s5s gets 95.2% curvature from plain weights while staying DV01-neutral: placement beats weighting",
      "P&L is decomposed into direction, carry, roll-down and cost, which is what shows the directional component was worth \u2212$5 over twenty-six years",
      "66 features into walk-forward gradient boosting lose to a random walk at every factor, with a paired test on squared errors putting t at +25 to +28",
      "DuckDB carries the curve and builds features as SQL window functions, framed PRECEDING-to-1-PRECEDING so a rolling mean cannot see the day it sits on",
      "Plain-English strategy parsing into a range-checked config, so execution stays deterministic however the request was phrased"
    ],
    "io": {
      "input": "A strategy in plain English \u2014 e.g. \"factor-neutral 1s2s5s since 2010, weekly, 1bp\" \u2014 parsed by keyword into a validated configuration.",
      "output": "The curve's factor decomposition, each trade's risk split across level/slope/curvature, a backtest whose P&L is separated into direction, carry, roll-down and cost, and a walk-forward forecast scored against a random walk.",
      "scale": "209 tests, all offline. 11,261 days x 9 tenors, 1981 to 2026, in a 594 KB committed snapshot."
    },
    "sources": [
      {
        "label": "FRED \u2014 Treasury constant maturity rates",
        "url": "https://fred.stlouisfed.org/categories/115",
        "note": "Daily par yields per tenor. Free, no key. The 20-year is excluded: it has a 6.75-year issuance gap that an inner join would hide."
      }
    ]
  },
  {
    "slug": "earnings-drift-tracker",
    "rank": 4,
    "title": "Earnings Drift Tracker",
    "category": "markets",
    "summary": "Measures whether a stock keeps drifting in the direction of an earnings surprise, by pairing each announcement with the return over the days that followed.",
    "detail": "For each quarterly announcement it takes the gap between reported and estimated EPS, finds the last trading session on or before the announcement, and measures the cumulative return 1, 5, and 10 trading days later. Correlating surprise against drift is the question the project exists to ask. The answer is usually 'weakly, if at all' \u2014 which makes the data-handling choices the substance of it: announcements land on holidays and weekends, recent quarters have no 10-day window yet, and a zero consensus estimate makes the surprise percentage undefined rather than zero.",
    "tech": [
      "Python",
      "pandas",
      "NumPy",
      "REST APIs",
      "pytest"
    ],
    "path": "markets/earnings-drift-tracker",
    "tests": 79,
    "highlights": [
      "Announcements landing on a non-trading day fall back to the prior session's close; requiring an exact index match silently dropped a large, non-random slice of events",
      "A horizon with insufficient history is omitted rather than zero-filled, so a missing return is never read as a flat one",
      "A zero consensus estimate yields an undefined surprise percentage, not 0%, which would bias the correlation toward zero"
    ],
    "io": {
      "input": "A ticker and a date range.",
      "output": "One row per announcement \u2014 surprise percentage and forward returns at each horizon \u2014 plus the correlation between them.",
      "scale": "79 tests. The demo covers 62 companies and 1,959 real announcements."
    },
    "sources": [
      {
        "label": "Yahoo Finance",
        "url": "https://finance.yahoo.com/",
        "note": "Reported vs estimated EPS, and daily closes."
      },
      {
        "label": "Financial Modeling Prep",
        "url": "https://site.financialmodelingprep.com/developer/docs",
        "note": "The CLI's earnings-surprise source; needs a free API key."
      }
    ]
  },
  {
    "slug": "factor-based-portfolio-simulator",
    "rank": 1,
    "title": "Factor Portfolio Simulator",
    "category": "markets",
    "summary": "Backtests a cross-sectional factor strategy the honest way \u2014 scoring each stock only on information that existed on the rebalance date.",
    "detail": "Given daily closes for a universe of stocks, it ranks them at each rebalance on momentum and low-volatility signals computed strictly from prior data, buys the top N equally weighted, and tracks the resulting portfolio value day by day. It then regresses the daily excess returns on the Fama-French three factors to separate genuine alpha from market, size, and value exposure. The correctness question the whole project turns on is temporal: a factor computed even one day into the future turns a flat strategy into a spectacular one.",
    "tech": [
      "Python",
      "pandas",
      "NumPy",
      "statsmodels",
      "yfinance",
      "pytest"
    ],
    "path": "markets/factor-based-portfolio-simulator",
    "tests": 105,
    "highlights": [
      "Fixed a look-ahead bias that overstated total return by 92 percentage points -- factors were computed once from the whole sample and reused at every rebalance",
      "Performance metrics were being computed on the last five rows of the backtest while describing three years",
      "Score-proportional weighting inverted on negative scores, producing short positions in a long-only book",
      "examples/lookahead_demo.py reproduces the biased and corrected loops over identical prices"
    ],
    "output": {
      "caption": "examples/lookahead_demo.py \u2014 identical prices, the only difference is when factors were measured",
      "text": "                       point-in-time   full-sample (bug)\n  total_return                  2.85%              95.43%\n  annualized_return             0.95%              25.25%\n  max_drawdown                 21.12%              16.91%\n  sharpe_ratio                   0.14                1.42\n\n  total return overstated by +92.6%"
    },
    "io": {
      "input": "A list of tickers, a date range, which factors to use, how many names to hold, and how often to rebalance.",
      "output": "A daily NAV path, per-rebalance weights, total and annualized return, volatility, Sharpe, max drawdown, and a Fama-French attribution table.",
      "scale": "105 tests. The bundled demo runs 62 tickers over six years of real daily closes."
    },
    "sources": [
      {
        "label": "Yahoo Finance (via yfinance)",
        "url": "https://finance.yahoo.com/",
        "note": "Daily adjusted closes for the 62-name demo universe."
      },
      {
        "label": "Kenneth French Data Library",
        "url": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html",
        "note": "Daily Fama-French factors, for the attribution regression."
      }
    ]
  },
  {
    "slug": "fastcache",
    "rank": 3,
    "title": "fastcache \u2014 an O(1) LRU cache",
    "category": "systems",
    "summary": "A drop-in memoization decorator with O(1) lookup, insertion, and eviction, benchmarked against the standard library and against the list-based version it replaced.",
    "detail": "An LRU cache decorator with O(1) lookup, insert, and eviction, plus a general `cached` decorator adding TTL expiry and a choice of eviction policy. The benchmark harness measures the hit path against `functools.lru_cache` and the list-based version this replaced, and measures LRU against LFU across five access patterns \u2014 because neither policy wins everywhere, and shipping one with no evidence it was the right one was the gap.",
    "tech": [
      "Python",
      "threading",
      "pytest",
      "benchmarking"
    ],
    "path": "systems/fastcache",
    "tests": 98,
    "highlights": [
      "The original called `list.remove` on every cache hit -- a linear scan on the one path a cache exists to make fast. Across sizes 128 to 32,768 it slows 8.7x while this one stays flat at ~0.45us",
      "Expiry needs no heap: every entry gets the same TTL, so deadline order is insertion order and the next entry to die is the front of the dict",
      "An expired entry must not count as a hit, or the hit rate is inflated by entries that were discarded -- and it still occupies capacity, so eviction now takes a dead entry before a live one",
      "LFU wins the scan-flushes-a-hot-set workload by 11 points; LRU wins the shifting-hot-set workload by 86, because LFU never decays counts and so refuses to admit a new key at all",
      "Under LFU the entry just inserted can be the one evicted, and the code then read it back out of the cache"
    ],
    "output": {
      "caption": "LRU against LFU: 50,000 accesses over 2,000 keys, cache holds 200",
      "text": "workload                 LRU hit  LFU hit    winner\nzipf (skewed)              71.3%    76.4%   LFU +5\nuniform (no locality)      10.1%    10.1%      tie\nsequential scan             0.0%     0.0%      tie\nhot set + scans            14.3%    24.9%  LFU +11\nshifting hot set           96.4%    10.7%  LRU +86"
    },
    "io": {
      "input": "A function to memoise, a max size, optionally a TTL in seconds and a policy (`lru` or `lfu`).",
      "output": "A wrapped function plus hits, misses, evictions, expirations, and hit rate; the benchmark emits microseconds per call and hit rate by workload.",
      "scale": "98 tests. Benchmarked to 32,768 entries, and 50,000 accesses over 2,000 keys."
    }
  },
  {
    "slug": "trie-search",
    "rank": 1,
    "title": "Trie Search",
    "category": "systems",
    "summary": "Crawls a website, indexes every word it finds into a prefix tree, and answers prefix and single-character-wildcard queries against it.",
    "detail": "A breadth-first crawler walks a site to a given link depth, strips each page to its visible text, and folds every word into a trie. The trie answers which words look like the query \u2014 by prefix or single-character wildcard \u2014 and a BM25 scorer answers which pages those words make relevant, which the original set-valued index could not: a page mentioning a word once and a directory mentioning it nineteen times were indistinguishable. Each node has 27 children, one per letter plus a bucket for everything else, which is what turns a wildcard query into a bounded walk down the tree instead of a scan across every key.",
    "tech": [
      "Python",
      "httpx",
      "lxml",
      "data structures",
      "pytest"
    ],
    "path": "systems/trie-search",
    "tests": 195,
    "highlights": [
      "Search was retrieval without ranking: each word mapped to the set of pages holding it, returned alphabetically, with no way to prefer a page matching both words of a two-word query",
      "BM25's IDF needs a floor at zero -- a term on more than half the pages otherwise scores negative, and a page improves its rank by not matching the query",
      "A wildcard token expands to many terms, so requiring every term to be present would be wrong; the intent is every token, and the two coincide only when each token resolved to one term",
      "Trie.__iter__ yielded (key, value) tuples, which broke keys(), values(), items() and dict(trie) -- the class claimed a contract it failed",
      "Wildcard search matched '*' while every doc promised '?', so all documented examples returned nothing",
      "The visited-URL set was a module-level global, so the second crawl in a process returned nothing"
    ],
    "output": {
      "caption": "Ranked search over a five-page crawl",
      "text": "query 'park'\n  1  /parks-directory   0.650   park x19   82 words\n  2  /park-hours        0.573   park x4    32 words\n  3  /dog-park-rules    0.540   park x5    64 words\n  4  /about             0.422   park x3    86 words\n\n/park-hours beats /dog-park-rules on fewer mentions:\n4 in 32 words is denser than 5 in 64."
    },
    "io": {
      "input": "A start URL and a link depth, then a query: words, `par*` for a prefix, `d?g` for a wildcard.",
      "output": "Pages ranked by BM25, each showing its score and which terms matched how many times. Plus a report of pages that could not be fetched.",
      "scale": "195 tests, no network. Crawl is capped by depth, page count, and a URL allowlist."
    }
  },
  {
    "slug": "card-game-system",
    "rank": 4,
    "title": "Card Game",
    "category": "systems",
    "summary": "A single-player poker-style draw game: you are dealt seven cards, discard up to five, and the resulting hand is scored \u2014 score nothing and the run ends.",
    "detail": "Deals seven cards, takes your discards, draws replacements, and evaluates the hand against an eight-tier table from a pair up to a straight flush. Scoring reads all seven cards rather than the best five, which is where the edge cases live: a flush needs five of a suit anywhere in the hand, two triples make a full house, a pair inside a run does not break the run, and the ace plays both high and low without wrapping. A Monte Carlo advisor then values all 120 legal discards \u2014 enumerating exactly where that is cheap, sampling above it \u2014 and reports which options are indistinguishable rather than ranking noise.",
    "tech": [
      "Python",
      "rich",
      "OOP",
      "pytest"
    ],
    "path": "systems/card-game-system",
    "tests": 137,
    "highlights": [
      "Straights and straight flushes were missing entirely, and a straight is more likely than a flush -- hands that should have scored were ending the run",
      "\"Has a straight and has a flush\" is not a straight flush: 5h 6d 7h 8s 9h Kh 2h holds both and is neither, so the search runs per suit",
      "Six- and seven-card flushes scored as nothing: `5 in suit_counts.values()` is False when you hold six of a suit",
      "Two separate triples scored as three-of-a-kind rather than a full house, worth 100 instead of 250",
      "Dealing from an empty deck returned None, which entered the hand and crashed later in scoring, far from the cause"
    ],
    "output": {
      "caption": "The advisor on four to a royal flush, holding a pair",
      "text": "holding A\u2665 K\u2665 Q\u2665 J\u2665 7\u2663 7\u2660 2\u2666 -> Pair\n  1. discard 7\u2663, 7\u2660, 2\u2666      534.6 pts (\u00b1136), scores 93.0%\n  2. discard 7\u2663, 7\u2660          309.6 pts (exact), scores 84.5%\n  3. discard 7\u2663, 2\u2666          308.9 pts (exact), scores 82.7%\n  5. discard 2\u2666              176.7 pts (exact), scores 100.0%"
    },
    "io": {
      "input": "Your discard choices each round, up to five of the seven cards -- or a hand typed as `Ah Kh Qh Jh 7c 7s 2d` for the advisor to analyse.",
      "output": "A hand rank and points per round with a running total, plus the expected value of every legal discard, labelled exact or sampled.",
      "scale": "137 tests. 120 discards evaluated per recommendation: 45 draws enumerated for one card, 990 for two, sampled above that."
    }
  },
  {
    "slug": "course-catalog",
    "rank": 2,
    "title": "Course Catalog & Scheduling",
    "category": "systems",
    "summary": "Reads the live University of Chicago MPCS catalog for any quarter, then builds the best conflict-free timetable from it \u2014 rather than only checking one you already wrote down.",
    "detail": "Fetches the real course listing from mpcs-courses.cs.uchicago.edu for any quarter back to 2015-16, then answers the question a filter cannot: given the courses you need and the hours you refuse, what are your options? A branch-and-bound search returns the best conflict-free schedules, scoring preferences in one interpretable unit \u2014 minutes of annoyance. Sections are alternatives, not additions: two sections of one course are the same course at two times, so picking which one is most of the value and no filter over the catalogue can do it. The search also reports whether its answer is proven optimal or merely the best it had time to find.",
    "tech": [
      "Python",
      "httpx",
      "csv",
      "interval logic",
      "pytest"
    ],
    "path": "systems/course-catalog",
    "tests": 190,
    "highlights": [
      "The bundled CSV was a snapshot, so it went stale the moment the department published a new quarter -- it now reads the live catalog, and a script regenerates the offline snapshot",
      "A quarter is published before its meeting times are set. Winter 2026-27 went up with all 30 courses and no times -- and a course with no time conflicts with nothing, so it scores zero and beats every real timetable. Left in, the best schedule is the one that schedules nothing",
      "`build_schedule` checked times and nothing else, and two sections of one course deliberately do not overlap -- so it enrolled you in Algorithms twice, under two different instructors",
      "The time parser rejected `6pm` as malformed, with a test asserting it. The real listing writes `Monday 6pm - 8pm` beside `Monday 5:30pm - 8:30pm`, so it was dropping real courses",
      "Two weekly meetings are one table cell split by `<br/>`; stripping tags first glues `3:20pm` to `Thursday` and parses as nothing",
      "Gaps are not monotone: inserting a class into an idle afternoon reduces total gap time, so a bound that assumed gaps only grow would prune the gap-filling schedule, which is usually the best one",
      "Prefix search was actually substring search, so `\"530\"` matched `MPCS 53014-1` via the digits in the middle of the number"
    ],
    "output": {
      "caption": "Four courses from the live Autumn 2026-27 listing, nothing before 10am, Friday and the weekend free",
      "text": "32 course(s) from Autumn 2026-27, live from the department.\n1 best schedule(s) of 4, cheapest first:\n\n1. MPCS 50101-1, MPCS 51046-1, MPCS 52060-1, MPCS 53001-1\n  cost 125\n    Mon  14:30-17:20 MPCS 52060-1, 17:30-19:30 MPCS 50101-1\n    Wed  14:00-17:00 MPCS 51046-1, 17:00-19:30 MPCS 53001-1\n    why: extra_days 120, gaps 5\n\nsearched 11,400 nodes"
    },
    "io": {
      "input": "A quarter (`2026-27/winter`, or `current`), plus either a search -- code prefix, keyword, day -- or a request: how many courses, which are required, which days to keep free, nothing before a given time.",
      "output": "Matching courses, or the best conflict-free schedules ranked by cost with the penalty that drove each, how many courses were set aside for having no published time, the nodes searched, and whether optimality was proven.",
      "scale": "190 tests, all offline: the real listing pages are saved as fixtures and the transport is faked. 48 quarters available live; a 30-course quarter searches in a few hundred nodes."
    },
    "sources": [
      {
        "label": "UChicago MPCS course catalog",
        "url": "https://mpcs-inforstems.uchicago.edu/",
        "note": "A 30-course snapshot, bundled with the package as CSV."
      }
    ]
  },
  {
    "slug": "bitcoin-and-asset-trading",
    "title": "Bitcoin Price Forecasting",
    "category": "markets",
    "summary": "An LSTM against a one-line baseline, evaluated properly. No forecast here carries usable information about price changes, and the ones that look like they might are destroyed by transaction costs.",
    "detail": "The notebook reported RMSE on the price level from one 80/20 split. RMSE on a level is dominated by the level \u2014 across 21 rolling origins the same forecaster scores $5 in one fold and $2,076 in another \u2014 so R-squared on returns asks the real question, and the LSTM scores -206 where predicting no change scores zero. \"16x worse than naive\" becomes a Diebold-Mariano test with a Newey-West correction: DM = +18.03, p = 7.9e-63. It also quantifies the scaler leak, since MinMaxScaler was fitted on the whole series before splitting, so the training data was normalised using an all-time high that had not happened yet.",
    "tech": [
      "Python",
      "NumPy",
      "pandas",
      "SciPy",
      "TensorFlow",
      "pytest"
    ],
    "path": "markets/bitcoin-and-asset-trading",
    "rank": 2,
    "io": {
      "input": "Daily bars, plus the protocol: rolling-origin window size, transaction cost in basis points, and which section to run.",
      "output": "RMSE, return R-squared and directional accuracy with Wilson intervals for each forecast; Diebold-Mariano tests between them; per-fold spread across 21 origins; and net return at 0, 10 and 30 bps against buy-and-hold.",
      "scale": "4,825 daily bars reduced once from a 127 MB minute file and committed as 230 KB. 64 tests, none needing TensorFlow."
    },
    "sources": [
      {
        "label": "Bitcoin Historical Data (Kaggle)",
        "url": "https://www.kaggle.com/datasets/mczielinski/bitcoin-historical-data",
        "note": "Minute-resolution BTC/USD trades, resampled to daily bars."
      }
    ],
    "tests": 64,
    "highlights": [
      "MinMaxScaler was fitted on the whole series before the split, so 36.2% of the scaled axis was territory training never reached and the model looks 1.61x better than it is",
      "RMSE on a price level is a statement about the price level: across 21 rolling origins the same forecaster scores $5 in one fold and $2,076 in another",
      "R-squared on returns is the metric that exposes a level-tracking model -- predicting no change scores exactly zero and the LSTM scores -206",
      "49.0% directional accuracy has a 95% interval of [46%, 52%], which is a coin flip however the point estimate reads",
      "The naive forecast abstains rather than failing -- it predicts no change -- so scoring it as 0% directional would report the random walk at zero accuracy",
      "AR(5) turns +158% into +8% once you pay 30 bps to trade 291 times, and nothing beats buy-and-hold's +398%",
      "The drift signal is long on 100% of days, so its 53% directional accuracy is not timing anything",
      "total_return divided by equity.iloc[0], which is already 1 + r_0, discarding the first day's return"
    ],
    "output": {
      "caption": "The saved LSTM against tomorrow-equals-today",
      "text": "  forecast                RMSE   R2(returns)       directional\n  LSTM (honest)         22,283       -206.38   49.0% [46%,52%]\n  LSTM (as written)     13,867        -58.53   49.7% [47%,53%]\n  naive                  1,401          0.00      makes no call\n\n  Diebold-Mariano: DM = +18.03, p = 7.9e-63\n  -> the better forecast is the naive one."
    }
  },
  {
    "slug": "fake-news-detection",
    "title": "Fake News Detection",
    "category": "inference",
    "summary": "A null result, established properly: this dataset contains no learnable signal, and the analysis says how much that rules out.",
    "detail": "Every title is `Breaking News {i}` and every body is one sentence with the index substituted, so 4,000 distinct titles collapse to a single skeleton once the digits are stripped \u2014 a TF-IDF model over that is a model of the row number. The labels are random, which is harder to show: a permutation test refits on shuffled labels and the observed 0.5145 AUC sits inside the null's 95% range, p = 0.119. A power analysis then says 4,000 rows would detect AUC >= 0.526 at 80% power, which turns \"we found nothing\" into \"there is nothing bigger than this to find\".",
    "tech": [
      "Python",
      "NumPy",
      "pandas",
      "scikit-learn",
      "SciPy",
      "pytest"
    ],
    "path": "inference/fake-news-detection",
    "rank": 2,
    "io": {
      "input": "The dataset, plus the number of label permutations to run.",
      "output": "Template detection per text column, cross-validated AUC for two model families, the permutation null with its p-value and floor, the minimum detectable effect at 80% power, a learning curve, and per-feature tests with a Benjamini-Hochberg correction.",
      "scale": "4,000 rows, 24 columns. 38 tests, most of them paired against planted data."
    },
    "sources": [
      {
        "label": "Fake News Detection (Kaggle)",
        "url": "https://www.kaggle.com/datasets/khushikyad001/fake-news-detection",
        "note": "4,000 rows. Synthetic: titles are 'Breaking News N' and labels appear randomly assigned."
      }
    ],
    "tests": 38,
    "highlights": [
      "4,000 distinct titles collapse to one skeleton once the digits are stripped: the text column is the row index in prose",
      "The permutation test is the load-bearing evidence, and the null distribution of a cross-validated AUC has to be simulated rather than looked up -- its spread depends on sample size, fold count and the model's capacity to overfit",
      "A power analysis turns \"we found nothing\" into \"there is nothing bigger than 0.526 to find\", which is the stronger claim and the one a reader needs",
      "A permutation p-value of (hits + 1) / (draws + 1) means 10 draws cannot produce a significant result however large the effect -- the package refuses fewer than 19",
      "Every test runs against synthetic data with a planted effect, because a null result is only credible if the method would have found something",
      "The label's correlation with row order is +0.008, so the file is shuffled -- had it been sorted, a text model would have scored well by reading the number"
    ],
    "output": {
      "caption": "The permutation test, and what the sample rules out",
      "text": "  title[0]: 'Breaking News 1'   4,000 distinct -> 1 skeleton\n\n  observed AUC             0.5145\n  shuffled-label null      0.4991 +/- 0.0120\n  95% of shuffles fall in  [0.4749, 0.5179]\n  z = +1.28,  p = 0.119\n  -> the real labels are NOT distinguishable from random ones.\n\n  4,000 rows would detect AUC >= 0.526 at 80% power."
    }
  },
  {
    "slug": "customer-churn-prediction",
    "title": "Customer Churn Prediction",
    "category": "inference",
    "summary": "Telco churn treated as what it actually is \u2014 right-censored survival data driving a spending decision \u2014 rather than a binary score. Kaplan-Meier, the log-rank test and Cox regression from scratch, checked against statsmodels.",
    "detail": "73.5% of these 7,043 customers had not left when the data was cut, so their lifetime is not \"no churn\" but *at least* their current tenure \u2014 and a classifier reads a one-month customer who stayed and a six-year customer who stayed as the same row. Survival analysis uses them properly: the median lifetime turns out to be undefined (more than half are still subscribed), the restricted mean says 46.8 of the next 60 months, and the Cox model reaches a concordance of 0.870 against the classifier's 0.845 AUC on the same rows. It then turns the score into a decision, because a churn model retains nobody: the optimal cut-off given a $30 offer is 0.25 rather than 0.5, and ranking by probability \u00d7 value returns 33% more than ranking by probability for the same budget \u2014 which needs expected remaining months, something only the survival model has.",
    "tech": [
      "Python",
      "NumPy",
      "pandas",
      "scikit-learn",
      "statsmodels",
      "pytest"
    ],
    "path": "inference/customer-churn-prediction",
    "rank": 1,
    "io": {
      "input": "The Telco CSV, plus the campaign economics: cost per offer, acceptance rate, margin, and horizon -- all arguments, because none of them can be read off the dataset.",
      "output": "Survival curves with confidence bands, hazard ratios with intervals and an assumption test, cross-validated AUC with bootstrap intervals, calibration error, and the expected value of every targeting threshold.",
      "scale": "7,043 customers, 73.5% censored. 105 tests; statsmodels is a test dependency only, used to check the from-scratch estimators to 1e-8."
    },
    "sources": [
      {
        "label": "Telco Customer Churn (Kaggle)",
        "url": "https://www.kaggle.com/datasets/blastchar/telco-customer-churn",
        "note": "7,043 customers; the notebook drops 11 rows with blank TotalCharges."
      }
    ],
    "tests": 105,
    "highlights": [
      "The dataset is right-censored survival data and the notebook treated it as binary classification, discarding the timing information entirely -- the Cox model's concordance (0.870) beats the classifier's AUC (0.845) on the same rows",
      "Class rebalancing -- SMOTE, which the notebook used -- changed the ranking by 0.0001 of AUC and made the probabilities twice too large: calibration error 0.149 against 0.012 unweighted. AUC cannot see it, and it matters the moment a score is multiplied by money",
      "The leak everyone names was worth +0.0002 of AUC. Reporting one lucky 80/20 split as an estimate was worth 0.017, and 0.8617 sits outside the interval cross-validation supports",
      "`roc_curve(y_test_numeric, y_prob)` referenced a variable assigned nowhere in the notebook -- ruff reports F821 twice, plus three undefined `np`",
      "Eleven customers with a blank TotalCharges were filled with the column mean, $2,283. All eleven have tenure 0: they have never been billed, so the answer is exactly 0 and it is derivable",
      "Six one-hot columns were exact duplicates of another column (\"No internet service\" is the same 1,526 customers as InternetService=No), leaving the design matrix at rank 21 of 27 and the Cox Hessian singular",
      "The proportional-hazards assumption fails for 16 of 20 covariates, so the hazard ratios are time-averages -- reported next to the table rather than in a footnote"
    ],
    "output": {
      "caption": "Survival, and the same budget spent three ways",
      "text": "  S( 6 months) = 0.885   95% CI [0.877, 0.892]\n  S(24 months) = 0.789   95% CI [0.778, 0.799]\n  S(60 months) = 0.664   95% CI [0.650, 0.678]\n  median lifetime: never reached inside the window\n  concordance 0.870  vs classifier AUC 0.845\n\n  same budget of 1,000 calls:\n    by_expected_value    $61,496\n    by_probability       $46,317\n    everyone             $ 5,602\n    random               $ 1,172"
    }
  },
  {
    "slug": "global-security-threats",
    "title": "Cybersecurity Threat Analysis",
    "category": "inference",
    "summary": "Six unsupervised methods, and the question that has to come first: does this dataset have any structure to find? It does not.",
    "detail": "An unsupervised method has no ground truth to be wrong against \u2014 k-means returns k clusters whatever you hand it, and a projection of independent noise still looks like a cloud with edges. So the structure is tested first: all three numeric columns are indistinguishable from uniform on their own range, the categories are equally likely, and the strongest association between any pair of columns is a Cramer's V of 0.062. The clusters then fail three ways \u2014 silhouette is marginally *worse* than on independently shuffled columns, bootstrap stability is ARI 0.484 against the usual 0.75 bar, and the gap statistic picks k = 1.",
    "tech": [
      "Python",
      "NumPy",
      "pandas",
      "scikit-learn",
      "SciPy",
      "pytest"
    ],
    "path": "inference/global-security-threats",
    "rank": 4,
    "io": {
      "input": "The incident CSV, plus k and the number of null draws.",
      "output": "Kolmogorov-Smirnov and chi-square tests per column, pairwise associations, silhouette against a shuffled-column null, bootstrap cluster stability, the gap statistic across k, and detector agreement against its chance baseline.",
      "scale": "3,000 incidents, 10 columns, 39 encoded features. 30 tests, each paired against planted structure."
    },
    "sources": [
      {
        "label": "Global Cybersecurity Threats 2015-2024 (Kaggle)",
        "url": "https://www.kaggle.com/datasets/atharvasoundankar/global-cybersecurity-threats-2015-2024",
        "note": "3,000 incidents across 7 industries and 6 attack types."
      }
    ],
    "tests": 30,
    "highlights": [
      "All three numerics are indistinguishable from uniform (KS p = 0.42, 0.51, 0.80) where real loss figures are heavy-tailed, and the strongest association between any pair of columns is a Cramer's V of 0.062",
      "Silhouette on the real data is 0.0796 against 0.0810 on independently shuffled columns -- marginally worse than noise, and the shuffle keeps every marginal exactly while destroying only the joint structure",
      "The gap statistic picks k = 1 and falls monotonically with k. It is the only criterion here that *can* say \"no clusters\": silhouette and elbow plots are undefined at k = 1, so an elbow plot of noise still has an elbow",
      "The two outlier detectors agree four times more than chance -- which is not validation, because both rank distance from the centre of the same cloud and so agree on noise too",
      "One categorical column of seven clears p<0.05, against 0.35 expected by chance; reporting that as imbalance is the mistake the check exists to prevent",
      "A permutation p-value of (hits + 1) / (draws + 1) means 10 draws cannot reach significance however large the effect -- found when a planted three-cluster structure reported \"not better than noise\""
    ],
    "output": {
      "caption": "The clusters, judged against a null",
      "text": "  silhouette on the real data            0.0796\n  silhouette on independently shuffled   0.0810 +/- 0.0015\n  z = -0.90,  p = 0.810   -> better than noise: False\n\n  bootstrap stability (ARI)   0.484 [0.144, 0.919]  reproducible: no\n\n  gap statistic: k=1 -0.2779, k=2 -0.3140, k=3 -0.3376, k=4 -0.3581\n  -> chooses k = 1; there are no clusters."
    }
  },
  {
    "slug": "personalized-recommendations-for-e-commerce",
    "title": "E-commerce Recommendations",
    "category": "inference",
    "summary": "A content-based recommender with ranking metrics and a leave-one-out protocol \u2014 where the obvious content rule turns out to be 14x worse than random, by construction.",
    "detail": "There is no user-item interaction matrix: purchase history is a list of subcategory names and product IDs appear nowhere in the customer table, so collaborative filtering is undefined rather than merely hard. What the data supports is content-based recommendation over the 24 shared subcategories, scored leave-one-out with recall@k, MAP, MRR and NDCG. Every customer's purchases sit in distinct categories, so holding one out leaves a history entirely in other categories and \"more of the same\" ranks the held-out item's category last. Browsing history, meanwhile, names the answer exactly and reaches recall@5 of 1.0000.",
    "tech": [
      "Python",
      "NumPy",
      "pandas",
      "pytest"
    ],
    "path": "inference/personalized-recommendations-for-e-commerce",
    "rank": 3,
    "io": {
      "input": "The two tables, plus the cut-off k for the ranking metrics.",
      "output": "recall@k, precision@k, MAP, MRR and NDCG for six recommenders including random, popularity and a deliberate oracle, with the count of customers excluded.",
      "scale": "10,000 customers and 10,000 products over 24 subcategories. 33 tests; every metric checked against a hand-computed value."
    },
    "sources": [
      {
        "label": "Personalized Recommendations for E-Commerce (Kaggle)",
        "url": "https://www.kaggle.com/datasets/suvroo/personalized-recommendations-for-e-commerce",
        "note": "Two 10,000-row tables: customer behaviour and product catalogue."
      }
    ],
    "tests": 33,
    "highlights": [
      "No user-item interaction matrix exists, so collaborative filtering is undefined here -- and the notebook's regression target, Probability_of_Recommendation, correlates with nothing else in the table (max |r| = 0.017)",
      "Every customer's purchases sit in distinct categories, so the obvious content rule ranks the held-out item's category last: NDCG 0.0090 against random's 0.1234",
      "Browsing history covers a purchased category for all 10,000 customers, so a recommender given it reaches recall@5 = 1.0000 -- the answer arriving through a different column",
      "A recommender receives a Context with visible and browsing as separate fields, so reading the leaky column is a visible choice rather than an accident of scope",
      "Popularity ties with random, because 24 near-uniform subcategories have no popular head -- so \"we beat popularity\" would mean nothing here",
      "A third of customers have one purchase and cannot be evaluated at all; they are excluded and counted rather than the sample quietly shrinking"
    ],
    "output": {
      "caption": "Leave-one-out ranking over 6,631 evaluable customers",
      "text": "  recommender             recall@5     prec@5     MAP@5     MRR   NDCG@5\n  random                    0.2083     0.0417    0.0959  0.1582   0.1234\n  popularity                0.2000     0.0400    0.0916  0.1541   0.1182\n  same category             0.0232     0.0046    0.0046  0.0746   0.0090\n  different category        0.2734     0.0547    0.1244  0.1918   0.1609\n  browsing (ORACLE)         1.0000     0.2000    0.5164  0.5164   0.6369"
    }
  },
  {
    "slug": "stock-bond-portfolio-analysis",
    "title": "Stock-Bond Portfolio Optimisation",
    "category": "markets",
    "summary": "Mean-variance allocation across five ETFs, evaluated out of sample and against the benchmark that keeps winning: 1/N.",
    "detail": "The notebook optimised on a training period and reported the resulting portfolio's statistics \u2014 which describe a portfolio chosen with knowledge of the returns it is then scored on. A rolling backtest where the estimation window only ever precedes the holding period, with transaction costs, reproduces DeMiguel, Garlappi and Uppal (2009): equal weighting earns +6.50% a year against maximum Sharpe's +1.80%, and maximum Sharpe comes last on the Sharpe ratio it optimises \u2014 0.32 against 1/N's 0.83 \u2014 because expected returns cannot be estimated well enough to optimise against. In sample it reports 5.61, a 17x collapse. The mechanism is visible directly: it rewrites 15% of the book every quarter chasing a sample mean, against 1/N's 1.8%.",
    "tech": [
      "Python",
      "NumPy",
      "pandas",
      "SciPy",
      "scikit-learn",
      "pytest"
    ],
    "path": "markets/stock-bond-portfolio-analysis",
    "rank": 3,
    "io": {
      "input": "Adjusted daily closes for five ETFs, plus the protocol: estimation window, rebalance cadence, transaction cost in basis points -- all arguments, because all of them change the answer.",
      "output": "Annualised return, volatility, Sharpe, max drawdown, turnover and cost drag for each allocation rule, out of sample and in sample side by side, plus weight instability per rebalance.",
      "scale": "4,201 trading days, 2010-2026. 29 tests; Ledoit-Wolf shrinkage cross-checked against scikit-learn."
    },
    "sources": [
      {
        "label": "Yahoo Finance (via yfinance)",
        "url": "https://finance.yahoo.com/",
        "note": "Daily adjusted closes for SPY, IWM, TLT, LQD and SHV. The generator fetches to the current day, so the demo\u0027s window widens on every run."
      },
      {
        "label": "Kenneth French Data Library",
        "url": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html",
        "note": "Fama-French factor returns."
      },
      {
        "label": "FRED",
        "url": "https://fred.stlouisfed.org/",
        "note": "Interest-rate and liquidity indicators."
      }
    ],
    "tests": 29,
    "highlights": [
      "The reported result was in-sample: optimised on the whole history and scored on the same history. Maximum Sharpe reports 5.61 there and 0.32 out of sample, a 17x collapse, while 1/N moves from 0.88 to 0.83 because it has no parameters to overfit",
      "1/N earns the most out of sample and is the only rule that estimates nothing -- DeMiguel, Garlappi and Uppal (2009), reproduced on five ETFs",
      "Minimum variance's Sharpe of 6.37 is an artefact: it holds a short-Treasury ETF at 100% and has almost no volatility to divide by. Read its +1.61% return instead",
      "`adjust_factor_weights_based_on_regression` multiplied a factor loading by 1.5 above 0.5 and 1.2 above 0.2 -- six unjustified constants -- and `normalize_client_weights` iterated factor names while indexing the result as asset names",
      "average_turnover compared consecutive target weights, so it reported 1/N as never trading; the book drifts between rebalances and returning to a fixed target costs 1.8% a quarter, so every cost drag was understated",
      "The shrinkage estimator divided by n while sample_covariance divided by n-1, leaving the shrunk diagonal disagreeing with the sample variance by n/(n-1)"
    ],
    "output": {
      "caption": "Out of sample, 504-day window, quarterly rebalance, 5 bps",
      "text": "  strategy                ann ret      vol  Sharpe     maxDD   turnover\n  equal weight (1/N)       +6.50%    8.02%    0.83     22.6%       1.8%\n  risk parity              +4.98%    4.39%    1.13     13.9%       5.7%\n  maximum Sharpe           +1.80%    6.09%    0.32     20.0%      14.9%\n  minimum variance         +1.61%    0.25%    6.37      0.4%       1.5%\n\n  in sample, maximum Sharpe reports a Sharpe of 5.61."
    }
  },
  {
    "slug": "weather-trends-and-forecast",
    "title": "Weather Trends & Forecast",
    "category": "inference",
    "summary": "Warming rates for six cities over 75 years \u2014 and the part the original scripts got wrong, which is not the slope but the error bar around it.",
    "detail": "Ordinary least squares assumes independent residuals and temperature does not oblige: a warm year follows a warm year. The lag-1 residual correlation is significantly positive in all six cities, so the effective sample is smaller than the row count \u2014 Tokyo's 75 years are worth about 32 \u2014 and the naive standard error is understated by 23% to 53%. Three corrections that share no assumptions agree: Newey-West, a moving-block bootstrap, and Mann-Kendall with Sen's slope. All four methods agree on the slope; only OLS disagrees on the width. Every city is warming, London fastest at +0.244 C/decade.",
    "tech": [
      "Python",
      "NumPy",
      "pandas",
      "SciPy",
      "statsmodels",
      "pytest"
    ],
    "path": "inference/weather-trends-and-forecast",
    "rank": 5,
    "io": {
      "input": "Annual mean temperature by city, plus which city to examine and how many bootstrap draws.",
      "output": "Sen slope with a distribution-free interval for every city, four trend estimates side by side with their standard errors and intervals, and autocorrelation diagnostics giving the effective sample size.",
      "scale": "Six cities, 75 annual means each, reduced once from ERA5 daily reanalysis and committed as 14 KB. 24 tests; OLS and Newey-West checked against statsmodels."
    },
    "sources": [
      {
        "label": "Open-Meteo ERA5 archive API",
        "url": "https://open-meteo.com/en/docs/historical-weather-api",
        "note": "Hourly reanalysis by latitude and longitude. The README also cites Meteostat; the code calls Open-Meteo."
      }
    ],
    "tests": 24,
    "highlights": [
      "The lag-1 residual correlation is significantly positive in all six cities, so the OLS standard error is understated by 23% to 53% -- Tokyo's 75 years are worth about 32 independent ones",
      "Three corrections that share no assumptions land in the same place: Newey-West, a moving-block bootstrap, and rank-based Mann-Kendall with Sen's slope",
      "The block bootstrap resampled temperatures against a fixed time axis, scrambling the trend out of the series: it returned [-0.11, +0.11] around a point estimate of +0.235, a null distribution rather than a sampling distribution",
      "A fixed Durbin-Watson cut-off of 1.5 called London uncorrelated at DW 1.576, when the 5% bound for 75 observations is above that -- the critical value depends on the sample size",
      "The year-to-year standard deviation exceeds a decade of trend in every city, which is why nobody notices warming from memory",
      "The original regressed temperature on a synthetic `generate_dummy_legislation_influence` feature, and fitted a trend through 90 days of daily maxima -- which measures the seasons"
    ],
    "output": {
      "caption": "London: one slope, four error bars",
      "text": "  method                   slope   std err   95% interval             p\n  OLS                    +0.2346    0.0294   [+0.1760, +0.2933]  1.6e-11\n  Newey-West (lag 3)     +0.2346    0.0352   [+0.1644, +0.3049]  4.4e-09\n  block bootstrap (4y)   +0.2346    0.0323   [+0.1712, +0.2978]  0.0e+00\n  Mann-Kendall / Sen     +0.2438       nan   [+0.1836, +0.3050]  2.3e-09\n\n  residual lag-1 +0.200, effective n 50 of 75\n  -> the OLS standard error is too small by about 23%."
    }
  }
];
