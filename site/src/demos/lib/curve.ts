/**
 * The Yield Curve Lab engine, ported to TypeScript so the demo runs in the
 * browser with no server.
 *
 * This re-implements a principal-component decomposition, a bond price and a
 * backtest. Those are not things to eyeball: every function here is checked
 * against the Python engine's answers in `curve.test.ts`, on fixtures the
 * Python generated. A port that is close is a port that is wrong.
 *
 * The one piece with no direct NumPy equivalent is the eigensolver. `eigh` on a
 * 9x9 symmetric covariance is a cyclic Jacobi rotation here, which converges to
 * machine precision in a handful of sweeps for a matrix this size and needs no
 * dependency.
 */

export interface CurvePayload {
  tenors: string[];
  labels: string[];
  maturities: number[];
  start: string;
  dayOffsets: number[];
  yieldsBp: number[][];
}

export interface Curve {
  tenors: string[];
  labels: string[];
  maturities: number[];
  /** Milliseconds since epoch, one per observation. */
  dates: number[];
  /** Percent, [day][tenor]. */
  yields: number[][];
}

const DAY_MS = 86_400_000;
const BP = 1e-4;
const COUPONS_PER_YEAR = 2;
const TRADING_DAYS = 252;

function cumulative(deltas: number[]): number[] {
  const out = new Array<number>(deltas.length);
  let running = 0;
  for (let i = 0; i < deltas.length; i++) {
    running += deltas[i];
    out[i] = running;
  }
  return out;
}

/** Undo the delta encoding the generator applied. */
export function decodeCurve(payload: CurvePayload): Curve {
  const startMs = Date.parse(`${payload.start}T00:00:00Z`);
  const dates = cumulative(payload.dayOffsets).map((offset) => startMs + offset * DAY_MS);
  const perTenor = payload.yieldsBp.map((deltas) => cumulative(deltas));
  const yields = dates.map((_, day) => perTenor.map((series) => series[day] / 100));
  return {
    tenors: payload.tenors,
    labels: payload.labels,
    maturities: payload.maturities,
    dates,
    yields,
  };
}

export function sliceCurve(curve: Curve, startMs?: number, endMs?: number): Curve {
  const keep: number[] = [];
  for (let i = 0; i < curve.dates.length; i++) {
    if (startMs !== undefined && curve.dates[i] < startMs) continue;
    if (endMs !== undefined && curve.dates[i] > endMs) continue;
    keep.push(i);
  }
  return { ...curve, dates: keep.map((i) => curve.dates[i]), yields: keep.map((i) => curve.yields[i]) };
}

/** First differences, [day][tenor]. */
export function dailyChanges(curve: Curve): number[][] {
  const out: number[][] = [];
  for (let day = 1; day < curve.yields.length; day++) {
    out.push(curve.yields[day].map((value, tenor) => value - curve.yields[day - 1][tenor]));
  }
  return out;
}

// --------------------------------------------------------------------------
// Eigen decomposition
// --------------------------------------------------------------------------

/**
 * Eigenvalues and eigenvectors of a symmetric matrix, largest first.
 *
 * Cyclic Jacobi: repeatedly zero the largest off-diagonal entry with a plane
 * rotation. For a 9x9 it converges in well under the iteration cap, and the
 * result is accurate to machine precision -- which matters, because the third
 * component here carries 3.9% of the variance and a sloppy solver mixes it
 * with the fourth.
 */
