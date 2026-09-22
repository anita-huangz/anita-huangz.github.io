# Three stages, two runtime images. The engine and the BFF are separate
# services because they are separate languages and scale differently: the
# engine is CPU-bound Python holding an 11,261-row curve, the BFF is an idle
# event loop with a cache. `--target` picks which one is built.

# --------------------------------------------------------------- client build
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci 2>/dev/null || npm install
COPY web/ ./
RUN npm run build


# ------------------------------------------------------------------ BFF build
FROM node:22-slim AS api-build
WORKDIR /api
COPY api/package.json api/package-lock.json* ./
RUN npm ci 2>/dev/null || npm install
COPY api/ ./
RUN npm run build


# ---------------------------------------------------------------- BFF runtime
FROM node:22-slim AS api
RUN useradd --create-home --uid 10001 app
WORKDIR /app
ENV NODE_ENV=production
COPY api/package.json api/package-lock.json* ./
# Production install: the dev dependencies are a TypeScript compiler and a
# test runner, neither of which belongs in a running container.
RUN npm ci --omit=dev 2>/dev/null || npm install --omit=dev
COPY --from=api-build /api/dist ./dist
COPY --from=web /web/dist ./public
USER app
ENV PORT=8080 CURVE_STATIC_DIR=/app/public
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:8080/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "dist/index.js"]


# --------------------------------------------------------------- engine wheel
FROM python:3.12-slim AS wheel
WORKDIR /build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip build && python -m build --wheel --outdir /dist


# ------------------------------------------------------------- engine runtime
FROM python:3.12-slim AS engine
RUN useradd --create-home --uid 10001 app
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
COPY --from=wheel /dist/*.whl /tmp/
# The forecast route needs XGBoost; everything else does not, which is why it
# is an extra rather than a dependency.
RUN pip install --upgrade pip \
    && pip install /tmp/*.whl "fastapi>=0.110" "uvicorn[standard]>=0.29" "xgboost>=2.0" \
    && rm -f /tmp/*.whl
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=4).status==200 else 1)"
CMD ["uvicorn", "curve_lab.service.app:app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
