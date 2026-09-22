/**
 * The TypeScript curve engine against the Python one.
 *
 * The port re-implements an eigendecomposition, a bond price and a backtest.
 * Every number below came out of the Python engine and was written to
 * `curve-golden.json` by `site/scripts/generate_curve_demo.py`; nothing here is
 * a hand-typed expectation. If the two ever disagree the demo is lying about
 * what the project computes, which is worse than having no demo.
 */

import { describe, expect, it } from "vitest";

import curveData from "../../data/demos/curve.json";
import golden from "../../data/demos/curve-golden.json";
import {
  type Butterfly,
  type Curve,
  type CurvePayload,
  decodeCurve,
  dailyChanges,
  dv01NeutralWeights,
  factorExposure,
  factorNeutralWeights,
  fitFactors,
  interpolate,
  netDv01,
  parBondDv01,
  runBacktest,
  sliceCurve,
  summarise,
  symmetricEigen,
  varianceShare,
} from "./curve";

const curve: Curve = decodeCurve(curveData as CurvePayload);
const factors = fitFactors(curve);

describe("decoding the payload", () => {
  it("recovers the full history", () => {
    expect(curve.yields.length).toBe(11261);
    expect(curve.tenors.length).toBe(9);
  });

  it("starts and ends where the snapshot does", () => {
    expect(new Date(curve.dates[0]).toISOString().slice(0, 10)).toBe("1981-09-01");
    expect(new Date(curve.dates[curve.dates.length - 1]).toISOString().slice(0, 10)).toBe(
      "2026-09-17",
    );
  });

  it("reverses the delta encoding to real yields", () => {
    // Row one of the committed CSV: 17.01, 17.17, 17.06, ...
    expect(curve.yields[0].slice(0, 3)).toEqual([17.01, 17.17, 17.06]);
  });

  it("has no gap bigger than a long weekend", () => {
    let worst = 0;
    for (let i = 1; i < curve.dates.length; i++) {
      worst = Math.max(worst, (curve.dates[i] - curve.dates[i - 1]) / 86_400_000);
    }
    expect(worst).toBeLessThanOrEqual(10);
  });

  it("slices by date", () => {
    const cut = sliceCurve(curve, Date.parse("2020-01-01T00:00:00Z"));
    expect(cut.yields.length).toBeLessThan(curve.yields.length);
    expect(new Date(cut.dates[0]).getUTCFullYear()).toBe(2020);
  });
});

describe("the eigensolver", () => {
  it("diagonalises a matrix whose answer is known", () => {
    const { values, vectors } = symmetricEigen([
      [2, 1],
      [1, 2],
    ]);
    expect(values[0]).toBeCloseTo(3, 12);
    expect(values[1]).toBeCloseTo(1, 12);
    expect(Math.abs(vectors[0][0])).toBeCloseTo(Math.SQRT1_2, 12);
  });

  it("returns orthonormal vectors", () => {
    const { vectors } = symmetricEigen([
      [4, 1, 0],
      [1, 3, 1],
      [0, 1, 2],
    ]);
    for (const v of vectors) {
      expect(v.reduce((s, x) => s + x * x, 0)).toBeCloseTo(1, 12);
    }
    const dot = vectors[0].reduce((s, x, i) => s + x * vectors[1][i], 0);
    expect(dot).toBeCloseTo(0, 12);
  });

  it("reconstructs the matrix from its own decomposition", () => {
    const m = [
      [6, 2, 1],
      [2, 5, 2],
      [1, 2, 4],
    ];
    const { values, vectors } = symmetricEigen(m);
    for (let i = 0; i < 3; i++) {
      for (let j = 0; j < 3; j++) {
        const rebuilt = values.reduce((s, v, k) => s + v * vectors[k][i] * vectors[k][j], 0);
        expect(rebuilt).toBeCloseTo(m[i][j], 10);
      }
    }
  });
});

describe("factors against Python", () => {
  it("explains the same share of variance", () => {
    factors.explained.forEach((value, i) => {
      expect(value).toBeCloseTo(golden.factors.explained[i], 9);
    });
  });

  it("recovers the same loadings, including their signs", () => {
    factors.loadings.forEach((row, i) => {
      row.forEach((value, j) => {
        expect(value).toBeCloseTo(golden.factors.loadings[i][j], 8);
      });
    });
  });

  it("gets the same factor variances", () => {
    factors.variances.forEach((value, i) => {
      expect(value).toBeCloseTo(golden.factors.variances[i], 11);
    });
  });

  it("puts the curvature trough at the two-year, as the write-up claims", () => {
    const curvature = factors.loadings[2];
    const trough = curvature.indexOf(Math.min(...curvature));
    expect(factors.tenors[trough]).toBe("DGS2");
  });

  it("agrees with Python that three factors explain about 95%", () => {
    const cumulative = factors.explained.reduce((a, b) => a + b, 0);
    expect(cumulative).toBeGreaterThan(0.94);
    expect(cumulative).toBeLessThan(0.97);
  });
});

