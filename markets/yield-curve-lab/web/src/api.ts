/**
 * The client's view of the BFF.
 *
 * Every call goes to a same-origin `/api/...`, which is true in production
 * (Express serves this bundle) and made true in development by the Vite proxy.
 * No base URL, no environment variable, nothing to get wrong between the two.
 */

export interface Issue {
  field: string;
  message: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly issues: Issue[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new ApiError(
      payload?.error ?? `request failed with ${response.status}`,
      response.status,
      payload?.issues ?? [],
    );
  }
  return payload as T;
}

export interface Strategy {
  wings: [string, string];
  belly: string;
  weighting: "dv01" | "factor";
  rebalanceDays: number;
  costBp: number;
  start: string | null;
  end: string | null;
  describe: string;
}

export interface Overview {
  factors: {
    tenors: string[];
    maturities: number[];
    names: string[];
    explained: number[];
    cumulative: number[];
    loadings: number[][];
    days: number;
  };
  trade: {
    label: string;
    netDv01: number;
    factorNames: string[];
    varianceShare: number[];
    unintendedShare: number;
  };
  backtest: {
    label: string;
    lookAhead: boolean;
    days: number;
    total: number;
    informationRatio: number;
    hitRate: number;
    maxDrawdown: number;
    contribution: Record<string, number>;
    dates: string[];
    equity: number[];
  };
}

export interface Forecast {
  factor: string;
  horizonDays: number;
  r2VsBaseline: number;
  directionalAccuracy: number;
  dmStatistic: number;
  beatsBaseline: boolean;
  nFeatures: number;
  testDays: number;
  verdict: string;
  scatter: number[][];
}

export interface Health {
  status: string;
  engine: { days: number; first: string; last: string };
  cache: { hits: number; misses: number; size: number; hitRate: number };
}

export interface Request {
  wings: [string, string];
  belly: string;
  weighting: "dv01" | "factor";
  start?: string | null;
  end?: string | null;
  rebalance_days: number;
  cost_bp: number;
  look_ahead: boolean;
}

export const api = {
  health: () => request<Health>("/health"),
  parse: (text: string) => request<Strategy>("/strategy/parse", { text }),
  overview: (body: Request) => request<Overview>("/overview", body),
  forecast: (body: { start?: string | null; factor: string; horizon_days: number; folds: number }) =>
    request<Forecast>("/forecast", body),
};
