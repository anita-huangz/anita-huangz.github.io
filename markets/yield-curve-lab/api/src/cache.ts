/**
 * A bounded response cache.
 *
 * Every answer this service gives is a deterministic function of a committed
 * file: the same window, legs and costs produce the same backtest forever,
 * because the 1990s are not going to change. That makes caching unusually
 * safe here, and unusually worthwhile -- a backtest is about a second of
 * Python and a walk-forward forecast is several, so the second caller of a
 * popular request should not pay for it again.
 *
 * Bounded, because "cache everything forever" is how a long-running service
 * turns into an out-of-memory crash: the key space is every combination of
 * legs, dates, rebalance and cost, which is effectively unlimited. Least
 * recently used is evicted first.
 *
 * Hits and misses are counted and exposed on the health route rather than
 * assumed. A cache with a 2% hit rate is a memory leak with extra steps, and
 * the only way to know which one this is, is to look.
 */

export interface CacheStats {
  hits: number;
  misses: number;
  evictions: number;
  size: number;
  capacity: number;
  hitRate: number;
}

export class ResponseCache<T> {
  private readonly entries = new Map<string, { value: T; expires: number }>();
  private hits = 0;
  private misses = 0;
  private evictions = 0;

  constructor(
    private readonly capacity = 256,
    private readonly ttlMs = 60 * 60 * 1000,
    private readonly now: () => number = Date.now,
  ) {
    if (capacity < 1) throw new Error("capacity must be at least 1");
    if (ttlMs <= 0) throw new Error("ttlMs must be positive");
  }

  get(key: string): T | undefined {
    const entry = this.entries.get(key);
    if (!entry) {
      this.misses += 1;
      return undefined;
    }
    if (entry.expires <= this.now()) {
      this.entries.delete(key);
      this.misses += 1;
      return undefined;
    }
    // Re-insert so Map iteration order puts it last: this is the "recently
    // used" half of LRU, and without it eviction is just insertion order.
    this.entries.delete(key);
    this.entries.set(key, entry);
    this.hits += 1;
    return entry.value;
  }

  set(key: string, value: T): void {
    if (this.entries.has(key)) this.entries.delete(key);
    this.entries.set(key, { value, expires: this.now() + this.ttlMs });
    while (this.entries.size > this.capacity) {
      const oldest = this.entries.keys().next();
      if (oldest.done) break;
      this.entries.delete(oldest.value);
      this.evictions += 1;
    }
  }

  clear(): void {
    this.entries.clear();
  }

  get stats(): CacheStats {
    const looked = this.hits + this.misses;
    return {
      hits: this.hits,
      misses: this.misses,
      evictions: this.evictions,
      size: this.entries.size,
      capacity: this.capacity,
      hitRate: looked === 0 ? 0 : this.hits / looked,
    };
  }
}

/** A stable key for a route plus its body. Key order must not matter. */
export function cacheKey(route: string, body: unknown): string {
  return `${route}:${stableStringify(body)}`;
}

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  const record = value as Record<string, unknown>;
  const pairs = Object.keys(record)
    .sort()
    .filter((k) => record[k] !== undefined)
    .map((k) => `${JSON.stringify(k)}:${stableStringify(record[k])}`);
  return `{${pairs.join(",")}}`;
}
