# Fake News Detection

A null result, established properly. **This dataset contains no learnable
signal, and the analysis says how much that rules out** — which is a stronger
and more useful claim than "my model got 51%".

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
news-signal                      # the whole analysis
news-signal --section contents   # or one part
pytest -q                        # 38 tests
```

---

## The file does not contain articles

| column | distinct | distinct after removing digits | templated |
|---|---:|---:|---|
| title | 4,000 | **1** | yes |
| text | 4,000 | **1** | yes |
| author | 5 | 5 | no |
| source | 13 | 13 | no |

```
title[0]: 'Breaking News 1'
text[0] : 'This is the content of article 1. It contains detailed analysis and reports.'
```

Every title is `Breaking News {i}` and every body is the same sentence with the
index substituted. **Strip the digits and 4,000 distinct titles collapse to
one.** So the TF-IDF model in the original notebook was a model of the row
number.

That check is three lines and it would have stopped the analysis before the
first classifier was fitted. It is now the first thing the package does.

One trap worth naming: the label's correlation with row order is +0.008, so the
file is shuffled. Had it been sorted or blocked by label — which datasets often
are — a text model would have scored well *by reading the number*, and the
result would have looked entirely convincing.

## Showing there is no signal is harder than failing to find one

"51% AUC" is consistent with three different worlds: the data is noise, the
model is wrong, or 4,000 rows are too few to see a small effect. Those need
different responses, so three tools separate them.

### A permutation test

```
logistic regression, 5-fold out-of-fold AUC  0.5145
gradient boosting, 200 trees                 0.5136

permutation test, 150 shuffles of the label:
  observed                 0.5145
  shuffled-label null      0.4991 +/- 0.0120
  95% of shuffles fall in  [0.4749, 0.5179]
  z = +1.28,  p = 0.119
  -> the real labels are NOT distinguishable from random ones.
```

**The model found as much in the real labels as in randomly shuffled ones.**

This is the only way to be certain, because the null distribution of a
*cross-validated* AUC is not the textbook one. It is centred near 0.5, but its
spread depends on the sample size, the fold count and how much the model can
overfit — and those interact in ways no formula captures. So it is simulated,
by refitting on shuffled labels. Only the labels are shuffled: every
feature-feature correlation survives, and only the relationship under test is
destroyed.

### A power analysis

```
with 4,000 rows this design would detect AUC >= 0.526 at 80% power.
The observed AUC is 0.5145, below that threshold.
```

This is the number that turns *we found nothing* into **there is nothing bigger
than this to find**. Without it, "no signal" and "not enough data to see the
signal" are indistinguishable, and only the first is a statement about the
data. It uses the Hanley-McNeil null variance of AUC, which accounts for the
class split — an unbalanced sample has less power at the same total size.

### A learning curve

| rows | AUC |
|---:|---:|
| 800 | 0.5101 |
| 1,600 | 0.5003 |
| 2,400 | 0.5017 |
| 3,200 | 0.5003 |
| 4,000 | 0.5045 |

Slope **−0.0014** AUC per 1,000 rows. More data is not the missing ingredient.

A caveat I got wrong first and kept: a flat curve means "the ceiling is not the
sample size", which is true both when there is nothing to learn *and* when what
there is has already been learned. A planted effect in the tests produces a
curve that is flat too — just flat at 0.7. The level distinguishes them, not
the slope, which is why the permutation test is the load-bearing evidence and
this is corroboration.

## Per-feature tests, corrected for testing many

| feature | r | p | BH threshold | reject |
|---|---:|---:|---:|---|
| has_videos | −0.0276 | 0.0808 | 0.0038 | no |
| clickbait_score | +0.0271 | 0.0863 | 0.0077 | no |
| num_shares | +0.0229 | 0.1481 | 0.0115 | no |
| char_count | −0.0222 | 0.1600 | 0.0154 | no |

Nothing survives. Testing 13 features at p < 0.05 produces about **0.65 false
positives by chance**, so an uncorrected "this feature is significant" on a
dataset this wide means very little. Benjamini-Hochberg controls the false
discovery rate instead.

## Every test works in both directions

A null result is only credible if the method would have found an effect. So the
test suite plants one — a synthetic dataset with a known signal in
`trust_score` — and checks that:

- the permutation test flags it (z > 5) and is not distinguishable on the real data
- the power calculation's threshold falls as rows are added
- the per-feature test finds the planted column and nothing on the real file
- the template detector flags `Breaking News {i}` and *not* a column of five real author names

That last one was a bug: the first version of the heuristic flagged anything
with few distinct skeletons, which called five author names a template. Five
names are five names. The test is collapse, not count.

## Layout

```
src/news_signal/
  data.py    loading, template detection, the row-order trap   (pure)
  signal.py  permutation test, power, learning curve,
             per-feature tests with BH correction              (pure)
  cli.py     the report
tests/       38 tests, most of them paired against planted data
notebooks/   the original, kept as the record (marked superseded)
```

## Limits

- **This is a statement about this file, not about fake-news detection.** Real
  corpora — LIAR, FakeNewsNet — have genuine signal. Nothing here says the task
  is impossible, only that this dataset cannot be used to attempt it.
- **The power analysis assumes the AUC is estimated on independent rows.**
  Cross-validated AUC is slightly correlated across folds, so the true
  detectable effect is marginally larger than 0.526.
- **No text model is fitted at all**, because there is no text. Running TF-IDF
  over the row index would produce a number, and the number would be
  meaningless.

## Data

[Fake News Detection](https://www.kaggle.com/datasets/khushikyad001/fake-news-detection)
— 4,000 rows, 24 columns, bundled in [`data/`](data/). Synthetic, which the
dataset page does not say.
