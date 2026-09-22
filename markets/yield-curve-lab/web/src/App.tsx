import { useCallback, useEffect, useMemo, useState } from "react";

import {
  api,
  ApiError,
  type Forecast,
  type Health,
  type Overview,
  type Request,
  type Strategy,
} from "./api";

const TENORS = [
  ["DGS3MO", "3m"], ["DGS6MO", "6m"], ["DGS1", "1y"], ["DGS2", "2y"], ["DGS3", "3y"],
  ["DGS5", "5y"], ["DGS7", "7y"], ["DGS10", "10y"], ["DGS30", "30y"],
] as const;

const EXAMPLES = [
  "factor-neutral 1s2s5s since 2010, weekly, 1bp",
  "2s5s10s butterfly since 2000, monthly",
  "duration-neutral fly on 3m, 2y and 10y since 1995, quarterly, frictionless",
  "5s10s30s pca weighted since 2015, every 3 days",
];

const money = (v: number) => `${v < 0 ? "−" : ""}$${Math.abs(Math.round(v)).toLocaleString()}`;
const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

const DEFAULT: Request = {
  wings: ["DGS2", "DGS10"],
  belly: "DGS5",
  weighting: "dv01",
  start: "2000-01-01",
  end: null,
  rebalance_days: 21,
  cost_bp: 0.5,
  look_ahead: false,
};

