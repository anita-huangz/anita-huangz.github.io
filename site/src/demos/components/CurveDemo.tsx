import { useMemo, useState } from "react";

import {
  type Butterfly,
  type CurvePayload,
  decodeCurve,
  dv01NeutralWeights,
  factorNeutralWeights,
  fitFactors,
  netDv01,
  runBacktest,
  sliceCurve,
  summarise,
  varianceShare,
} from "../lib/curve";
import { useDemoData } from "../useDemoData";
import { BarChart, LineChart, ScatterChart, type Series } from "./Chart";
import { Loading } from "./Loading";
import { Term } from "./Term";

interface ForecastRun {
  factor: string;
  horizonDays: number;
  r2: number;
  directionalAccuracy: number;
  dmStatistic: number;
  dmPValue: number;
  beatsBaseline: boolean;
  nFeatures: number;
  testDays: number;
  /** [actual, predicted] pairs. Typed loosely because a JSON import
   *  widens fixed-length tuples to arrays. */
  scatter: number[][];
}

interface ForecastFile {
  model: string;
  folds: number;
  runs: ForecastRun[];
}

// Level / slope / curvature. Blue, green and orange rather than a blue-to-
// purple run: these three are read against each other on the same axes, and
// the site has no --sys or --bad, which is how the slope series rendered as
// an invisible bar the first time round.
const FACTOR_COLOUR = ["var(--ai)", "var(--se)", "var(--ds)"];
const PANELS = [
  { id: "trade", label: "What the fly trades" },
  { id: "backtest", label: "What it earned" },
  { id: "forecast", label: "Can it be forecast?" },
] as const;

type PanelId = (typeof PANELS)[number]["id"];

const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
const money = (v: number) => `$${Math.round(v).toLocaleString()}`;
const year = (ms: number) => new Date(ms).getUTCFullYear();

export function CurveDemo() {
  const curveFile = useDemoData<CurvePayload>(() => import("../../data/demos/curve.json"));
  const forecasts = useDemoData<ForecastFile>(
    () => import("../../data/demos/curve-forecasts.json"),
  );
  if (!curveFile || !forecasts) {
    return <Loading label="Loading forty-five years of the Treasury curve…" />;
  }
  return <Configured payload={curveFile} forecasts={forecasts} />;
}