export function symmetricEigen(input: number[][]): { values: number[]; vectors: number[][] } {
  const n = input.length;
  const a = input.map((row) => row.slice());
  let v: number[][] = Array.from({ length: n }, (_, i) =>
    Array.from({ length: n }, (_, j) => (i === j ? 1 : 0)),
  );

  for (let sweep = 0; sweep < 100; sweep++) {
    let off = 0;
    for (let p = 0; p < n; p++) {
      for (let q = p + 1; q < n; q++) off += a[p][q] * a[p][q];
    }
    if (off < 1e-30) break;

    for (let p = 0; p < n; p++) {
      for (let q = p + 1; q < n; q++) {
        if (Math.abs(a[p][q]) < 1e-300) continue;
        const theta = (a[q][q] - a[p][p]) / (2 * a[p][q]);
        const t = Math.sign(theta || 1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
        const c = 1 / Math.sqrt(t * t + 1);
        const s = t * c;
        for (let k = 0; k < n; k++) {
          const akp = a[k][p];
          const akq = a[k][q];
          a[k][p] = c * akp - s * akq;
          a[k][q] = s * akp + c * akq;
        }
        for (let k = 0; k < n; k++) {
          const apk = a[p][k];
          const aqk = a[q][k];
          a[p][k] = c * apk - s * aqk;
          a[q][k] = s * apk + c * aqk;
        }
        for (let k = 0; k < n; k++) {
          const vkp = v[k][p];
          const vkq = v[k][q];
          v[k][p] = c * vkp - s * vkq;
          v[k][q] = s * vkp + c * vkq;
        }
      }
    }
  }

  const order = Array.from({ length: n }, (_, i) => i).sort((x, y) => a[y][y] - a[x][x]);
  return {
    values: order.map((i) => a[i][i]),
    // Column i of `v` is eigenvector i; return them as rows.
    vectors: order.map((i) => v.map((row) => row[i])),
  };
}

// --------------------------------------------------------------------------
// Factors
// --------------------------------------------------------------------------

export const FACTOR_NAMES = ["level", "slope", "curvature"] as const;

export interface Factors {
  tenors: string[];
  maturities: number[];
  /** [component][tenor] */
  loadings: number[][];
  explained: number[];
  meanChange: number[];
  /** Variance of each component's daily score. */
  variances: number[];
}

function median(values: number[]): number {
  const sorted = values.slice().sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/**
 * Pin each eigenvector's arbitrary sign to a readable convention: level is
 * "yields up", slope is "long end up", curvature is "wings up".
 */
function orient(loadings: number[][], maturities: number[]): number[][] {
  const fixed = loadings.map((row) => row.slice());
  if (fixed.length >= 1 && fixed[0].reduce((a, b) => a + b, 0) < 0) {
    fixed[0] = fixed[0].map((x) => -x);
  }
  if (fixed.length >= 2 && fixed[1][fixed[1].length - 1] < fixed[1][0]) {
    fixed[1] = fixed[1].map((x) => -x);
  }
  if (fixed.length >= 3) {
    const target = median(maturities);
    let belly = 0;
    for (let i = 1; i < maturities.length; i++) {
      if (Math.abs(maturities[i] - target) < Math.abs(maturities[belly] - target)) belly = i;
    }
    if (fixed[2][belly] > 0) fixed[2] = fixed[2].map((x) => -x);
  }
  return fixed;
}

export function fitFactors(curve: Curve, nComponents = 3): Factors {
  const changes = dailyChanges(curve);
  const n = curve.tenors.length;
  if (changes.length <= n) throw new Error("too few daily changes to estimate a covariance");

  const mean = new Array<number>(n).fill(0);
  for (const row of changes) for (let i = 0; i < n; i++) mean[i] += row[i] / changes.length;

  // Sample covariance, divisor n-1, matching numpy.cov's default.
  const cov: number[][] = Array.from({ length: n }, () => new Array<number>(n).fill(0));
  for (const row of changes) {
    for (let i = 0; i < n; i++) {
      for (let j = i; j < n; j++) {
        cov[i][j] += ((row[i] - mean[i]) * (row[j] - mean[j])) / (changes.length - 1);
      }
    }
  }
  for (let i = 0; i < n; i++) for (let j = 0; j < i; j++) cov[i][j] = cov[j][i];

  const { values, vectors } = symmetricEigen(cov);
  const total = values.reduce((a, b) => a + b, 0);
  const available = Math.min(nComponents, n);
  const loadings = orient(vectors.slice(0, available), curve.maturities);

  const factors: Factors = {
    tenors: curve.tenors,
    maturities: curve.maturities,
    loadings,
    explained: values.slice(0, available).map((v) => v / total),
    meanChange: mean,
    variances: [],
  };
  factors.variances = factorVariances(factors, changes);
  return factors;
}

/** Project daily changes onto the factors. [day][component] */
export function factorScores(factors: Factors, changes: number[][]): number[][] {
  return changes.map((row) =>
    factors.loadings.map((loading) =>
      loading.reduce((sum, weight, i) => sum + weight * (row[i] - factors.meanChange[i]), 0),
    ),
  );
}

function factorVariances(factors: Factors, changes: number[][]): number[] {
  const scores = factorScores(factors, changes);
  return factors.loadings.map((_, component) => {
    const column = scores.map((row) => row[component]);
    const mean = column.reduce((a, b) => a + b, 0) / column.length;
    return column.reduce((sum, x) => sum + (x - mean) ** 2, 0) / (column.length - 1);
  });
}

/** A trade's exposure to each factor: loadings dotted with DV01 weights. */
export function factorExposure(factors: Factors, weights: number[]): number[] {
  return factors.loadings.map((loading) =>
    loading.reduce((sum, value, i) => sum + value * weights[i], 0),
  );
}

// --------------------------------------------------------------------------
// Bond maths and trade construction
// --------------------------------------------------------------------------

/** Price change per basis point for a bond trading at par, per 100 face. */
export function parBondDv01(yieldPct: number, maturityYears: number, face = 100): number {
  if (maturityYears <= 0) throw new Error("maturity must be positive");
  const y = yieldPct / 100;

  if (maturityYears < 1 / COUPONS_PER_YEAR) {
    // A bill: one payment left, simple discount.
    return (maturityYears / (1 + y * maturityYears)) * face * BP;
  }

  const periods = Math.round(maturityYears * COUPONS_PER_YEAR);
  const periodic = y / COUPONS_PER_YEAR;
  let price = 0;
  let weighted = 0;
  for (let k = 1; k <= periods; k++) {
    const flow = face * periodic + (k === periods ? face : 0);
    const discount = Math.pow(1 + periodic, -k);
    price += flow * discount;
    weighted += (k / COUPONS_PER_YEAR) * flow * discount;
  }
  const macaulay = weighted / price;
  return (macaulay / (1 + periodic)) * price * BP;
}

export interface Butterfly {
  tenors: string[];
  weights: number[];
  wings: [string, string];
  belly: string;
  label: string;
  weighting: "dv01" | "factor";
}

function legLabel(maturity: number): string {
  return maturity < 1 ? `${maturity * 12}m` : `${maturity}s`;
}

function flyLabel(factors: Factors, wings: [string, string], belly: string, kind: string): string {
  const at = (t: string) => factors.maturities[factors.tenors.indexOf(t)];
  return `${legLabel(at(wings[0]))}${legLabel(at(belly))}${legLabel(at(wings[1]))} ${kind}`;
}

export function dv01NeutralWeights(
  factors: Factors,
  wings: [string, string],
  belly: string,
): Butterfly {
  const weights = new Array<number>(factors.tenors.length).fill(0);
  weights[factors.tenors.indexOf(belly)] = -1;
  for (const wing of wings) weights[factors.tenors.indexOf(wing)] = 0.5;
  return {
    tenors: factors.tenors,
    weights,
    wings,
    belly,
    weighting: "dv01",
    label: flyLabel(factors, wings, belly, "DV01-neutral"),
  };
}

export function factorNeutralWeights(
  factors: Factors,
  wings: [string, string],
  belly: string,
): Butterfly {
  const bellyIndex = factors.tenors.indexOf(belly);
  const wingIndices = wings.map((w) => factors.tenors.indexOf(w));

  // Two equations, two unknowns: zero the level and slope exposures.
  const a = factors.loadings[0][wingIndices[0]];
  const b = factors.loadings[0][wingIndices[1]];
  const c = factors.loadings[1][wingIndices[0]];
  const d = factors.loadings[1][wingIndices[1]];
  const determinant = a * d - b * c;
  if (Math.abs(determinant) < 1e-12) {
    throw new Error("those wings load almost identically; the weights are not identified");
  }
  const p = factors.loadings[0][bellyIndex];
  const q = factors.loadings[1][bellyIndex];
  const x = (p * d - b * q) / determinant;
  const y = (a * q - c * p) / determinant;

  const weights = new Array<number>(factors.tenors.length).fill(0);
  weights[bellyIndex] = -1;
  weights[wingIndices[0]] = x;
  weights[wingIndices[1]] = y;
  return {
    tenors: factors.tenors,
    weights,
    wings,
    belly,
    weighting: "factor",
    label: flyLabel(factors, wings, belly, "factor-neutral"),
  };
}

export function netDv01(fly: Butterfly): number {
  return fly.weights.reduce((a, b) => a + b, 0);
}

/** Share of a trade's P&L variance attributable to each factor. */
export function varianceShare(fly: Butterfly, factors: Factors): number[] {
  const exposure = factorExposure(factors, fly.weights);
  const contributions = exposure.map((e, i) => e * e * factors.variances[i]);
  const total = contributions.reduce((a, b) => a + b, 0);
  if (total <= 0) throw new Error("this trade has no factor risk at all");
  return contributions.map((c) => c / total);
}

// --------------------------------------------------------------------------
// Backtest
// --------------------------------------------------------------------------

export interface BacktestSettings {
  rebalanceDays: number;
  costBp: number;
  rollHorizonDays: number;
}

export interface BacktestResult {
  dates: number[];
  directional: number[];
  carry: number[];
  rolldown: number[];
  cost: number[];
  total: number[];
  equity: number[];
  rebalances: number;
  contribution: { directional: number; carry: number; rolldown: number; cost: number };
}

/** Linear in maturity, flat outside the quoted range. */
export function interpolate(maturities: number[], yields: number[], target: number): number {
  if (target <= maturities[0]) return yields[0];
  const last = maturities.length - 1;
  if (target >= maturities[last]) return yields[last];
  let i = 0;
  while (i < last && maturities[i + 1] < target) i++;
  const span = maturities[i + 1] - maturities[i];
  const weight = (target - maturities[i]) / span;
  return yields[i] + weight * (yields[i + 1] - yields[i]);
}

function legFaces(row: number[], weights: number[], maturities: number[]): number[] {
  return weights.map((weight, i) =>
    weight === 0 ? 0 : (weight / parBondDv01(row[i], maturities[i])) * 100,
  );
}

export function runBacktest(
  curve: Curve,
  fly: Butterfly,
  settings: BacktestSettings,
): BacktestResult {
  if (curve.yields.length < 2) throw new Error("a backtest needs at least two days");
  const { maturities } = curve;
  const horizon = settings.rollHorizonDays / TRADING_DAYS;

  let faces = legFaces(curve.yields[0], fly.weights, maturities);
  let rebalances = 1;
  const grossDv01 = fly.weights.reduce((a, b) => a + Math.abs(b), 0);

  const result: BacktestResult = {
    dates: [], directional: [], carry: [], rolldown: [], cost: [], total: [], equity: [],
    rebalances: 0,
    contribution: { directional: 0, carry: 0, rolldown: 0, cost: 0 },
  };

  let running = 0;
  for (let day = 1; day < curve.yields.length; day++) {
    const previous = curve.yields[day - 1];
    const current = curve.yields[day];

    let directional = 0;
    let carry = 0;
    let rolldown = 0;
    for (let i = 0; i < maturities.length; i++) {
      if (faces[i] === 0) continue;
      const changeBp = (current[i] - previous[i]) * 100;
      directional -= (faces[i] / 100) * parBondDv01(previous[i], maturities[i]) * changeBp;
      carry += (faces[i] * previous[i]) / 100 / TRADING_DAYS;
      if (horizon < maturities[i]) {
        const aged = maturities[i] - horizon;
        const agedYield = interpolate(maturities, previous, aged);
        const duration = parBondDv01(agedYield, aged) / (100 * BP);
        const totalRollBp = duration * (previous[i] - agedYield) * 100;
        rolldown += (faces[i] * totalRollBp * BP) / settings.rollHorizonDays;
      }
    }

    let cost = 0;
    if (day % settings.rebalanceDays === 0) {
      faces = legFaces(curve.yields[day], fly.weights, maturities);
      cost = settings.costBp * grossDv01;
      rebalances += 1;
    }
    // Opening the position pays the spread like any other trade.
    if (day === 1) cost += settings.costBp * grossDv01;

    const total = directional + carry + rolldown - cost;
    running += total;
    result.dates.push(curve.dates[day]);
    result.directional.push(directional);
    result.carry.push(carry);
    result.rolldown.push(rolldown);
    result.cost.push(-cost);
    result.total.push(total);
    result.equity.push(running);
  }

  result.rebalances = rebalances;
  result.contribution = {
    directional: result.directional.reduce((a, b) => a + b, 0),
    carry: result.carry.reduce((a, b) => a + b, 0),
    rolldown: result.rolldown.reduce((a, b) => a + b, 0),
    cost: result.cost.reduce((a, b) => a + b, 0),
  };
  return result;
}

// --------------------------------------------------------------------------
// Risk
// --------------------------------------------------------------------------

export interface Performance {
  days: number;
  total: number;
  informationRatio: number;
  annualisedVolatility: number;
  hitRate: number;
  maxDrawdown: number;
  drawdownStart: number | null;
  drawdownTrough: number | null;
}

export function summarise(result: BacktestResult): Performance {
  const pnl = result.total;
  if (pnl.length < 2) throw new Error("need at least two days of P&L");
  const mean = pnl.reduce((a, b) => a + b, 0) / pnl.length;
  const variance = pnl.reduce((s, x) => s + (x - mean) ** 2, 0) / (pnl.length - 1);
  const volatility = Math.sqrt(variance);

  let peak = -Infinity;
  let peakIndex = 0;
  let depth = 0;
  let startIndex: number | null = null;
  let troughIndex: number | null = null;
  for (let i = 0; i < result.equity.length; i++) {
    if (result.equity[i] > peak) {
      peak = result.equity[i];
      peakIndex = i;
    }
    const under = result.equity[i] - peak;
    if (under < depth) {
      depth = under;
      startIndex = peakIndex;
      troughIndex = i;
    }
  }

  return {
    days: pnl.length,
    total: pnl.reduce((a, b) => a + b, 0),
    informationRatio: volatility > 0 ? (mean / volatility) * Math.sqrt(TRADING_DAYS) : 0,
    annualisedVolatility: volatility * Math.sqrt(TRADING_DAYS),
    hitRate: pnl.filter((x) => x > 0).length / pnl.length,
    maxDrawdown: depth,
    drawdownStart: startIndex === null ? null : result.dates[startIndex],
    drawdownTrough: troughIndex === null ? null : result.dates[troughIndex],
  };
}
