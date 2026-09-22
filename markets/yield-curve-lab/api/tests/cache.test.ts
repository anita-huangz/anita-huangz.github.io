import { describe, expect, it } from "vitest";

import { cacheKey, ResponseCache } from "../src/cache.js";

describe("the response cache", () => {
  it("returns what was put in", () => {
    const cache = new ResponseCache<string>();
    cache.set("a", "one");
    expect(cache.get("a")).toBe("one");
  });

  it("misses on a key it has never seen", () => {
    expect(new ResponseCache<string>().get("absent")).toBeUndefined();
  });

  it("counts hits and misses so the hit rate can be looked at", () => {
    const cache = new ResponseCache<string>();
    cache.set("a", "one");
    cache.get("a");
    cache.get("a");
    cache.get("b");
    expect(cache.stats).toMatchObject({ hits: 2, misses: 1, size: 1 });
    expect(cache.stats.hitRate).toBeCloseTo(2 / 3, 10);
  });

  it("reports a zero hit rate rather than dividing by nothing", () => {
    expect(new ResponseCache<string>().stats.hitRate).toBe(0);
  });

  it("evicts the least recently used entry, not the oldest inserted", () => {
    const cache = new ResponseCache<string>(2);
    cache.set("a", "1");
    cache.set("b", "2");
    cache.get("a"); // "a" is now the most recently used
    cache.set("c", "3");
    expect(cache.get("a")).toBe("1");
    expect(cache.get("b")).toBeUndefined();
    expect(cache.stats.evictions).toBe(1);
  });

  it("stays within its capacity", () => {
    const cache = new ResponseCache<number>(3);
    for (let i = 0; i < 50; i++) cache.set(`k${i}`, i);
    expect(cache.stats.size).toBe(3);
    expect(cache.stats.evictions).toBe(47);
  });

  it("expires an entry once its TTL has passed", () => {
    let now = 1_000;
    const cache = new ResponseCache<string>(10, 500, () => now);
    cache.set("a", "one");
    now = 1_400;
    expect(cache.get("a")).toBe("one");
    now = 1_600;
    expect(cache.get("a")).toBeUndefined();
  });

  it("overwrites rather than duplicating a repeated key", () => {
    const cache = new ResponseCache<string>(5);
    cache.set("a", "one");
    cache.set("a", "two");
    expect(cache.get("a")).toBe("two");
    expect(cache.stats.size).toBe(1);
  });

  it("refuses a nonsense configuration", () => {
    expect(() => new ResponseCache(0)).toThrow(/capacity/);
    expect(() => new ResponseCache(4, 0)).toThrow(/ttlMs/);
  });
});

describe("cache keys", () => {
  it("does not depend on the order the body was written in", () => {
    // The browser does not promise a key order, and a cache that misses on
    // {a,b} after storing {b,a} is a cache with half the hit rate it thinks.
    expect(cacheKey("/x", { a: 1, b: 2 })).toBe(cacheKey("/x", { b: 2, a: 1 }));
  });

  it("separates different routes", () => {
    expect(cacheKey("/a", { x: 1 })).not.toBe(cacheKey("/b", { x: 1 }));
  });

  it("separates different values", () => {
    expect(cacheKey("/x", { cost: 0.5 })).not.toBe(cacheKey("/x", { cost: 1 }));
  });

  it("treats a missing key and an undefined one as the same request", () => {
    expect(cacheKey("/x", { a: 1, b: undefined })).toBe(cacheKey("/x", { a: 1 }));
  });

  it("keeps array order, which is meaningful for legs", () => {
    expect(cacheKey("/x", { wings: ["DGS2", "DGS10"] })).not.toBe(
      cacheKey("/x", { wings: ["DGS10", "DGS2"] }),
    );
  });

  it("handles nested objects and nulls", () => {
    expect(cacheKey("/x", { a: { c: 1, b: null } })).toBe(cacheKey("/x", { a: { b: null, c: 1 } }));
  });
});
