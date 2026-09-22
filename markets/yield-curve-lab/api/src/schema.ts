/**
 * Request shapes, validated here before anything reaches the quant service.
 *
 * The Python side validates too, and that is not duplication worth removing:
 * this is the layer facing the internet, and an out-of-range cost should cost
 * a 400 from a Node process rather than a round trip and a stack unwind in
 * the engine. The bounds are deliberately the same as the engine's, so a
 * request that passes here cannot fail validation there -- the only 422s from
 * downstream should be about the data, like a window too short to fit a
 * covariance.
 */

import { z } from "zod";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export const TENORS = [
  "DGS3MO", "DGS6MO", "DGS1", "DGS2", "DGS3", "DGS5", "DGS7", "DGS10", "DGS30",
] as const;

const tenor = z.enum(TENORS);
const isoDate = z.string().regex(ISO_DATE, "expected an ISO date, YYYY-MM-DD");

export const windowSchema = z.object({
  start: isoDate.nullish(),
  end: isoDate.nullish(),
});

export const tradeSchema = windowSchema.extend({
  wings: z.tuple([tenor, tenor]).default(["DGS2", "DGS10"]),
  belly: tenor.default("DGS5"),
  weighting: z.enum(["dv01", "factor"]).default("dv01"),
});

export const backtestSchema = tradeSchema.extend({
  rebalance_days: z.number().int().min(1).max(252).default(21),
  cost_bp: z.number().min(0).max(25).default(0.5),
  look_ahead: z.boolean().default(false),
});

export const forecastSchema = windowSchema.extend({
  factor: z.enum(["level", "slope", "curvature"]).default("curvature"),
  horizon_days: z.number().int().min(1).max(252).default(5),
  folds: z.number().int().min(2).max(10).default(4),
});

export const parseSchema = z.object({
  text: z.string().min(1).max(500),
});

/** The belly has to sit between the wings, and the engine says so too. */
export function legsOrdered(wings: readonly [string, string], belly: string): boolean {
  const years: Record<string, number> = {
    DGS3MO: 0.25, DGS6MO: 0.5, DGS1: 1, DGS2: 2, DGS3: 3,
    DGS5: 5, DGS7: 7, DGS10: 10, DGS30: 30,
  };
  const short = years[wings[0]];
  const middle = years[belly];
  const long = years[wings[1]];
  if (short === undefined || middle === undefined || long === undefined) return false;
  return short < middle && middle < long;
}
