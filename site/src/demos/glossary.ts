/**
 * Plain-English definitions for the jargon in the demos.
 *
 * The demos are configurable, which is only useful if you know what you are
 * configuring. "Hold top 3" and "Rebalance quarterly" are levers with real
 * consequences and no meaning at all to someone who has not met them before,
 * and a portfolio nobody can operate is a portfolio nobody can judge.
 *
 * Two rules for the text. **No term is defined using another undefined term** —
 * a definition that needs a second lookup has not explained anything. And each
 * entry says what the number is *for*, not just what it measures: "above 1 is
 * good, and easy to inflate with a short sample" is the part that lets a reader
 * decide whether to believe the figure on screen.
 *
 * `aliases` exist because the same idea appears under several labels across the
 * demos (Annualised / Annualized, Sharpe / Sharpe ratio).
 */

export interface GlossaryEntry {
  /** The heading shown in the popover. */
  term: string;
  /** The definition. Two or three sentences, no jargon of its own. */
  body: string;
  /** What it means for the thing on screen right now. Optional. */
  here?: string;
  /** Other labels that should resolve to this entry. */
  aliases?: string[];
}

export const GLOSSARY: Record<string, GlossaryEntry> = {
  // ------------------------------------------------------------------ rates
  "curve-factor": {
    term: "Curve factor",
    body:
      "Nine Treasury yields do not move independently — when the ten-year " +
      "sells off the seven-year almost always does too. A principal component " +
      "is one of the independent movements underneath: a shape the whole curve " +
      "moves in, plus a number saying how much of the total movement it " +
      "accounts for.",
    here:
      "Three of them cover 95% of everything the curve did in forty-five " +
      "years. The first shifts every tenor together (level), the second tilts " +
      "the ends against each other (slope), the third moves the middle against " +
      "both ends (curvature).",
    // Deliberately not aliased to "factor" or "pca". Both already exist
    // here meaning other things -- an equity factor like momentum, and
    // PCA used to squash columns into two dimensions for a scatter plot.
    aliases: ["level slope curvature"],
  },
  dv01: {
    term: "DV01",
    body:
      "What a bond position gains or loses if its yield moves by one basis " +
      "point — a hundredth of a percent. It is how size is measured in rates, " +
      "because $10m of two-year and $10m of thirty-year are wildly different " +
      "amounts of risk, while $1,000 of DV01 in each is the same.",
    here:
      "Every trade here is sized per $1 of DV01 on the belly leg, so the P&L " +
      "is comparable across trades and across eras. \"DV01-neutral\" means the " +
      "legs cancel: a parallel move in all yields nets to zero.",
    aliases: ["dollar value of a basis point", "duration", "dv01-neutral"],
  },
  carry: {
    term: "Carry",
    body:
      "The yield a bond pays you simply for holding it, before anything moves. " +
      "It needs no forecast: if the curve sat perfectly still, carry is what " +
      "you would still earn.",
    here:
      "It is kept in its own column precisely so it can be told apart from the " +
      "part that needed a view. On these butterflies, carry is essentially the " +
      "whole return and the directional part is worth about nothing.",
    aliases: ["roll-down", "rolldown", "carry and roll"],
  },
  // ----------------------------------------------------------------- markets
  backtest: {
    term: "Backtest",
    body:
      "Running a strategy over past prices to see what it would have done. It " +
      "is not evidence that the strategy will work — it is a check that the " +
      "rules are coherent and that the result is not an accident of one lucky " +
      "stretch.",
    here:
      "Every number here comes from real daily closes, replayed one day at a " +
      "time. No money was ever at risk.",
  },
  factor: {
    term: "Factor",
    body:
      "A measurable characteristic of a company that has historically lined up " +
      "with its future returns — how much its price has risen lately, how " +
      "steady that price is, how cheap it looks against its earnings. A factor " +
      "strategy scores every company in its list on that characteristic and " +
      "buys the highest scorers.",
    here:
      "Pick more than one and the scores are combined, so a company has to do " +
      "well on both to be bought.",
    aliases: ["factors"],
  },
  momentum: {
    term: "Momentum",
    body:
      "The observation that shares which have risen over the past year tend to " +
      "keep rising for a while longer. Nobody fully agrees on why; the usual " +
      "explanations are that investors react to news slowly, or that they chase " +
      "what is already going up.",
    here: "Measured as the return over the previous 252 trading days, about one year.",
  },
  "low-volatility": {
    term: "Low volatility",
    body:
      "Shares whose price moves less from day to day. Historically they have " +
      "delivered returns comparable to jumpier shares while putting their " +
      "holders through smaller swings, which is a better deal for the same " +
      "destination.",
    here: "Measured from the spread of daily moves over the previous 21 trading days.",
    aliases: ["low volatility"],
  },
  universe: {
    term: "Universe",
    body:
      "The list of companies a strategy is allowed to buy. It matters more than " +
      "it sounds: a strategy that only ever looks at large, successful " +
      "companies has already made most of its decision before any ranking " +
      "happens.",
  },
  "hold-top": {
    term: "Hold top N",
    body:
      "How many of the ranked companies to actually buy. Holding the top 3 " +
      "means buying the three highest scorers and nothing else.",
    here:
      "Fewer names means more of the outcome rides on each pick — higher " +
      "potential return, and a worse result when one of them is wrong.",
  },
  rebalance: {
    term: "Rebalance",
    body:
      "Re-scoring every company and rebuilding the portfolio to match the new " +
      "ranking. Prices move constantly, so yesterday's best picks are not " +
      "always today's.",
    here:
      "More often follows the signal more closely but trades more, and every " +
      "trade costs money. Monthly here means every 21 trading days.",
    aliases: ["rebalances"],
  },
  nav: {
    term: "NAV",
    body:
      "Net asset value — what the portfolio is worth at a given moment, cash " +
      "and holdings together. Plotting it over time is the most direct picture " +
      "of whether a strategy made or lost money.",
  },
  "total-return": {
    term: "Total return",
    body:
      "The whole gain or loss from the first day to the last, as a percentage. " +
      "It says nothing about the path: +50% could mean a steady climb or a " +
      "crash followed by a recovery.",
  },
  annualised: {
    term: "Annualised return",
    body:
      "The total return restated as a per-year rate, so results over different " +
      "lengths of time can be compared. A 21% gain over three years is about 7% " +
      "a year.",
    aliases: ["annualized", "annualised return", "annualized return"],
  },
  volatility: {
    term: "Volatility",
    body:
      "How much the return bounces around, stated as a per-year figure. Higher " +
      "means a bumpier ride, not necessarily a worse destination — it is a " +
      "measure of uncertainty, not of loss.",
    aliases: ["annualised volatility", "annualized volatility"],
  },
  sharpe: {
    term: "Sharpe ratio",
    body:
      "Return divided by volatility — roughly, how much you were paid for the " +
      "bumpiness. Two strategies returning 10% are not equal if one of them " +
      "got there calmly.",
    here:
      "Above 1 is considered good. It is also easy to inflate with a short " +
      "sample or a well-chosen window, so treat a high number from a few years " +
      "of data with suspicion.",
    aliases: ["sharpe ratio"],
  },
  drawdown: {
    term: "Max drawdown",
    body:
      "The worst fall from a previous high point to the low that followed. If " +
      "it reads 36%, then at some moment the portfolio was worth 36% less than " +
      "its own best day.",
    here:
      "This is the number that decides whether a strategy actually gets held. " +
      "A single figure hides how long the fall lasted, which matters just as " +
      "much as how deep it went.",
    aliases: ["max drawdown", "maximum drawdown"],
  },
  "look-ahead": {
    term: "Look-ahead bias",
    body:
      "Accidentally using information that was not available at the time. A " +
      "strategy that picks 2021 holdings using 2024 prices will look brilliant " +
      "and mean nothing, because nobody could have run it.",
    here:
      "Toggle it on to see the same strategy over the same prices report 95% " +
      "instead of 3%. It is the most common way a backtest lies.",
  },
  benchmark: {
    term: "Benchmark",
    body:
      "A simple standard to measure a strategy against, usually a broad market " +
      "index such as the S&P 500. A strategy up 300% in a period the market " +
      "rose 400% lost money in the only sense that matters.",
  },
  "trading-day": {
    term: "Trading day",
    body:
      "A day the stock market is open — weekdays, minus public holidays, about " +
      "252 a year. Prices do not exist for weekends, so every window here is " +
      "counted in trading days rather than calendar days.",
    aliases: ["trading days", "session", "sessions"],
  },

  // -------------------------------------------------------- earnings / drift
  earnings: {
    term: "Earnings",
    body:
      "A public company's profit, which it must report every three months. " +
      "Analysts at banks publish an estimate of that figure beforehand, and the " +
      "gap between the estimate and the actual number is what moves the share " +
      "price on the day.",
  },
  surprise: {
    term: "Earnings surprise",
    body:
      "How far the reported profit came in above or below what analysts had " +
      "estimated, as a percentage of the estimate. +10% means the company " +
      "earned a tenth more than expected.",
    here:
      "The whole question here is whether a bigger surprise is followed by a " +
      "bigger move in the weeks afterwards.",
    aliases: ["earnings surprise", "median surprise"],
  },
  drift: {
    term: "Post-earnings drift",
    body:
      "The tendency for a share to keep moving in the direction of its earnings " +
      "surprise for weeks after the announcement, rather than adjusting all at " +
      "once on the day. If it is real, the market absorbs news more slowly than " +
      "it is supposed to.",
    aliases: ["post-earnings drift", "pead"],
  },
  abnormal: {
    term: "Abnormal return",
    body:
      "A share's return with the market's return over the same days subtracted. " +
      "It isolates the part of the move that was about this company rather than " +
      "about everything going up or down together.",
    here:
      "It matters a lot: the raw drift here is +1.43% and the abnormal drift is " +
      "+0.43%, so two thirds of the apparent effect was just the market.",
    aliases: ["abnormal return", "abnormal drift", "market-adjusted"],
  },
  "beat-rate": {
    term: "Beat rate",
    body:
      "The share of announcements where the company reported more profit than " +
      "analysts estimated. It usually sits well above half, because estimates " +
      "tend to be set at a level companies can clear.",
    aliases: ["beat rate"],
  },
  quintile: {
    term: "Quintile",
    body:
      "One fifth of a sorted list. Splitting announcements into surprise " +
      "quintiles puts the 20% biggest surprises in one bucket and the 20% " +
      "smallest in another, so the two extremes can be compared directly.",
    aliases: ["quintiles"],
  },
  "t-stat": {
    term: "t-statistic",
    body:
      "A measure of whether a difference is bigger than the noise around it. " +
      "Above about 2 is the usual bar for calling a result unlikely to be " +
      "chance — it is a test of whether the effect is detectable, not of " +
      "whether it is large enough to be useful.",
    aliases: ["t-statistic", "t stat"],
  },

  // ------------------------------------------------------------------- cache
  cache: {
    term: "Cache",
    body:
      "A store of answers already worked out, so the same question does not " +
      "have to be answered twice. Caching is how a slow function becomes a fast " +
      "one, and almost everything you use is doing it somewhere.",
  },
  "hit-rate": {
    term: "Hit rate",
    body:
      "The share of requests the cache could answer from memory. A hit is free; " +
      "a miss means doing the real work. This is the single number that says " +
      "whether a cache is earning its keep.",
    aliases: ["hit rate", "hits", "misses"],
  },
  capacity: {
    term: "Capacity",
    body:
      "How many answers the cache is allowed to keep. Memory is finite, so once " +
      "it is full, storing something new means throwing something else out.",
  },
  eviction: {
    term: "Eviction",
    body:
      "Throwing an entry out of a full cache to make room. Which one to throw " +
      "is the whole design problem: get it wrong and you discard the entry you " +
      "were about to need.",
    aliases: ["evictions", "evicted"],
  },
  lru: {
    term: "LRU",
    body:
      "Least Recently Used. When the cache is full, discard whatever has gone " +
      "untouched for longest. It assumes that what you used just now is what " +
      "you will use next, which is true surprisingly often.",
    here:
      "Its weakness is a scan: read ten thousand things once each and LRU " +
      "throws away everything useful to make room for them.",
  },
  lfu: {
    term: "LFU",
    body:
      "Least Frequently Used. When the cache is full, discard whatever has been " +
      "asked for fewest times. It protects a popular entry from being pushed " +
      "out by a crowd of one-off requests.",
    here:
      "Its weakness is the mirror image: when what is popular changes, the old " +
      "favourites have counts the newcomers can never catch, so they sit there " +
      "forever serving nobody.",
  },
  ttl: {
    term: "TTL",
    body:
      "Time to live — how long a cached answer stays usable before it has to be " +
      "worked out again. An exchange rate is not wrong to cache, it is wrong to " +
      "cache forever.",
    aliases: ["time to live"],
  },

  // ------------------------------------------------------------------ search
  crawler: {
    term: "Crawler",
    body:
      "A program that fetches a web page, finds the links on it, fetches those, " +
      "and keeps going. It is how a search engine discovers what exists before " +
      "it can index anything.",
    aliases: ["crawl"],
  },
  trie: {
    term: "Trie",
    body:
      "A tree that stores words one letter per level, so all the words " +
      "beginning \"par\" hang below the same branch. That shape makes " +
      "\"everything starting with par\" a short walk down the tree instead of a " +
      "scan through every word you know.",
  },
  bm25: {
    term: "BM25",
    body:
      "The standard way to score how relevant a page is to a query. It rewards " +
      "a page for using your words often, discounts words that appear " +
      "everywhere and so distinguish nothing, and adjusts for page length so a " +
      "long page cannot win by simply containing more text.",
    here:
      "Try \"park\": the short page wins on fewer mentions, because 4 mentions " +
      "in 32 words is denser than 5 in 64.",
    aliases: ["score"],
  },
  and: {
    term: "AND search",
    body:
      "Requiring every word you typed to appear, rather than any of them. Two " +
      "words almost always means both — an any-of search buries the good " +
      "results under pages that merely used the commoner word.",
  },
  wildcard: {
    term: "Wildcard",
    body:
      "A placeholder standing in for characters you do not want to spell out. " +
      "Here `?` matches exactly one character, so `d?g` finds dog and dig, and a " +
      "trailing `*` matches any ending, so `par*` finds park, parks and parking.",
  },

  // ---------------------------------------------------------------- schedule
  section: {
    term: "Section",
    body:
      "One of several sittings of the same course, at different times with " +
      "different instructors. You take one of them, never two — which is why " +
      "picking the right section is most of the work in building a timetable.",
    aliases: ["sections"],
  },
  conflict: {
    term: "Conflict",
    body:
      "Two classes whose times overlap, so you cannot attend both. A class " +
      "ending at 19:30 and one starting at 19:30 do not conflict — they are " +
      "back to back.",
    aliases: ["clash", "conflicts"],
  },
  cost: {
    term: "Cost",
    body:
      "How annoying a schedule is, in minutes. An extra day on campus is priced " +
      "at 60, an hour of dead time between classes at 30, a class on a day you " +
      "asked to keep free at 480. Lower is better.",
    here:
      "Everything is in one unit on purpose, so the total means something " +
      "instead of being an arbitrary score, and `why:` shows what drove it.",
  },
  "proven-optimal": {
    term: "Proven optimal",
    body:
      "Whether the search checked enough possibilities to be certain nothing " +
      "better exists, or simply ran out of budget first. \"The best there is\" " +
      "and \"the best I had time to find\" are different claims, and reporting " +
      "the second as the first would be the real bug.",
    aliases: ["nodes", "nodes searched"],
  },

  // ------------------------------------------------------------------- cards
  "expected-points": {
    term: "Expected points",
    body:
      "The average score you would get from a choice if you made it over and " +
      "over. A one-in-twenty shot at 2000 points is worth more than a certain " +
      "50, even though it usually pays nothing.",
    aliases: ["pts", "expected value"],
  },
  "exact-vs-sampled": {
    term: "Exact vs sampled",
    body:
      "Throwing one card away has 45 possible replacements and two has 990, so " +
      "every outcome can simply be counted — those answers are exact. Five " +
      "discards has 1,221,759, too many to count, so a few hundred are drawn at " +
      "random and averaged instead.",
    here:
      "`±` is the margin on a sampled figure. It is widest where one rare huge " +
      "payoff can swing the average, which is a property of the game rather " +
      "than a flaw in the estimate.",
    aliases: ["exact", "sampled"],
  },
  "monte-carlo": {
    term: "Monte Carlo",
    body:
      "Answering a question you cannot compute by trying it at random many " +
      "times and averaging. Used whenever the number of possibilities is too " +
      "large to count but easy to sample from.",
  },

  // ----------------------------------------------------- models & statistics
  accuracy: {
    term: "Accuracy",
    body:
      "The share of predictions that were right. It is the most quoted measure " +
      "and often the least useful: if 3% of customers leave, predicting \"nobody " +
      "leaves\" scores 97% and is worthless.",
  },
  precision: {
    term: "Precision",
    body:
      "Of the cases the model flagged, how many it got right. Low precision " +
      "means crying wolf — you chase customers who were never going to leave.",
  },
  recall: {
    term: "Recall",
    body:
      "Of the cases that really happened, how many the model caught. Low recall " +
      "means quietly missing most of them, which an accuracy score will not " +
      "show you.",
  },
  f1: {
    term: "F1",
    body:
      "A single number blending precision and recall, so a model cannot look " +
      "good by being cautious or by flagging everything. It sits between the " +
      "two, closer to the worse one.",
  },
  auc: {
    term: "ROC AUC",
    body:
      "How well the model separates the two groups, from 0.5 (no better than a " +
      "coin flip) to 1.0 (perfect). Unlike accuracy it does not depend on where " +
      "you set the cut-off, so it measures ranking rather than a decision.",
    aliases: ["roc auc"],
  },
  threshold: {
    term: "Decision threshold",
    body:
      "The score above which the model says yes. Moving it trades the two kinds " +
      "of mistake against each other: catch more real cases, and flag more " +
      "people who were fine.",
    here: "Drag it and watch precision and recall move in opposite directions.",
    aliases: ["decision threshold"],
  },
  "confusion-matrix": {
    term: "Confusion matrix",
    body:
      "A two-by-two count of what the model said against what actually " +
      "happened. The diagonal is the cases it got right; the other two cells " +
      "are the two different ways of being wrong.",
  },
  rmse: {
    term: "RMSE",
    body:
      "Root mean squared error — the typical size of the model's mistake, in " +
      "the units being predicted. An RMSE of $1,400 on a bitcoin price means " +
      "predictions are off by roughly that much, and big misses count for more " +
      "than small ones.",
  },
  mape: {
    term: "MAPE",
    body:
      "Mean absolute percentage error — the typical mistake as a percentage " +
      "rather than an amount. Useful when the thing being predicted changes " +
      "scale, since being $1,000 out matters differently at $20,000 and at " +
      "$60,000.",
  },
  baseline: {
    term: "Naive baseline",
    body:
      "The dumbest prediction that is not obviously stupid — here, \"tomorrow " +
      "will be the same as today\". Every model has to beat it to have earned " +
      "its complexity, and a surprising number do not.",
    here:
      "This one does not: the baseline scores an RMSE of $1,401 and the neural " +
      "network $22,283.",
    aliases: ["naive rmse", "naive"],
  },
  "directional-accuracy": {
    term: "Directional accuracy",
    body:
      "How often the model got the direction right — up or down — regardless of " +
      "by how much. It matters more than the size of the error for anything you " +
      "would trade on, because only the change is tradeable.",
    here:
      "Around a coin flip for every forecaster here. A chart can track a price " +
      "level convincingly while carrying no information about its changes. " +
      "Days where the forecast implies no move are counted separately as " +
      "abstentions — no call is not the same as a wrong one, and the naive " +
      "forecast abstains on every single day.",
    aliases: ["directional accuracy", "direction"],
  },
  lstm: {
    term: "LSTM",
    body:
      "A kind of neural network built for sequences, which keeps a memory of " +
      "what it has seen so far. Popular for price prediction, and prone to " +
      "learning to repeat the most recent value — which looks impressive on a " +
      "chart and predicts nothing.",
  },
  lookback: {
    term: "Lookback window",
    body:
      "How many past days the model is shown before it makes each prediction. " +
      "Longer gives it more context and fewer examples to learn from.",
    aliases: ["lookback window"],
  },
  "train-test": {
    term: "Train / test split",
    body:
      "Fitting the model on one stretch of history and grading it on a later " +
      "stretch it has never seen. Grading a model on the data it learned from " +
      "measures memory, not prediction.",
    aliases: ["train / test days", "train/test"],
  },
  pca: {
    term: "Principal component",
    body:
      "A way of squashing many columns down to two so they can be drawn. The " +
      "first component is the single direction along which the data varies " +
      "most; the second is the next, at right angles to it. The axes are " +
      "mixtures of the original columns, so distance means \"similar\" and the " +
      "numbers on the axes mean nothing by themselves.",
    aliases: ["first principal component", "second principal component", "pca"],
  },
  clustering: {
    term: "Clustering",
    body:
      "Grouping records by similarity with nobody having labelled them first. " +
      "It always returns groups, which is the trap: there is no ground truth to " +
      "check them against, so a clean-looking split can be an artefact of the " +
      "columns you happened to feed it.",
    aliases: ["k-means", "dbscan", "cluster"],
  },
  anomaly: {
    term: "Anomaly detection",
    body:
      "Finding the records that do not look like the rest. Useful for flagging " +
      "things worth a human look, but \"unusual\" and \"important\" are not the " +
      "same thing and nothing in the method knows the difference.",
    aliases: ["isolation forest", "flagged anomalous", "anomalous"],
  },

  // ----------------------------------------------------- portfolio optimiser
  frontier: {
    term: "Efficient frontier",
    body:
      "The curve of the best available trade-offs: for each level of bumpiness, " +
      "the mix that historically returned the most. Anything below the curve is " +
      "strictly worse than something on it, so there is no reason to hold it.",
    aliases: ["efficient frontier"],
  },
  etf: {
    term: "ETF",
    body:
      "A single tradeable fund holding a basket of things — every share in the " +
      "S&P 500, or a spread of government bonds. It is how one purchase buys " +
      "a whole market.",
    aliases: ["etfs"],
  },
  "treasuries": {
    term: "Treasuries",
    body:
      "Loans to the US government, which pays them back with interest. Treated " +
      "as the safest thing available, so they are where an allocation goes when " +
      "it is told to avoid risk at any cost.",
    aliases: ["short treasuries"],
  },

  // ------------------------------------------------------------------ weather
  reanalysis: {
    term: "Reanalysis",
    body:
      "A reconstruction of past weather that blends real measurements with a " +
      "physics model to fill the gaps, giving a complete hourly record " +
      "everywhere. It is the closest thing to historical weather observations " +
      "for places and times nobody was measuring.",
    aliases: ["era5"],
  },
  "warming-rate": {
    term: "Warming rate",
    body:
      "How fast average temperature is rising, in degrees per decade, fitted as " +
      "a straight line through the record. A projection from it is that line " +
      "extended — not a climate model, and year-to-year variation is larger " +
      "than a decade of trend.",
    aliases: ["warming rate"],
  },

  // -------------------------------------------------------------- inference
  "permutation-test": {
    term: "Permutation test",
    body:
      "Shuffle the answers at random, re-run the whole analysis, and repeat a " +
      "few hundred times. That builds a picture of what your method scores on " +
      "data with no signal in it whatsoever. If the real result sits inside " +
      "that picture, the real result is what noise looks like.",
    here:
      "It needs no assumption about how the data is distributed, which is why " +
      "it is trustworthy where a textbook formula might not be.",
    aliases: ["permutation", "permutation null", "shuffle test"],
  },
  "p-value": {
    term: "p-value",
    body:
      "The chance of seeing a result at least this strong if nothing real were " +
      "going on. Small means the result is hard to explain as luck. It is not " +
      "the probability that the finding is true, and 0.05 is a convention, not " +
      "a law of nature.",
    aliases: ["p value", "significance"],
  },
  "statistical-power": {
    term: "Statistical power",
    body:
      "How likely a study is to spot an effect that really is there. It depends " +
      "on how big the effect is and how much data you have. Low power means " +
      "'we found nothing' is uninformative — you would probably have found " +
      "nothing either way.",
    here:
      "Quoting the smallest effect a design could have detected turns 'no " +
      "signal' from a shrug into a bounded claim.",
    aliases: ["power", "minimum detectable effect"],
  },
  "learning-curve": {
    term: "Learning curve",
    body:
      "Accuracy plotted against how much training data the model was given. A " +
      "model held back by sample size climbs as you feed it more. A flat line " +
      "means more data will not help, so the limit is the data itself.",
  },
  "benjamini-hochberg": {
    term: "Benjamini-Hochberg",
    body:
      "A correction for testing many things at once. Test twenty features at " +
      "the usual 5% cut-off and about one will look significant by pure chance; " +
      "this raises the bar so that the share of your 'discoveries' that are " +
      "flukes stays controlled.",
    aliases: ["multiple testing", "false discovery rate", "fdr"],
  },
  "confidence-interval": {
    term: "Confidence interval",
    body:
      "A range that the true value is plausibly in, given the data. Wide means " +
      "the estimate is uncertain. The single number in the middle is the least " +
      "interesting part — the width is what tells you how much to trust it.",
    aliases: ["interval", "ci", "error bar"],
  },
  "null-model": {
    term: "Null model",
    body:
      "A deliberately meaningless version of the data, built to see what your " +
      "method reports when there is nothing to find. Every method returns " +
      "something; the null is how you learn whether that something means " +
      "anything.",
    aliases: ["null", "null distribution"],
  },

  // -------------------------------------------------------------- clustering
  silhouette: {
    term: "Silhouette score",
    body:
      "How neatly points sit inside their assigned cluster rather than near a " +
      "neighbouring one, from -1 to 1. Higher looks better, but it can only " +
      "compare groupings — it cannot tell you whether any grouping should " +
      "exist, because it is undefined when everything is one group.",
    here:
      "Which is why it is shown against a shuffled null here rather than on " +
      "its own.",
  },
  "gap-statistic": {
    term: "Gap statistic",
    body:
      "Compares how tightly your data clusters against how tightly pure random " +
      "noise of the same size and shape clusters. Unlike an elbow plot it can " +
      "return an answer of one — meaning 'there are no groups here' — which is " +
      "sometimes the correct answer.",
    aliases: ["gap"],
  },
  ari: {
    term: "Adjusted Rand index",
    body:
      "How much two groupings of the same items agree, corrected so that chance " +
      "agreement scores zero. 1 is identical. Re-cluster a random half of your " +
      "data repeatedly and a low score means the groups move when the data " +
      "does — they were fitted to noise.",
    aliases: ["adjusted rand index", "cluster stability", "stability"],
  },
  "cramers-v": {
    term: "Cramér's V",
    body:
      "Correlation for categories rather than numbers, from 0 to 1. It answers " +
      "'does knowing the industry tell you anything about the attack type?'. " +
      "Near zero means the two columns are unrelated.",
    aliases: ["cramers v", "cramér's v", "association"],
  },
  "ks-test": {
    term: "Uniformity test",
    body:
      "Checks whether a column is spread evenly across its range instead of " +
      "clustering anywhere. Real quantities are lumpy — most incidents are " +
      "small, a few are huge. A perfectly flat column is a strong hint that a " +
      "random number generator produced it.",
    aliases: ["uniformity", "kolmogorov-smirnov"],
  },

  // ------------------------------------------------------------ recommenders
  "recall-at-k": {
    term: "Recall@k",
    body:
      "Of the things a customer actually bought, what share appeared in the top " +
      "k recommendations. It answers 'did we surface it at all', so it rises as " +
      "you show more items.",
    aliases: ["recall@k", "recall at k"],
  },
  "precision-at-k": {
    term: "Precision@k",
    body:
      "Of the k items recommended, what share the customer actually wanted. " +
      "Shorter lists can score higher, so it trades off against recall.",
    aliases: ["precision@k", "precision at k"],
  },
  ndcg: {
    term: "NDCG",
    body:
      "Like recall, but it cares where in the list the right answer landed — a " +
      "hit at position one counts for more than a hit at position ten. 1 is a " +
      "perfect ordering.",
    aliases: ["ndcg@k", "normalised discounted cumulative gain"],
  },
  mrr: {
    term: "MRR",
    body:
      "Mean reciprocal rank: one divided by the position of the first correct " +
      "item, averaged over customers. Finding it first scores 1, third scores " +
      "0.33. The metric to use when people only look at the top of the list.",
    aliases: ["mean reciprocal rank", "reciprocal rank"],
  },
  map: {
    term: "MAP",
    body:
      "Mean average precision: precision measured at each position where a " +
      "correct item appears, averaged. It rewards getting several right answers " +
      "high up rather than just one.",
    aliases: ["mean average precision", "map@k"],
  },
  "leave-one-out": {
    term: "Leave-one-out",
    body:
      "Hide one of a customer's purchases, recommend from what is left, and see " +
      "whether the hidden one comes back. Nothing is scored against information " +
      "the recommender was allowed to see, which is what makes the number mean " +
      "anything.",
    aliases: ["loo", "held out"],
  },
  oracle: {
    term: "Oracle",
    body:
      "A deliberately cheating method that is allowed to see the answer. It is " +
      "not a proposal — it is a ruler. If a normal method scores near the " +
      "oracle, look for a leak; if the oracle scores a perfect 1.0, the column " +
      "it read already contained the answer.",
    aliases: ["leak", "data leak", "leakage"],
  },

  // ---------------------------------------------------------------- trends
  "newey-west": {
    term: "Newey-West",
    body:
      "A way of widening an error bar to account for measurements that are not " +
      "independent. Warm years follow warm years, so seventy-five annual " +
      "readings carry less information than seventy-five unrelated ones, and " +
      "the ordinary formula would report more confidence than is earned.",
    aliases: ["hac", "newey west", "heteroskedasticity and autocorrelation consistent"],
  },
  "mann-kendall": {
    term: "Mann-Kendall",
    body:
      "A trend test that only looks at whether later values tend to exceed " +
      "earlier ones, ignoring their size. That makes it immune to one freak " +
      "year, which would tug a straight-line fit. The standard cross-check in " +
      "climate work.",
    aliases: ["sen's slope", "sens slope", "mann kendall"],
  },
  "block-bootstrap": {
    term: "Block bootstrap",
    body:
      "Re-runs the analysis on thousands of resampled versions of the data to " +
      "see how much the answer wobbles. It resamples in contiguous blocks " +
      "rather than single points, so the year-to-year persistence in the record " +
      "is preserved rather than shuffled away.",
    aliases: ["bootstrap", "moving block bootstrap"],
  },
  autocorrelation: {
    term: "Autocorrelation",
    body:
      "When each value is related to the one before it. Temperature has plenty: " +
      "a warm year makes the next year more likely to be warm. It does not bias " +
      "the trend, but it does mean the usual uncertainty formulas understate " +
      "how uncertain that trend is.",
    aliases: ["serial correlation", "lag-1"],
  },
  "effective-sample-size": {
    term: "Effective sample size",
    body:
      "How many genuinely independent observations your correlated data is " +
      "worth. Seventy-five annual temperatures behaving like forty-six " +
      "independent ones is the honest count to do statistics with.",
    aliases: ["effective n"],
  },

  // ------------------------------------------------------------- allocation
  "in-sample": {
    term: "In-sample",
    body:
      "A result measured on the same data used to choose the strategy. It is " +
      "always flattering, because the choice was tuned to those exact numbers. " +
      "Treat it as an upper bound on fantasy, not an estimate of performance.",
    aliases: ["in sample", "fitted"],
  },
  "out-of-sample": {
    term: "Out-of-sample",
    body:
      "A result measured on data the strategy had never seen when its decisions " +
      "were made — here, weights chosen from a trailing window and then held " +
      "forward. The only version of a backtest worth reading.",
    aliases: ["out of sample", "realised"],
  },
  "ledoit-wolf": {
    term: "Ledoit-Wolf shrinkage",
    body:
      "Estimating how assets move together from limited history gives a noisy " +
      "answer, and optimisers chase that noise. Shrinkage pulls the estimate " +
      "part-way toward a simple, stable one — accepting a little bias to remove " +
      "a lot of noise.",
    aliases: ["shrinkage", "covariance shrinkage"],
  },
  "minimum-variance": {
    term: "Minimum variance",
    body:
      "The mix with the smallest possible wobble, ignoring returns entirely. It " +
      "usually lands on whatever is safest, so a spectacular-looking " +
      "return-to-risk ratio often just means 'it bought cash'.",
    aliases: ["min variance", "min vol"],
  },
  "risk-parity": {
    term: "Risk parity",
    body:
      "Size each holding so that each contributes the same amount of risk, " +
      "rather than the same amount of money. It needs no forecast of returns, " +
      "which is exactly why it tends to survive contact with the future.",
  },
  "equal-weight": {
    term: "Equal weight (1/N)",
    body:
      "Put the same amount in everything. It estimates nothing, so there is " +
      "nothing for it to get wrong, and it is a famously hard benchmark for " +
      "clever optimisers to beat once their estimation error is counted.",
    aliases: ["1/n", "naive diversification"],
  },
  turnover: {
    term: "Turnover",
    body:
      "How much of the portfolio is bought and sold at each rebalance. Every " +
      "trade costs money, so a rule whose weights lurch around each quarter is " +
      "paying for the privilege of chasing noise.",
  },
  "excess-sharpe": {
    term: "Sharpe over cash",
    body:
      "Return above what cash would have paid, divided by how much it wobbled. " +
      "Subtracting cash is what makes the comparison fair: a portfolio that is " +
      "entirely cash has a huge plain return-to-risk ratio and an excess Sharpe " +
      "of about zero, which is the honest score.",
    aliases: ["excess sharpe", "sharpe over cash"],
  },
  "condition-number": {
    term: "Condition number",
    body:
      "How close a matrix is to being unusable. A large value means small " +
      "errors in the inputs become large errors in the answer — so an optimiser " +
      "fed one will produce confident, precise, meaningless weights.",
  },

  // --------------------------------------------------------------- forecasts
  "walk-forward": {
    term: "Walk-forward",
    body:
      "Train on the past, test on the next stretch, roll forward, repeat. One " +
      "train/test split gives one number that might be luck; twenty rolling " +
      "ones show whether the result holds up across different market regimes.",
    aliases: ["rolling origin", "walk forward"],
  },
  "diebold-mariano": {
    term: "Diebold-Mariano",
    body:
      "A test for whether one forecast is genuinely more accurate than another, " +
      "or just happened to be on this sample. Comparing two error numbers " +
      "cannot tell you; this accounts for the fact that both forecasts make " +
      "their mistakes on the same days.",
    aliases: ["dm test"],
  },
  "wilson-interval": {
    term: "Wilson interval",
    body:
      "An error bar around a percentage. 52% right out of 4,000 days sounds " +
      "like an edge until you see the range around it. Wilson is used rather " +
      "than the textbook formula because that one misbehaves near 0% and 100%.",
    aliases: ["wilson score interval"],
  },
  "return-r2": {
    term: "R² on returns",
    body:
      "Whether a forecast predicts the daily *change* better than just guessing " +
      "'no change'. Predicting tomorrow's price is easy — it is close to " +
      "today's. Predicting the move is the hard part, and negative here means " +
      "worse than not trying.",
    aliases: ["return r2", "r squared on returns"],
  },
  "buy-and-hold": {
    term: "Buy and hold",
    body:
      "Buy once, do nothing, pay no further costs. The benchmark any trading " +
      "strategy has to beat, and in a strongly rising market most of them turn " +
      "out to be it in disguise with extra fees.",
    aliases: ["buy & hold"],
  },
  // ------------------------------------------------------------------ music
  viterbi: {
    term: "Viterbi algorithm",
    body:
      "A way of finding the single cheapest route through a sequence of "
      + "choices, when each choice has a cost of its own and each pair of "
      + "neighbouring choices has a cost between them. It works by keeping, at "
      + "every step, only the best route to each option \u2014 which is why it "
      + "can be exact without trying every combination.",
    here:
      "Each chord offers dozens of playable voicings, and the best one depends "
      + "on the chord before it. Trying every combination of a seven-chord "
      + "progression would mean billions of paths; this finds the best in a "
      + "few hundred thousand comparisons.",
    aliases: ["dynamic programming", "shortest path"],
  },
  greedy: {
    term: "Greedy",
    body:
      "Making each choice as well as possible at the moment you make it, "
      + "without looking ahead. It is fast and often close, but it cannot "
      + "accept a slightly worse choice now in exchange for a much better one "
      + "later \u2014 so it can talk itself into a corner.",
    here:
      "Picking the nicest voicing for each chord in turn leaves the hand in "
      + "awkward places for the chord after. Measured over eight progressions "
      + "it costs 5% at beginner and 29% at advanced.",
    aliases: ["greedy baseline"],
  },
  "voice-leading": {
    term: "Voice leading",
    body:
      "How each individual line moves from one chord to the next. The ear "
      + "follows lines, not chords, so a chord change sounds smooth when every "
      + "note moves a short distance \u2014 or better, does not move at all.",
    here:
      "Notes shared between neighbouring chords are held in place wherever "
      + "possible, which is the main reason to invert a chord rather than play "
      + "it in root position.",
  },
  "parallel-fifths": {
    term: "Parallel fifths",
    body:
      "Two voices a fifth apart that both move by the same amount, staying a "
      + "fifth apart. They stop sounding like two independent lines and "
      + "collapse into one thickened one, which is why four-part writing has "
      + "avoided them for about five hundred years.",
    aliases: ["parallel octaves", "parallels"],
  },
  inversion: {
    term: "Inversion",
    body:
      "Playing a chord with something other than its root as the lowest note. "
      + "The chord is unchanged \u2014 same notes, same name \u2014 but it sits "
      + "differently under the hand and connects differently to its neighbours.",
    here:
      "The freedom to invert is most of what separates the intermediate level "
      + "from the beginner one: it lets the solver keep the right hand still "
      + "across a chord change.",
    aliases: ["slash chord", "root position"],
  },
  "hand-span": {
    term: "Hand span",
    body:
      "The widest interval a hand can comfortably reach, measured in "
      + "semitones. Twelve is an octave, which most adults manage; fourteen is "
      + "a tenth and is a professional stretch. It is a hard physical limit, "
      + "not a preference.",
  },
  "shell-voicing": {
    term: "Shell voicing",
    body:
      "A chord played with only the notes that define it \u2014 usually root, "
      + "third and seventh \u2014 dropping the fifth. The fifth carries no "
      + "information about whether a chord is major or minor, so leaving it "
      + "out frees a finger and loses nothing.",
  },
  "chord-symbol": {
    term: "Chord symbol",
    body:
      "Shorthand naming which notes are in a chord, like Cmaj7 or F#m7b5. It "
      + "says nothing about which octave each note goes in, how many of each "
      + "to play, or which hand plays what \u2014 all of which someone has to "
      + "decide before it can be played.",
    aliases: ["chord chart", "lead sheet"],
  },
  "scaler-leak": {
    term: "Scaler leakage",
    body:
      "Squashing prices into a 0-1 range using the highest price in the whole " +
      "record — including the test period. The model then quietly knows the " +
      "future high before it forecasts. Doing it correctly, on training data " +
      "only, often makes results much worse and much more honest.",
    aliases: ["scaling leak"],
  },
};

/** Lower-cased label → entry id, including every alias. */
const LOOKUP: Record<string, string> = {};
for (const [id, entry] of Object.entries(GLOSSARY)) {
  LOOKUP[id.toLowerCase()] = id;
  LOOKUP[entry.term.toLowerCase()] = id;
  for (const alias of entry.aliases ?? []) LOOKUP[alias.toLowerCase()] = id;
}

/** Resolve an id, a term, or an alias to an entry. */
export function lookupTerm(key: string): GlossaryEntry | undefined {
  return GLOSSARY[LOOKUP[key.trim().toLowerCase()]];
}

export const GLOSSARY_IDS = Object.keys(GLOSSARY);
