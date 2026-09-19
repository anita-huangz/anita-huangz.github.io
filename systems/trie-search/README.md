# Trie Search

Crawl a website, index every word into a trie, and search it by prefix or with
a single-character wildcard.

```
$ trie-search https://scrapple.fly.dev/parks --depth 2 --query "par?"
Crawled 34 page(s), 8,112 words.
Indexed 1,204 distinct words.

                    Results for 'par?'
┏━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  Word ┃ Pages ┃ URL(s)                                  ┃
┡━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│  park │    31 │ https://scrapple.fly.dev/parks          │
│  part │     4 │ https://scrapple.fly.dev/parks/12       │
└───────┴───────┴─────────────────────────────────────────┘
```

Without `--query` it drops into an interactive prompt.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
trie-search https://example.com --depth 1
trie-bench      # the trie against a dictionary scan
trie-bench --index   # what positions and stemming cost
trie-search https://example.com --stem --query '"park hours"'
pytest -q       # 195 tests, no network
ruff check .
```

## Layout

```
src/trie_search/
  trie.py      the trie: MutableMapping + prefix and wildcard search
  fetch.py     HTTP, HTML extraction, tokenizing
  crawler.py   breadth-first crawl, index building
  cli.py       argument parsing, rich tables, interactive prompt
```

## How the trie works

Each node has up to 27 children: one per letter `a-z`, plus one bucket for
everything else. Keys fold into that alphabet, which makes the trie
**case-insensitive** and means `don't` and `don_t` are the same key.

That's lossy, and it's the trade: a fixed small alphabet is what keeps wildcard
search a simple bounded walk instead of a scan. `original_keys()` gives back
the text as it was inserted when you need it.

## Is the trie worth it? Measured, not assumed

A trie is more code than a dictionary, and it is lossy — the fixed alphabet
above folds case and punctuation away. That trade only pays if prefix and
wildcard lookup are genuinely cheaper than scanning the keys, so the project
measures it rather than asserting it:

```
$ trie-bench
Prefix 'ab' and wildcard '?ar?', best of 5. Milliseconds.

                      PREFIX                       WILDCARD
    words      trie     scan     hits      trie     scan     hits
------------------------------------------------------------------------
    5,000     0.008    0.056       12     0.013    0.284        0
   25,000     0.026    0.265       41     0.020    1.388        5
  100,000     0.095    1.096      141     0.031    5.825       22

Over a 20x larger vocabulary the scan got 20x slower and the trie 12x.
```

The ratio is not the interesting number — it moves around with how many words
happen to match. The shape of the columns is. **The scan grows with the
vocabulary** because it visits every key: 20× the words, 20× the time, dead
linear. **The trie grows with the answer** — its 12× tracks the hit count
going from 12 to 141, not the vocabulary going from 5,000 to 100,000.

That is the whole case for the data structure, and it is why the wildcard
column is the more lopsided of the two: a regex scan still touches all 100,000
keys to return 22 of them, while the trie's `?` is a bounded branch over 27
children at one depth.

`tests/test_benchmark.py` asserts the trie and the scan return **the same
words** for every prefix and pattern it tries. A faster answer that disagreed
with the obvious one would not be an optimisation.

## Phrases, and why a word index cannot answer one

Searching `park hours` finds pages containing both words. That is not the same
question as "which pages say *park hours*", and on a real corpus the difference
is most of the results:

```
$ trie-search https://example.com --query '"park hours"'
```

A word index physically cannot tell them apart. `word -> {urls}` records that a
page contains a term, not where, and adjacency is a fact about *where*. So the
posting list now carries offsets:

```python
Posting(counts={"/a": 2}, positions={"/a": [4, 18]})
```

Matching walks the first term's offsets and probes the others for `start + 1`,
`start + 2` and so on. Membership is tested against sets, so the cost tracks
the occurrences of the term being anchored on, not the length of the page —
looking for "the quick brown fox" on a page with a thousand `the`s is still a
thousand constant-time probes.

The phrase is then scored **as a single term**: its frequency is the number of
adjacent runs, and its document frequency is the number of pages containing
one. Summing the two words' BM25 scores would rank a page mentioning `park`
forty times and `hours` thirty times above one that actually says `park hours`,
which is the bug the feature exists to avoid.

Positions are optional, because they are not free:

```
$ trie-bench --index

400 pages x 600 words = 240,000 tokens.

index                     terms      payload  vs counts     build
------------------------------------------------------------------
counts only                 462        102 KB       1.0x      16 ms
with positions              462      1,977 KB      19.4x      22 ms
positions + stemming        340      1,927 KB      18.9x     426 ms
```

**Nineteen times the payload.** Counts cost one entry per distinct term per
page; positions cost one per *token*, so the gap widens with page length rather
than with vocabulary. `--no-positions` builds the smaller index, and a phrase
query against it raises `MissingPositions` with the reason rather than
returning an empty list that looks like "no matches".

## Stemming: park, parks, parking

Without it those are three unrelated keys, and a search for one misses pages
that only use another. The wildcard partly covers this — `par*` finds all three
— but only if the searcher thinks to type it, and it over-matches badly:
`par*` also returns `parliament`, `parenthesis` and `parasite`.

`--stem` folds words to their Porter stem at index time and folds the query the
same way:

```
                   without --stem              with --stem
park        ->     /a                          /a  /b  /c
parks       ->     /b                          /a  /b  /c
parking     ->     /a  /c                      /a  /b  /c
parked      ->     /c                          /a  /b  /c
```

`stem.py` is Porter's 1980 algorithm written out — the measure function, the
five steps, the `*o` condition and all. It agrees with NLTK's
`PorterStemmer(mode=ORIGINAL_ALGORITHM)` on **all 235,974 words** in the system
dictionary; `tests/porter_reference.json` pins 4,000 of those so the suite
checks it without taking a dependency on NLTK.

Deliberately the 1980 paper and not Porter's later revisions. He went on to add
`BLI -> BLE` and `LOGI -> LOG`, which change about one word in 220 — every
`-ology`, and words like `accessibly`. Either set is defensible; implementing
one while citing the other is not.

**What it costs.** Stemming is a heuristic, and it conflates words that are
genuinely different: `universe`, `university` and `universal` all reduce to
`univers`. Stems are often not words — `happy` becomes `happi`. And the
algorithm is **not idempotent**: `abase` stems to `abas`, which stems again to
`aba`. That is harmless here because the index and the query are each folded
exactly once, and there is a test pinning that invariant rather than a comment
asserting it. It is also why stemming is opt-in.

## Bugs this version fixes

**`__iter__` yielded `(key, value)` pairs instead of keys.**

`MutableMapping` builds `keys()`, `values()`, and `items()` on top of
`__iter__` by doing `self[element]` for each element yielded. Yielding a tuple
made every one of those raise `KeyError`, and `dict(trie)` didn't work either.
The class claimed to be a mapping and failed the mapping contract.

**Wildcard search matched `*` while everything documented `?`.**

The docstring said `c?t would match 'cat', 'cut', 'cot'`; the implementation
checked `if char == '*'`. Every documented example returned nothing.

**The visited-URL set was a module-level global.**

```python
_seen_already = set()      # module scope
```

So the *second* crawl in a process raised "already seen this run" on every URL
and returned nothing. It also made the crawler untestable, since state leaked
between tests. The visited set now belongs to the crawl.

**Script and style bodies were indexed as words.** `text_content()` includes
them, so a page's JavaScript became searchable text.

**Adjacent elements were glued together.** `text_content()` concatenates with
no separator, so `<a>C</a><p>alpha page</p>` produced `Calpha page` — "C" and
"alpha" both became unfindable. Text nodes are now joined with a space.

**Fetch failures were silently swallowed** by a bare `except: continue`, so a
crawl where every page 500'd was indistinguishable from a site with no content.
Failures are now collected in `CrawlResult.failures` and reported.

Also: URL fragments are stripped before dedup (`/page` and `/page#section` are
one document), off-site links are not followed, and `max_pages` caps a runaway
crawl.

## Notes

- Crawling is restricted to an allowlist of URL prefixes, defaulting to the
  start URL. It's a guardrail against wandering off a test site, not a security
  boundary.
- `robots.txt` is not consulted and there is no rate limiting. Point this at
  test sites.
- Ranking is BM25 over term frequency and page length; see the section above
  for why the trie and the corpus are separate structures.
- Phrase search needs `positions=True`, which is the default for
  `build_search_index` and off under `--no-positions`.
- Stemming is off by default. On, it is Porter's algorithm and the index holds
  stems rather than surface forms, so `original_keys()` is how you recover what
  was actually written on the page.
