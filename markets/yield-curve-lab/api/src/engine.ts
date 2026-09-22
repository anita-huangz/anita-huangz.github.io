/**
 * A typed client for the Python quant service.
 *
 * Kept behind an interface so the Express layer can be tested without a
 * running engine. That is not a hypothetical convenience: the alternative is a
 * test suite that needs Python, a loaded 11,261-row curve and a port, to check
 * that a bad cost value returns 400.
 */

export interface EngineClient {
  get(path: string): Promise<unknown>;
  post(path: string, body: unknown): Promise<unknown>;
}

export class EngineError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail: unknown = null,
  ) {
    super(message);
    this.name = "EngineError";
  }
}

export function httpEngine(baseUrl: string, timeoutMs = 60_000): EngineClient {
  const call = async (path: string, init: RequestInit): Promise<unknown> => {
    const controller = new AbortController();
    // The forecast route refits XGBoost several times; a default fetch timeout
    // would cut it off and report an engine failure that never happened.
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(`${baseUrl}${path}`, { ...init, signal: controller.signal });
      const text = await response.text();
      const payload = text ? JSON.parse(text) : null;
      if (!response.ok) {
        const detail = (payload as { detail?: unknown } | null)?.detail ?? text;
        throw new EngineError(
          typeof detail === "string" ? detail : "the engine rejected the request",
          response.status,
          detail,
        );
      }
      return payload;
    } catch (error) {
      if (error instanceof EngineError) throw error;
      if (error instanceof Error && error.name === "AbortError") {
        throw new EngineError(`the engine did not answer within ${timeoutMs}ms`, 504);
      }
      throw new EngineError(
        error instanceof Error ? error.message : "could not reach the engine",
        502,
      );
    } finally {
      clearTimeout(timer);
    }
  };

  return {
    get: (path) => call(path, { method: "GET" }),
    post: (path, body) =>
      call(path, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      }),
  };
}