export function App() {
  const [request, setRequest] = useState<Request>(DEFAULT);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [sentence, setSentence] = useState(EXAMPLES[0]!);
  const [parsed, setParsed] = useState<Strategy | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);

  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [forecastBusy, setForecastBusy] = useState(false);
  const [factor, setFactor] = useState("curvature");
  const [horizon, setHorizon] = useState(5);

  const patch = (change: Partial<Request>) => setRequest((r) => ({ ...r, ...change }));

  const refreshHealth = useCallback(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    let alive = true;
    setBusy(true);
    setError(null);
    api
      .overview(request)
      .then((result) => {
        if (alive) setOverview(result);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        const message =
          e instanceof ApiError
            ? [e.message, ...e.issues.map((i) => `${i.field}: ${i.message}`)].join(" — ")
            : "could not reach the API";
        setError(message);
      })
      .finally(() => {
        if (alive) {
          setBusy(false);
          refreshHealth();
        }
      });
    return () => {
      alive = false;
    };
  }, [request, refreshHealth]);

  const runSentence = async () => {
    setParseError(null);
    try {
      const strategy = await api.parse(sentence);
      setParsed(strategy);
      patch({
        wings: strategy.wings,
        belly: strategy.belly,
        weighting: strategy.weighting,
        rebalance_days: strategy.rebalanceDays,
        cost_bp: strategy.costBp,
        start: strategy.start,
        end: strategy.end,
      });
    } catch (e) {
      setParsed(null);
      setParseError(e instanceof ApiError ? e.message : "could not parse that");
    }
  };

  const runForecast = async () => {
    setForecastBusy(true);
    try {
      setForecast(
        await api.forecast({ start: request.start, factor, horizon_days: horizon, folds: 4 }),
      );
    } catch (e) {
      setForecast(null);
      setParseError(e instanceof ApiError ? e.message : "the forecast failed");
    } finally {
      setForecastBusy(false);
      refreshHealth();
    }
  };

  return (
    <main>
      <header>
        <h1>Yield Curve Lab</h1>
        <p className="lede">
          Treasury curve factors, trade construction and backtests, served by the Python
          engine behind an Express cache. Everything below is computed on request — nothing
          here is precomputed.
        </p>
        {health && (
          <p className="status">
            {health.engine.days.toLocaleString()} days, {health.engine.first} to{" "}
            {health.engine.last} · cache {health.cache.hits}/
            {health.cache.hits + health.cache.misses} hits ({pct(health.cache.hitRate)})
          </p>
        )}
      </header>

      <section>
        <h2>Describe a strategy</h2>
        <div className="row">
          <input
            value={sentence}
            onChange={(e) => setSentence(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void runSentence()}
            aria-label="Strategy in plain English"
          />
          <button onClick={() => void runSentence()}>Parse</button>
        </div>
        <div className="examples">
          {EXAMPLES.map((example) => (
            <button key={example} className="ghost" onClick={() => setSentence(example)}>
              {example}
            </button>
          ))}
        </div>
        {parsed && <p className="ok">Read as: {parsed.describe}</p>}
        {parseError && <p className="bad">{parseError}</p>}
        <p className="note">
          Parsed by keyword, not by a model, into a range-checked object. Every route below
          takes that same object, so execution stays deterministic however it was phrased.
        </p>
      </section>

      <section>
        <h2>The trade</h2>
        <div className="controls">
          <Picker label="Short wing" value={request.wings[0]}
                  onChange={(v) => patch({ wings: [v, request.wings[1]] })} />
          <Picker label="Belly" value={request.belly} onChange={(v) => patch({ belly: v })} />
          <Picker label="Long wing" value={request.wings[1]}
                  onChange={(v) => patch({ wings: [request.wings[0], v] })} />
          <label>
            <span>Weighting</span>
            <select
              value={request.weighting}
              onChange={(e) => patch({ weighting: e.target.value as "dv01" | "factor" })}
            >
              <option value="dv01">DV01-neutral</option>
              <option value="factor">Factor-neutral</option>
            </select>
          </label>
          <label>
            <span>From</span>
            <input type="date" value={request.start ?? ""}
                   onChange={(e) => patch({ start: e.target.value || null })} />
          </label>
          <label>
            <span>Rebalance</span>
            <select value={request.rebalance_days}
                    onChange={(e) => patch({ rebalance_days: Number(e.target.value) })}>
              <option value={1}>Daily</option>
              <option value={5}>Weekly</option>
              <option value={21}>Monthly</option>
              <option value={63}>Quarterly</option>
            </select>
          </label>
          <label>
            <span>Cost {request.cost_bp.toFixed(2)}bp</span>
            <input type="range" min={0} max={3} step={0.25} value={request.cost_bp}
                   onChange={(e) => patch({ cost_bp: Number(e.target.value) })} />
          </label>
          <label className="check">
            <input type="checkbox" checked={request.look_ahead}
                   disabled={request.weighting === "dv01"}
                   onChange={(e) => patch({ look_ahead: e.target.checked })} />
            <span>Fit factors on all 45 years{request.weighting === "dv01" && " (factor-neutral only)"}</span>
          </label>
        </div>

        {error && <p className="bad">{error}</p>}
        {busy && !overview && <p className="note">Computing…</p>}

        {overview && (
          <>
            <div className="metrics">
              <Metric label="Level" value={pct(overview.trade.varianceShare[0]!)} />
              <Metric label="Slope" value={pct(overview.trade.varianceShare[1]!)} />
              <Metric label="Curvature" value={pct(overview.trade.varianceShare[2]!)} strong />
              <Metric label="Net DV01" value={overview.trade.netDv01.toFixed(3)} />
            </div>
            <p className="note">
              <strong>{overview.trade.label}.</strong>{" "}
              {overview.trade.varianceShare[2]! < 0.1
                ? "Almost none of this is curvature — it is a level and slope position with a butterfly's name."
                : "This one really does trade curvature."}{" "}
              Share of P&amp;L variance by factor, over all 45 years.
            </p>

            <div className="metrics">
              <Metric label="Total" value={money(overview.backtest.total)} />
              <Metric label="Info ratio" value={overview.backtest.informationRatio.toFixed(2)} />
              <Metric label="Max drawdown" value={money(overview.backtest.maxDrawdown)} />
              <Metric label="Hit rate" value={pct(overview.backtest.hitRate)} />
            </div>
            <Equity dates={overview.backtest.dates} equity={overview.backtest.equity} />
            <Contribution contribution={overview.backtest.contribution} />
            <p className="note">
              {overview.backtest.days.toLocaleString()} days, per $1 of belly DV01.
              {overview.backtest.lookAhead
                ? " Look-ahead is on: the factor model saw everything after the start date, so these weights could not have been set at the time."
                : " Factors are refitted on the traded window, so the weights use nothing the trader would not have had."}
            </p>
          </>
        )}
      </section>

      <section>
        <h2>Forecast it, on demand</h2>
        <p className="note">
          This is the part the static demo on the portfolio site cannot do: XGBoost does not
          train in a browser, so there it is precomputed. Here it is refit per request, over
          any window and horizon, which is the reason the service exists.
        </p>
        <div className="controls">
          <label>
            <span>Factor</span>
            <select value={factor} onChange={(e) => setFactor(e.target.value)}>
              {["level", "slope", "curvature"].map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
          </label>
          <label>
            <span>Horizon</span>
            <select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>
              {[1, 5, 21, 63].map((h) => (
                <option key={h} value={h}>{h} day{h === 1 ? "" : "s"}</option>
              ))}
            </select>
          </label>
          <button onClick={() => void runForecast()} disabled={forecastBusy}>
            {forecastBusy ? "Refitting…" : "Run walk-forward"}
          </button>
        </div>
        {forecast && (
          <>
            <div className="metrics">
              <Metric label="Out-of-sample R²" value={forecast.r2VsBaseline.toFixed(3)}
                      bad={forecast.r2VsBaseline < 0} strong />
              <Metric label="Directional accuracy" value={pct(forecast.directionalAccuracy)} />
              <Metric label="DM t-statistic" value={forecast.dmStatistic.toFixed(1)} />
              <Metric label="Features" value={String(forecast.nFeatures)} />
            </div>
            <p className="note">{forecast.verdict}</p>
          </>
        )}
      </section>
    </main>
  );
}

function Picker({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label>
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {TENORS.map(([id, text]) => (
          <option key={id} value={id}>{text}</option>
        ))}
      </select>
    </label>
  );
}

function Metric({ label, value, strong, bad }: { label: string; value: string; strong?: boolean; bad?: boolean }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className={`metric-value${strong ? " strong" : ""}${bad ? " bad" : ""}`}>{value}</div>
    </div>
  );
}

