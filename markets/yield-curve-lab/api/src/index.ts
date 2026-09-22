/** Entry point. Configuration is environment only; there is no config file. */

import { createServer } from "./server.js";
import { httpEngine } from "./engine.js";
import { ResponseCache } from "./cache.js";

const PORT = Number(process.env.PORT ?? 8080);
const ENGINE_URL = process.env.CURVE_ENGINE_URL ?? "http://127.0.0.1:8000";
const STATIC_DIR = process.env.CURVE_STATIC_DIR ?? "public";
const CACHE_ENTRIES = Number(process.env.CURVE_CACHE_ENTRIES ?? 256);
const CACHE_TTL_MINUTES = Number(process.env.CURVE_CACHE_TTL_MINUTES ?? 60);

const app = createServer({
  engine: httpEngine(ENGINE_URL),
  staticDir: STATIC_DIR,
  cache: new ResponseCache(CACHE_ENTRIES, CACHE_TTL_MINUTES * 60_000),
});

app.listen(PORT, () => {
  console.log(`curve-lab api on :${PORT}, engine at ${ENGINE_URL}`);
});
