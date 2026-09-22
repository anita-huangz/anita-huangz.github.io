/**
 * The BFF.
 *
 * It sits between the browser and the Python engine and earns its place doing
 * four things the engine should not:
 *
 *   **Caching.** Answers are deterministic functions of a committed file, so a
 *   repeated request is free. See `cache.ts` for why that is bounded and why
 *   the hit rate is reported rather than assumed.
 *
 *   **Validation at the edge.** A malformed cost is a 400 from Node instead of
 *   a round trip into Python.
 *
 *   **Fan-out.** The overview page needs factors, the trade decomposition and a
 *   backtest. That is three engine calls and one browser round trip, not three.
 *
 *   **Serving the client.** One origin, so there is no CORS to configure in
 *   production.
 *
 * It deliberately holds no domain logic. Every number it returns was computed
 * by the engine; if this file ever starts computing a DV01, there are two
 * implementations of the same idea and they will drift.
 */

import express, { type Express, type NextFunction, type Request, type Response } from "express";
import { existsSync } from "node:fs";
import { z } from "zod";

import { cacheKey, ResponseCache } from "./cache.js";
import { EngineError, type EngineClient } from "./engine.js";
import {
  backtestSchema,
  forecastSchema,
  legsOrdered,
  parseSchema,
  tradeSchema,
  windowSchema,
} from "./schema.js";

export interface ServerOptions {
  engine: EngineClient;
  /** Directory of the built client. Skipped when absent, so the API runs alone. */
  staticDir?: string;
  cache?: ResponseCache<unknown>;
}

export function createServer({ engine, staticDir, cache }: ServerOptions): Express {
  const app = express();
  const responses = cache ?? new ResponseCache<unknown>(256, 60 * 60 * 1000);
  app.use(express.json({ limit: "64kb" }));
  app.disable("x-powered-by");

  /** Run an engine call through the cache, keyed on the route and its body. */
  const cached = async (route: string, body: unknown): Promise<unknown> => {
    const key = cacheKey(route, body);
    const hit = responses.get(key);
    if (hit !== undefined) return hit;
    const value = await engine.post(route, body);
    responses.set(key, value);
    return value;
  };

  /** Validate, then delegate. Zod failures never reach the engine. */
  const route =
    <T extends z.ZodTypeAny>(schema: T, path: string, checkLegs = false) =>
    async (request: Request, response: Response, next: NextFunction) => {
      const parsed = schema.safeParse(request.body ?? {});
      if (!parsed.success) {
        response.status(400).json({
          error: "invalid request",
          issues: parsed.error.issues.map((i) => ({
            field: i.path.join(".") || "(body)",
            message: i.message,
          })),
        });
        return;
      }
      const body = parsed.data as Record<string, unknown>;
      if (checkLegs) {
        const wings = body.wings as [string, string];
        const belly = body.belly as string;
        if (!legsOrdered(wings, belly)) {
          response.status(400).json({
            error: "invalid request",
            issues: [
              {
                field: "belly",
                message: `a butterfly needs its belly between the wings; got ${wings[0]}, ${belly}, ${wings[1]}`,
              },
            ],
          });
          return;
        }
      }
      try {
        response.json(await cached(path, body));
      } catch (error) {
        next(error);
      }
    };

  app.get("/api/health", async (_request, response, next) => {
    try {
      const engineHealth = await engine.get("/health");
      response.json({ status: "ok", engine: engineHealth, cache: responses.stats });
    } catch (error) {
      next(error);
    }
  });

  app.get("/api/curve/summary", async (_request, response, next) => {
    try {
      const key = cacheKey("/curve/summary", null);
      const hit = responses.get(key);
      if (hit !== undefined) {
        response.json(hit);
        return;
      }
      const value = await engine.get("/curve/summary");
      responses.set(key, value);
      response.json(value);
    } catch (error) {
      next(error);
    }
  });

  app.post("/api/factors", route(windowSchema, "/factors"));
  app.post("/api/trade", route(tradeSchema, "/trade", true));
  app.post("/api/backtest", route(backtestSchema, "/backtest", true));
  app.post("/api/carry", route(windowSchema, "/carry"));
  app.post("/api/forecast", route(forecastSchema, "/forecast"));
  app.post("/api/cycles", route(windowSchema, "/cycles"));
  app.post("/api/strategy/parse", route(parseSchema, "/strategy/parse"));

  /**
   * Everything the overview page needs, in one round trip.
   *
   * The three calls go out together rather than in sequence: they do not
   * depend on each other, and run serially the page waits for their sum.
   */
  app.post("/api/overview", async (request, response, next) => {
    const parsed = backtestSchema.safeParse(request.body ?? {});
    if (!parsed.success) {
      response.status(400).json({
        error: "invalid request",
        issues: parsed.error.issues.map((i) => ({
          field: i.path.join(".") || "(body)",
          message: i.message,
        })),
      });
      return;
    }
    const body = parsed.data;
    if (!legsOrdered(body.wings, body.belly)) {
      response.status(400).json({
        error: "invalid request",
        issues: [{ field: "belly", message: "the belly must sit between the wings" }],
      });
      return;
    }
    try {
      const [factors, trade, backtest] = await Promise.all([
        cached("/factors", { start: body.start, end: body.end }),
        cached("/trade", {
          start: body.start, end: body.end,
          wings: body.wings, belly: body.belly, weighting: body.weighting,
        }),
        cached("/backtest", body),
      ]);
      response.json({ factors, trade, backtest });
    } catch (error) {
      next(error);
    }
  });

  if (staticDir && existsSync(staticDir)) {
    app.use(express.static(staticDir));
    // History-API fallback, but never for /api: an unknown API path should be
    // a 404, not the client's index.html with a 200 attached.
    app.get(/^(?!\/api\/).*/, (_request, response) => {
      response.sendFile("index.html", { root: staticDir });
    });
  }

  app.use((_request: Request, response: Response) => {
    response.status(404).json({ error: "no such route" });
  });

  app.use((error: unknown, _request: Request, response: Response, _next: NextFunction) => {
    if (error instanceof EngineError) {
      // 4xx from the engine is the caller's problem and is passed through;
      // 5xx is ours and is reported as a bad gateway rather than pretending
      // the engine's internals are the client's business.
      const status = error.status >= 400 && error.status < 500 ? error.status : 502;
      response.status(status).json({ error: error.message, from: "engine" });
      return;
    }
    response.status(500).json({ error: "unexpected failure" });
  });

  return app;
}