function Equity({ dates, equity }: { dates: string[]; equity: number[] }) {
  const path = useMemo(() => {
    if (equity.length < 2) return "";
    const low = Math.min(...equity, 0);
    const high = Math.max(...equity, 0);
    const span = high - low || 1;
    return equity
      .map((value, i) => {
        const x = (i / (equity.length - 1)) * 100;
        const y = 100 - ((value - low) / span) * 100;
        return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join(" ");
  }, [equity]);

  const zero = useMemo(() => {
    const low = Math.min(...equity, 0);
    const high = Math.max(...equity, 0);
    const span = high - low || 1;
    return 100 - ((0 - low) / span) * 100;
  }, [equity]);

  if (!path) return null;
  return (
    <figure className="chart">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img"
           aria-label="Cumulative profit and loss">
        <line x1="0" y1={zero} x2="100" y2={zero} className="zero" vectorEffect="non-scaling-stroke" />
        <path d={path} vectorEffect="non-scaling-stroke" />
      </svg>
      <figcaption>
        {dates[0]} → {dates[dates.length - 1]}, cumulative P&amp;L
      </figcaption>
    </figure>
  );
}

function Contribution({ contribution }: { contribution: Record<string, number> }) {
  const rows = ["directional", "carry", "rolldown", "cost"].map((key) => ({
    key,
    value: contribution[key] ?? 0,
  }));
  const scale = Math.max(...rows.map((r) => Math.abs(r.value)), 1);
  return (
    <div className="bars">
      {rows.map(({ key, value }) => (
        <div className="bar-row" key={key}>
          <span className="bar-label">{key}</span>
          <span className="bar-track">
            <span className={`bar-fill ${key}`} style={{ width: `${(Math.abs(value) / scale) * 100}%` }} />
          </span>
          <span className="bar-value">{money(value)}</span>
        </div>
      ))}
    </div>
  );
}
