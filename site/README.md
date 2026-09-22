# Portfolio site

The project showcase at
**[anita-huangz.github.io](https://anita-huangz.github.io/)**.

![The portfolio site](docs/screenshot.png)

A static React + Vite single-page app: a filterable grid of every project in
the repository, with a detail panel per project covering the design decisions,
the bugs that were fixed, and real captured output.

Six projects also carry a **live demo** that runs in the browser — an
interactive factor backtest, an earnings-drift scatter, trie search, a
timetable builder, a playable card game, and an LRU eviction visualiser.

```bash
npm install
npm run dev       # http://localhost:5173
npm test          # 738 tests: the ports against the Python's answers
npm run build     # production bundle for GitHub Pages
npm run preview   # serve the built bundle locally
```

## Live demos and the drift problem

The demos re-implement logic that already exists in Python, which risks the two
quietly disagreeing. Two things keep them honest:

1. **`scripts/generate_demo_data.py` imports the projects themselves** to
   produce both the data the browser needs (real prices, real earnings
   surprises, the course catalogue) and *golden fixtures* — inputs paired with
   the answer the Python gave.
2. **`src/demos/lib/ports.test.ts` checks every port against those fixtures**:
   400 scored poker hands, every course pair's conflict verdict, every trie
   prefix and wildcard query, and six full factor backtests.

This is not ceremony. The cross-check caught a real off-by-one in the factor
port — `index > LOOKBACK` where the Python guards on `len(history) > LOOKBACK`,
which starts a day late and changes the first ranking of the backtest.

Regenerate after changing any project's behaviour:

```bash
python scripts/generate_demo_data.py    # needs the project venvs on the path
npm test
```

## Notes

- **The terminal output is real.** It was captured by running each project and
  pasted into [`src/data/projects.ts`](src/data/projects.ts), not written by
  hand. When a project's behaviour changes, re-run it and update the string.
- **Project content is data, not markup.** Adding a project means one entry in
  `projects.ts`; no component changes.
- **Category colour is always paired with a text label**, so identity never
  rests on hue alone. Light and dark are both selected from a validated palette
  against their own surface rather than being an automatic inversion.
- **No base path.** This is a GitHub *user* site (the repository is named
  `anita-huangz.github.io`), so it publishes at the domain root. A project
  page would need `base: "/<repo>/"` instead.

Deployed by [`.github/workflows/pages.yml`](../.github/workflows/pages.yml) on
every push to `main` that touches `site/`.
