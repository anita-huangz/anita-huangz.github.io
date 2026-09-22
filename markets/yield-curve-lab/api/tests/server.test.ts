/**
 * The BFF, with the engine faked.
 *
 * Nothing here needs Python running. That is the point of the `EngineClient`
 * interface: checking that a cost of 90bp is a 400 should not require a
 * loaded curve and a spare port.
 */

import type { Express } from "express";
import { describe, expect, it, beforeEach } from "vitest";

import { ResponseCache } from "../src/cache.js";
import { EngineError, type EngineClient } from "../src/engine.js";
import { createServer } from "../src/server.js";

interface Call {
  path: string;
  body: unknown;
}

function fakeEngine(overrides: Partial<Record<string, unknown>> = {}) {
  const calls: Call[] = [];
  let failWith: EngineError | null = null;
  const client: EngineClient = {
    async get(path) {
      calls.push({ path, body: null });
      if (failWith) throw failWith;
      return overrides[path] ?? { ok: true, path };
    },
    async post(path, body) {
      calls.push({ path, body });
      if (failWith) throw failWith;
      return overrides[path] ?? { ok: true, path, echo: body };
    },
  };
  return {
    client,
    calls,
    fail(error: EngineError | null) {
      failWith = error;
    },
  };
}

/** A tiny fetch-free request helper against an Express app. */
async function call(
  app: Express,
  method: "GET" | "POST",
  path: string,
  body?: unknown,
): Promise<{ status: number; json: any }> {
  const { createServer: createHttp } = await import("node:http");
  const server = createHttp(app);
  await new Promise<void>((resolve) => server.listen(0, resolve));
  const address = server.address();
  const port = typeof address === "object" && address ? address.port : 0;
  try {
    const response = await fetch(`http://127.0.0.1:${port}${path}`, {
      method,
      headers: body === undefined ? undefined : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    return { status: response.status, json: text ? JSON.parse(text) : null };
  } finally {
    server.close();
  }
}

describe("validation at the edge", () => {
  let engine: ReturnType<typeof fakeEngine>;
  let app: Express;

  beforeEach(() => {
    engine = fakeEngine();
    app = createServer({ engine: engine.client, cache: new ResponseCache(64) });
  });

  it("rejects a cost outside the range without asking the engine", async () => {
    const { status, json } = await call(app, "POST", "/api/backtest", { cost_bp: 90 });
    expect(status).toBe(400);
    expect(json.issues[0].field).toBe("cost_bp");
    expect(engine.calls).toHaveLength(0);
  });

  it("rejects an unknown tenor", async () => {
    const { status } = await call(app, "POST", "/api/trade", { belly: "DGS99" });
    expect(status).toBe(400);
    expect(engine.calls).toHaveLength(0);
  });

  it("rejects a belly outside its wings, and says which legs", async () => {
    const { status, json } = await call(app, "POST", "/api/trade", {
      wings: ["DGS10", "DGS30"],
      belly: "DGS2",
    });
    expect(status).toBe(400);
    expect(json.issues[0].message).toMatch(/between the wings/);
    expect(engine.calls).toHaveLength(0);
  });

  it("rejects a malformed date", async () => {
    const { status, json } = await call(app, "POST", "/api/factors", { start: "01/01/2000" });
    expect(status).toBe(400);
    expect(json.issues[0].message).toMatch(/ISO date/);
  });

  it("rejects a rebalance period of zero", async () => {
    const { status } = await call(app, "POST", "/api/backtest", { rebalance_days: 0 });
    expect(status).toBe(400);
  });

  it("applies the same defaults the engine would", async () => {
    await call(app, "POST", "/api/trade", {});
    expect(engine.calls[0]?.body).toMatchObject({
      wings: ["DGS2", "DGS10"],
      belly: "DGS5",
      weighting: "dv01",
    });
  });

  it("accepts an empty body, because every field has a default", async () => {
    const { status } = await call(app, "POST", "/api/backtest", {});
    expect(status).toBe(200);
  });
});

describe("caching", () => {
  it("asks the engine once for a repeated request", async () => {
    const engine = fakeEngine();
    const app = createServer({ engine: engine.client, cache: new ResponseCache(64) });
    await call(app, "POST", "/api/trade", { belly: "DGS5" });
    await call(app, "POST", "/api/trade", { belly: "DGS5" });
    expect(engine.calls).toHaveLength(1);
  });

  it("does not confuse two different requests", async () => {
    const engine = fakeEngine();
    const app = createServer({ engine: engine.client, cache: new ResponseCache(64) });
    await call(app, "POST", "/api/backtest", { cost_bp: 0.5 });
    await call(app, "POST", "/api/backtest", { cost_bp: 1.5 });
    expect(engine.calls).toHaveLength(2);
  });

  it("reports its hit rate on the health route", async () => {
    const engine = fakeEngine();
    const app = createServer({ engine: engine.client, cache: new ResponseCache(64) });
    await call(app, "POST", "/api/trade", {});
    await call(app, "POST", "/api/trade", {});
    const { json } = await call(app, "GET", "/api/health");
    expect(json.cache.hits).toBe(1);
    expect(json.cache.misses).toBe(1);
    expect(json.cache.hitRate).toBeCloseTo(0.5, 10);
  });
});

describe("fan-out", () => {
  it("answers the overview from three engine calls in one round trip", async () => {
    const engine = fakeEngine();
    const app = createServer({ engine: engine.client, cache: new ResponseCache(64) });
    const { status, json } = await call(app, "POST", "/api/overview", { start: "2000-01-01" });
    expect(status).toBe(200);
    expect(Object.keys(json).sort()).toEqual(["backtest", "factors", "trade"]);
    expect(engine.calls.map((c) => c.path).sort()).toEqual(["/backtest", "/factors", "/trade"]);
  });

  it("reuses whatever the individual routes already cached", async () => {
    const engine = fakeEngine();
    const app = createServer({ engine: engine.client, cache: new ResponseCache(64) });
    await call(app, "POST", "/api/factors", { start: "2000-01-01" });
    engine.calls.length = 0;
    await call(app, "POST", "/api/overview", { start: "2000-01-01" });
    expect(engine.calls.map((c) => c.path)).not.toContain("/factors");
  });

  it("validates before fanning out", async () => {
    const engine = fakeEngine();
    const app = createServer({ engine: engine.client, cache: new ResponseCache(64) });
    const { status } = await call(app, "POST", "/api/overview", { cost_bp: -1 });
    expect(status).toBe(400);
    expect(engine.calls).toHaveLength(0);
  });
});

describe("what happens when the engine misbehaves", () => {
  it("passes a 4xx through, because it is the caller's problem", async () => {
    const engine = fakeEngine();
    engine.fail(new EngineError("window too short", 422));
    const app = createServer({ engine: engine.client, cache: new ResponseCache(64) });
    const { status, json } = await call(app, "POST", "/api/factors", { start: "2026-09-01" });
    expect(status).toBe(422);
    expect(json.error).toBe("window too short");
  });

  it("turns a 5xx into a bad gateway rather than leaking it", async () => {
    const engine = fakeEngine();
    engine.fail(new EngineError("ZeroDivisionError at line 412", 500));
    const app = createServer({ engine: engine.client, cache: new ResponseCache(64) });
    const { status, json } = await call(app, "POST", "/api/trade", {});
    expect(status).toBe(502);
    expect(json.from).toBe("engine");
  });

  it("reports an unreachable engine as a bad gateway", async () => {
    const engine = fakeEngine();
    engine.fail(new EngineError("connect ECONNREFUSED", 502));
    const app = createServer({ engine: engine.client, cache: new ResponseCache(64) });
    const { status } = await call(app, "GET", "/api/health");
    expect(status).toBe(502);
  });

  it("does not cache a failure", async () => {
    const engine = fakeEngine();
    const app = createServer({ engine: engine.client, cache: new ResponseCache(64) });
    engine.fail(new EngineError("transient", 500));
    await call(app, "POST", "/api/trade", {});
    engine.fail(null);
    const { status } = await call(app, "POST", "/api/trade", {});
    expect(status).toBe(200);
  });
});

describe("routing", () => {
  it("404s an unknown API path as JSON", async () => {
    const engine = fakeEngine();
    const app = createServer({ engine: engine.client, cache: new ResponseCache(64) });
    const { status, json } = await call(app, "GET", "/api/nope");
    expect(status).toBe(404);
    expect(json.error).toBe("no such route");
  });

  it("runs without a client build present", async () => {
    const engine = fakeEngine();
    const app = createServer({
      engine: engine.client,
      staticDir: "/nonexistent",
      cache: new ResponseCache(64),
    });
    const { status } = await call(app, "GET", "/api/health");
    expect(status).toBe(200);
  });
});