describe("par bond DV01 against Python", () => {
  it.each(golden.dv01)("matches at $maturity years, $yield%", (row) => {
    expect(parBondDv01(row.yield, row.maturity)).toBeCloseTo(row.dv01, 12);
  });

  it("scales linearly with face", () => {
    expect(parBondDv01(4, 10, 250)).toBeCloseTo(2.5 * parBondDv01(4, 10), 12);
  });

  it("refuses a zero maturity", () => {
    expect(() => parBondDv01(4, 0)).toThrow(/maturity must be positive/);
  });
});

describe("butterfly construction against Python", () => {
  const build = (row: (typeof golden.flies)[number]): Butterfly => {
    const wings: [string, string] = [row.wings[0], row.wings[1]];
    return row.weighting === "dv01"
      ? dv01NeutralWeights(factors, wings, row.belly)
      : factorNeutralWeights(factors, wings, row.belly);
  };

  it.each(golden.flies)("weights $belly between $wings the $weighting way", (row) => {
    const fly = build(row);
    fly.weights.forEach((weight, i) => expect(weight).toBeCloseTo(row.weights[i], 9));
    expect(netDv01(fly)).toBeCloseTo(row.netDv01, 9);
  });

  it.each(golden.flies)("splits $belly/$weighting risk the same way", (row) => {
    varianceShare(build(row), factors).forEach((share, i) => {
      expect(share).toBeCloseTo(row.varianceShare[i], 8);
    });
  });

  it("reproduces the headline: the textbook fly trades almost no curvature", () => {
    const fly = dv01NeutralWeights(factors, ["DGS2", "DGS10"], "DGS5");
    const shares = varianceShare(fly, factors);
    expect(shares[2]).toBeLessThan(0.02);
    expect(shares[0] + shares[1]).toBeGreaterThan(0.95);
  });

  it("reproduces the fix: moving the fly onto the two-year", () => {
    const fly = dv01NeutralWeights(factors, ["DGS1", "DGS5"], "DGS2");
    expect(varianceShare(fly, factors)[2]).toBeGreaterThan(0.9);
    expect(netDv01(fly)).toBeCloseTo(0, 12);
  });

  it("zeroes level and slope when asked to", () => {
    const exposure = factorExposure(
      factors,
      factorNeutralWeights(factors, ["DGS2", "DGS10"], "DGS5").weights,
    );
    expect(exposure[0]).toBeCloseTo(0, 10);
    expect(exposure[1]).toBeCloseTo(0, 10);
  });

  it("refuses a belly outside its wings, like the Python engine does", () => {
    expect(() => dv01NeutralWeights(factors, ["DGS10", "DGS30"], "DGS2")).toThrow(
      /belly between its wings/,
    );
    expect(() => factorNeutralWeights(factors, ["DGS10", "DGS30"], "DGS2")).toThrow(
      /belly between its wings/,
    );
  });

  it("refuses a tenor the curve does not carry", () => {
    expect(() => dv01NeutralWeights(factors, ["DGS2", "DGS99"], "DGS5")).toThrow(/no tenor/);
  });

  it("refuses the same tenor twice, as not being a butterfly at all", () => {
    expect(() => factorNeutralWeights(factors, ["DGS2", "DGS2"], "DGS5")).toThrow(
      /belly between its wings/,
    );
  });

  it("refuses wings that load alike rather than least-squaring them", () => {
    // Unreachable with the real curve once the ordering check is in front of
    // it, so the degenerate factor model is built explicitly -- same as the
    // Python test of the same name.
    const bad = { ...factors, loadings: factors.loadings.map((row) => row.slice()) };
    const two = factors.tenors.indexOf("DGS2");
    const ten = factors.tenors.indexOf("DGS10");
    for (const row of bad.loadings) row[ten] = row[two]!;
    expect(() => factorNeutralWeights(bad, ["DGS2", "DGS10"], "DGS5")).toThrow(
      /not identified/,
    );
  });
});

describe("interpolation", () => {
  it("hits the quoted points", () => {
    expect(interpolate([1, 2, 5], [3, 3.5, 4], 2)).toBeCloseTo(3.5, 12);
  });

  it("is linear between them", () => {
    expect(interpolate([1, 3], [2, 4], 2)).toBeCloseTo(3, 12);
  });

  it("holds flat outside the range rather than extrapolating", () => {
    expect(interpolate([1, 30], [3, 5], 0.1)).toBe(3);
    expect(interpolate([1, 30], [3, 5], 100)).toBe(5);
  });
});