function Configured({
  payload,
  forecasts,
}: {
  payload: CurvePayload;
  forecasts: ForecastFile;
}) {
  const [panel, setPanel] = useState<PanelId>("trade");

  const [startYear, setStartYear] = useState(2000);
  const [shortWing, setShortWing] = useState("DGS2");
  const [belly, setBelly] = useState("DGS5");
  const [longWing, setLongWing] = useState("DGS10");
  const [weighting, setWeighting] = useState<"dv01" | "factor">("dv01");
  const [rebalanceDays, setRebalanceDays] = useState(21);
  const [costBp, setCostBp] = useState(0.5);
  // Fitting the factor model on all forty-five years and then trading only a
  // slice of them is look-ahead. It defaults to off, and turning it on flips
  // the factor-neutral result from +$143 to -$232.
  const [lookAhead, setLookAhead] = useState(false);

  const curve = useMemo(() => decodeCurve(payload), [payload]);
  const window = useMemo(
    () => sliceCurve(curve, Date.parse(`${startYear}-01-01T00:00:00Z`)),
    [curve, startYear],
  );
  const allFactors = useMemo(() => fitFactors(curve), [curve]);
  // The weights a trader could actually have set on day one use only the data
  // available by then, which is the backtest window.
  const windowFactors = useMemo(
    () => (window.yields.length > 300 ? fitFactors(window) : allFactors),
    [window, allFactors],
  );
  // The risk decomposition is a description of all forty-five years, and it is
  // the number quoted in the write-up directly above this demo, so it always
  // uses the full history. Only the *backtest* cares which curve taught the
  // weights, because only it is claiming a trader could have set them.
  const factors = allFactors;
  const tradingFactors = lookAhead ? allFactors : windowFactors;

  const [forecastFactor, setForecastFactor] = useState("curvature");
  const [horizon, setHorizon] = useState(5);

  const order = (t: string) => factors.maturities[factors.tenors.indexOf(t)];
  const legsValid = order(shortWing) < order(belly) && order(belly) < order(longWing);

  const build = (basis: typeof factors): Butterfly | null => {
    if (!legsValid) return null;
    const wings: [string, string] = [shortWing, longWing];
    try {
      return weighting === "dv01"
        ? dv01NeutralWeights(basis, wings, belly)
        : factorNeutralWeights(basis, wings, belly);
    } catch {
      return null;
    }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const fly = useMemo(() => build(factors), [factors, shortWing, longWing, belly, weighting, legsValid]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const tradedFly = useMemo(
    () => build(tradingFactors),
    [tradingFactors, shortWing, longWing, belly, weighting, legsValid],
  );

  const shares = useMemo(() => (fly ? varianceShare(fly, factors) : null), [fly, factors]);

  const backtest = useMemo(() => {
    if (!tradedFly || window.yields.length < 30) return null;
    const result = runBacktest(window, tradedFly, { rebalanceDays, costBp, rollHorizonDays: 63 });
    return { result, performance: summarise(result) };
  }, [window, tradedFly, rebalanceDays, costBp]);

  const run = forecasts.runs.find(
    (r) => r.factor === forecastFactor && r.horizonDays === horizon,
  );

  return (
    <div className="demo">
      <div className="demo-controls">
        <div className="control" role="group" aria-label="Panel">
          {PANELS.map((p) => (
            <button
              key={p.id}
              className={`chip${panel === p.id ? " primary" : ""}`}
              aria-pressed={panel === p.id}
              onClick={() => setPanel(p.id)}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {panel !== "forecast" && (
        <div className="demo-controls">
          <label className="control">
            <span className="control-label">Short wing</span>
            <select value={shortWing} onChange={(e) => setShortWing(e.target.value)}>
              {factors.tenors.map((t, i) => (
                <option key={t} value={t}>
                  {curve.labels[i]}
                </option>
              ))}
            </select>
          </label>
          <label className="control">
            <span className="control-label">Belly</span>
            <select value={belly} onChange={(e) => setBelly(e.target.value)}>
              {factors.tenors.map((t, i) => (
                <option key={t} value={t}>
                  {curve.labels[i]}
                </option>
              ))}
            </select>
          </label>
          <label className="control">
            <span className="control-label">Long wing</span>
            <select value={longWing} onChange={(e) => setLongWing(e.target.value)}>
              {factors.tenors.map((t, i) => (
                <option key={t} value={t}>
                  {curve.labels[i]}
                </option>
              ))}
            </select>
          </label>
          <label className="control">
            <span className="control-label">Weighting</span>
            <select
              value={weighting}
              onChange={(e) => setWeighting(e.target.value as "dv01" | "factor")}
            >
              <option value="dv01">DV01-neutral (textbook)</option>
              <option value="factor">Factor-neutral</option>
            </select>
          </label>
        </div>
      )}

      {!legsValid && (
        <p className="demo-warn">
          A butterfly needs its belly between the two wings. Pick a belly longer than the
          short wing and shorter than the long one.
        </p>
      )}

      {panel === "trade" && fly && shares && (
        <TradePanel curve={curve} factors={factors} fly={fly} shares={shares} />
      )}

      {panel === "backtest" && (
        <>
          <div className="demo-controls">
            <label className="control">
              <span className="control-label">From {startYear}</span>
              <input
                type="range"
                min={1982}
                max={2020}
                value={startYear}
                onChange={(e) => setStartYear(Number(e.target.value))}
              />
            </label>
            <label className="control">
              <span className="control-label">Rebalance</span>
              <select
                value={rebalanceDays}
                onChange={(e) => setRebalanceDays(Number(e.target.value))}
              >
                <option value={1}>Daily</option>
                <option value={5}>Weekly</option>
                <option value={21}>Monthly</option>
                <option value={63}>Quarterly</option>
              </select>
            </label>
            <label className="control">
              <span className="control-label">Cost {costBp.toFixed(2)}bp</span>
              <input
                type="range"
                min={0}
                max={3}
                step={0.25}
                value={costBp}
                onChange={(e) => setCostBp(Number(e.target.value))}
              />
            </label>
            <label className="control" title={
              weighting === "dv01"
                ? "A DV01-neutral fly is 0.5 / -1 / 0.5 whatever the factor model says, so this changes nothing. Switch the weighting to factor-neutral."
                : "Refit the factor model on the whole history, including everything after the start date."
            }>
              <input
                type="checkbox"
                checked={lookAhead}
                disabled={weighting === "dv01"}
                onChange={(e) => setLookAhead(e.target.checked)}
              />
              <span className="control-label">
                Fit factors on all 45 years
                {weighting === "dv01" && " (factor-neutral only)"}
              </span>
            </label>
          </div>
          {backtest && (
            <BacktestPanel
              {...backtest}
              label={fly?.label ?? ""}
              lookAhead={lookAhead && weighting === "factor"}
              startYear={startYear}
            />
          )}
        </>
      )}

      {panel === "forecast" && (
        <ForecastPanel
          forecasts={forecasts}
          run={run}
          factor={forecastFactor}
          horizon={horizon}
          onFactor={setForecastFactor}
          onHorizon={setHorizon}
        />
      )}
    </div>
  );
}

function TradePanel({
  curve,
  factors,
  fly,
  shares,
}: {
  curve: ReturnType<typeof decodeCurve>;
  factors: ReturnType<typeof fitFactors>;
  fly: Butterfly;
  shares: number[];
}) {
  const loadingSeries: Series[] = factors.loadings.map((row, i) => ({
    label: ["Level", "Slope", "Curvature"][i],
    color: FACTOR_COLOUR[i],
    points: row.map((value, j) => ({ x: factors.maturities[j], y: value })),
  }));

  const curvature = shares[2];
  const verdict =
    curvature < 0.1
      ? "Almost none of this trade's risk is curvature — it is a level and slope position wearing a butterfly's name."
      : curvature > 0.9
        ? "This one really is a curvature trade."
        : "Part curvature, part something else.";

  return (
    <>
      <div className="metric-row">
        <Stat label="Level" value={pct(shares[0])} />
        <Stat label="Slope" value={pct(shares[1])} />
        <Stat label="Curvature" value={pct(shares[2])} tone="var(--ds)" />
        <Stat label="Net DV01" value={netDv01(fly).toFixed(3)} />
      </div>

      <BarChart
        bars={[
          { label: "Level", value: shares[0], color: FACTOR_COLOUR[0] },
          { label: "Slope", value: shares[1], color: FACTOR_COLOUR[1] },
          { label: "Curvature", value: shares[2], color: FACTOR_COLOUR[2] },
        ]}
        formatValue={pct}
      />

      <p className="demo-note">
        <strong>{fly.label}.</strong> {verdict} Share of P&amp;L variance from each{" "}
        <Term id="curve-factor">factor</Term>, using the covariance of daily changes
        over {curve.yields.length.toLocaleString()} days. A{" "}
        <Term id="dv01">DV01</Term>-neutral fly is neutral to a <em>parallel</em> shift; the
        curve does not move in parallel shifts.
      </p>

      <h4>The three shapes the curve moves in</h4>
      <LineChart
        series={loadingSeries}
        height={220}
        formatX={(v) => (v < 1 ? `${v * 12}m` : `${v}y`)}
        formatY={(v) => v.toFixed(2)}
        yLabel="loading"
      />
      <p className="demo-note">
        Level {pct(factors.explained[0])}, slope {pct(factors.explained[1])}, curvature{" "}
        {pct(factors.explained[2])} of all curve movement. Curvature bends hardest at the
        two-year — which is why a fly centred on the five-year barely touches it.
      </p>
    </>
  );
}

function BacktestPanel({
  result,
  performance,
  label,
  lookAhead,
  startYear,
}: {
  result: ReturnType<typeof runBacktest>;
  performance: ReturnType<typeof summarise>;
  label: string;
  lookAhead: boolean;
  startYear: number;
}) {
  const equity: Series[] = [
    {
      label: "Cumulative P&L",
      color: "var(--mk)",
      points: result.dates.map((d, i) => ({ x: d, y: result.equity[i] })),
    },
  ];
  const c = result.contribution;

  return (
    <>
      <div className="metric-row">
        <Stat label="Total" value={money(performance.total)} />
        <Stat label="Info ratio" value={performance.informationRatio.toFixed(2)} />
        <Stat label="Max drawdown" value={money(performance.maxDrawdown)} />
        <Stat label="Hit rate" value={pct(performance.hitRate)} />
      </div>

      <LineChart
        series={equity}
        height={240}
        formatX={(v) => String(year(v))}
        formatY={money}
        yLabel="$ per $1/bp"
      />

      <h4>Where the money came from</h4>
      <BarChart
        bars={[
          { label: "Direction", value: c.directional, color: "var(--mk)" },
          { label: "Carry", value: c.carry, color: "var(--se)" },
          { label: "Roll-down", value: c.rolldown, color: "var(--ai)" },
          { label: "Cost", value: c.cost, color: "var(--ds)" },
        ]}
        formatValue={money}
      />
      <p className="demo-note">
        <strong>{label}</strong>, {performance.days.toLocaleString()} days, sized per $1 of
        belly <Term id="dv01">DV01</Term>. The direction bar is what the position earned for
        being right about where the curve went; <Term id="carry">carry</Term> and roll-down
        needed no view at all. Move the cost slider to see how much of it survives the
        bid-offer.
      </p>
      <p className={lookAhead ? "demo-warn" : "demo-hint"}>
        {lookAhead ? (
          <>
            <strong>Look-ahead is on.</strong> The factor model is fitted on all
            forty-five years, including everything after {startYear}, so these weights
            could not have been set at the time. It is not a small effect: on the
            factor-neutral 2s5s10s from 2000 it takes the result from{" "}
            <strong>+$143 to −$232</strong> — a sign flip, not a rounding difference.
            The curve of the 1980s was a different animal, and loadings fitted across
            both eras fit neither.
          </>
        ) : (
          <>
            Factors are fitted on the backtest window only, so the weights use nothing
            the trader would not have had. Tick the box above to fit them on all
            forty-five years instead and see what the look-ahead is worth.
          </>
        )}
      </p>
    </>
  );
}

function ForecastPanel({
  forecasts,
  run,
  factor,
  horizon,
  onFactor,
  onHorizon,
}: {
  forecasts: ForecastFile;
  run: ForecastRun | undefined;
  factor: string;
  horizon: number;
  onFactor: (v: string) => void;
  onHorizon: (v: number) => void;
}) {
  const factorNames = [...new Set(forecasts.runs.map((r) => r.factor))];
  const horizons = [...new Set(forecasts.runs.map((r) => r.horizonDays))];

  return (
    <>
      <div className="demo-controls">
        <label className="control">
          <span className="control-label">Factor</span>
          <select value={factor} onChange={(e) => onFactor(e.target.value)}>
            {factorNames.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </label>
        <label className="control">
          <span className="control-label">Horizon</span>
          <select value={horizon} onChange={(e) => onHorizon(Number(e.target.value))}>
            {horizons.map((h) => (
              <option key={h} value={h}>
                {h} day{h === 1 ? "" : "s"}
              </option>
            ))}
          </select>
        </label>
      </div>

      {run && (
        <>
          <div className="metric-row">
            <Stat
              label="Out-of-sample R²"
              value={run.r2.toFixed(3)}
              tone={run.r2 < 0 ? "var(--ds)" : "var(--good)"}
            />
            <Stat label="Directional accuracy" value={pct(run.directionalAccuracy)} />
            <Stat label="DM t-statistic" value={run.dmStatistic.toFixed(1)} />
            <Stat label="Test days" value={run.testDays.toLocaleString()} />
          </div>

          <ScatterChart
            groups={[
              {
                label: "Predicted vs actual",
                color: "var(--mk)",
                points: run.scatter.map((pair) => ({ x: pair[0], y: pair[1] })),
              },
            ]}
            height={260}
            xLabel="actual factor move"
            yLabel="predicted"
          />

          <p className="demo-note">
            {forecasts.model} over {run.nFeatures} engineered features, walk-forward on an
            expanding window across {forecasts.folds} folds. The baseline predicts{" "}
            <strong>zero</strong>, because a factor score is already a change — so a{" "}
            <em>negative</em> R² means the model is worse than assuming the curve is a random
            walk.{" "}
            {run.beatsBaseline
              ? "This one beats it."
              : `It does not beat it here, and the paired test on squared errors puts t at ${run.dmStatistic.toFixed(0)} — the errors are larger, and not by luck.`}
          </p>
          <p className="demo-note">
            Try every combination: all twelve lose. That is consistent with the backtest,
            which found the directional P&amp;L was worth about nothing.
          </p>
        </>
      )}
    </>
  );
}

function Stat({
  label,
  value,
  term,
  tone,
}: {
  label: string;
  value: string;
  /** Glossary id, when the label is jargon. */
  term?: string;
  tone?: string;
}) {
  return (
    <div className="metric">
      <div className="metric-label">{term ? <Term id={term}>{label}</Term> : label}</div>
      <div className="metric-value" style={tone ? { color: tone } : undefined}>
        {value}
      </div>
    </div>
  );
}