describe("the backtest against Python", () => {
  it.each(golden.backtests)(
    "matches $weighting from $start, rebalanced every $rebalanceDays days, factors on $fittedOn",
    (row) => {
      const window = sliceCurve(curve, Date.parse(`${row.start}T00:00:00Z`));
      // Which curve the factor model is fitted on changes the weights, and for
      // the factor-neutral fly it changes the sign of the answer.
      const basis = row.fittedOn === "full" ? factors : fitFactors(window);
      const fly =
        row.weighting === "dv01"
          ? dv01NeutralWeights(basis, ["DGS2", "DGS10"], "DGS5")
          : factorNeutralWeights(basis, ["DGS2", "DGS10"], "DGS5");
      const result = runBacktest(window, fly, {
        rebalanceDays: row.rebalanceDays,
        costBp: row.costBp,
        rollHorizonDays: 63,
      });
      const performance = summarise(result);

      expect(performance.days).toBe(row.days);
      expect(performance.total).toBeCloseTo(row.total, 6);
      expect(performance.informationRatio).toBeCloseTo(row.informationRatio, 6);
      expect(performance.maxDrawdown).toBeCloseTo(row.maxDrawdown, 6);
      expect(performance.hitRate).toBeCloseTo(row.hitRate, 8);
      expect(result.contribution.directional).toBeCloseTo(row.contribution.directional, 6);
      expect(result.contribution.carry).toBeCloseTo(row.contribution.carry, 6);
      expect(result.contribution.rolldown).toBeCloseTo(row.contribution.rolldown, 6);
      expect(result.contribution.cost).toBeCloseTo(row.contribution.cost, 6);
    },
  );

  it("gives a different answer depending on which curve the factors came from", () => {
    // Not a footnote: fitting the factor model on all forty-five years and
    // then trading only the 2000s is look-ahead, and it flips this result
    // from positive to negative.
    const window = sliceCurve(curve, Date.parse("2000-01-01T00:00:00Z"));
    const settings = { rebalanceDays: 21, costBp: 0.5, rollHorizonDays: 63 };
    const onWindow = summarise(
      runBacktest(window, factorNeutralWeights(fitFactors(window), ["DGS2", "DGS10"], "DGS5"), settings),
    );
    const onEverything = summarise(
      runBacktest(window, factorNeutralWeights(factors, ["DGS2", "DGS10"], "DGS5"), settings),
    );
    expect(onWindow.total).toBeGreaterThan(0);
    expect(onEverything.total).toBeLessThan(0);
  });

  it("splits the P&L into parts that add to the total", () => {
    const window = sliceCurve(curve, Date.parse("2015-01-01T00:00:00Z"));
    const result = runBacktest(window, dv01NeutralWeights(factors, ["DGS2", "DGS10"], "DGS5"), {
      rebalanceDays: 21,
      costBp: 0.5,
      rollHorizonDays: 63,
    });
    result.total.forEach((total, i) => {
      const parts =
        result.directional[i] + result.carry[i] + result.rolldown[i] + result.cost[i];
      expect(parts).toBeCloseTo(total, 12);
    });
  });

  it("charges more when it trades more often", () => {
    const window = sliceCurve(curve, Date.parse("2015-01-01T00:00:00Z"));
    const fly = dv01NeutralWeights(factors, ["DGS2", "DGS10"], "DGS5");
    const rare = runBacktest(window, fly, { rebalanceDays: 63, costBp: 1, rollHorizonDays: 63 });
    const often = runBacktest(window, fly, { rebalanceDays: 5, costBp: 1, rollHorizonDays: 63 });
    expect(often.contribution.cost).toBeLessThan(rare.contribution.cost);
  });

  it("refuses a single day", () => {
    const oneDay = { ...curve, dates: curve.dates.slice(0, 1), yields: curve.yields.slice(0, 1) };
    expect(() =>
      runBacktest(oneDay, dv01NeutralWeights(factors, ["DGS2", "DGS10"], "DGS5"), {
        rebalanceDays: 21,
        costBp: 0.5,
        rollHorizonDays: 63,
      }),
    ).toThrow(/at least two days/);
  });
});

describe("daily changes", () => {
  it("has one fewer row than the curve", () => {
    expect(dailyChanges(curve).length).toBe(curve.yields.length - 1);
  });

  it("is a first difference", () => {
    const changes = dailyChanges(curve);
    expect(changes[0][0]).toBeCloseTo(curve.yields[1][0] - curve.yields[0][0], 12);
  });
});
