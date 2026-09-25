# SEC Filing Intelligence

A multi-agent research platform over SEC EDGAR filings, served both as an HTTP
API and as an MCP server, with per-call token, cost, and latency telemetry.

Ask it a question about a public company; it plans the research, pulls the
relevant filings and financials from EDGAR, drafts a cited answer, and then runs
a separate verification pass that checks every citation against the evidence
actually gathered before the answer is returned.

Everything it reads is public: SEC EDGAR and daily closing prices. No API key is
needed to run the data layer, and the whole test suite runs offline.

![The research UI, showing the agent's run timeline and live cost telemetry](docs/screenshot-light.png)

## Try it without an API key

```bash
make install && make demo      # http://localhost:8000
```

`make demo` builds the UI and runs the stack against **real SEC EDGAR data**
with no credentials. Filings, figures, and quoted passages are genuine; the
answers are **extractive, not generative** — passages are selected by keyword
overlap against the filing the agent actually fetched, so it can quote but
cannot summarise, compare across filings, or decline an unanswerable question.
The UI says so in a banner. Set `ANTHROPIC_API_KEY` and
`FILING_INTEL_PROVIDER=anthropic` for real reasoning.

---

## Why it is built this way

The hard part of a system like this is not calling a model. It is everything
around the call: keeping the model from inventing citations, stopping a tool loop
that will not converge, knowing what a request cost, and being able to test any
of it without spending money. Each of those is a deliberate piece of the design.

| Concern | How it is handled |
|---|---|
| Model lock-in | Every layer speaks `ModelRequest`/`ModelResponse`. Anthropic, Bedrock, and replay are interchangeable via one config value. |
| Fabricated citations | A verifier node audits each finding against the gathered evidence and can mark the answer unverified. |
| Runaway tool loops | A hard tool-call ceiling in the graph, plus a capability grant the loop cannot reach outside of. |
| Unknown spend | Every model call emits a typed event with tokens, estimated USD, latency, and outcome. |
| Untestable AI code | A replay provider serves recorded responses, so CI exercises the real graph with no key and no cost. |
| Redis being down | The cache degrades to in-process with identical TTL semantics; a cache outage costs latency, not a 500. |

---

## Architecture

```
                    ┌──────────────┐        ┌──────────────┐
   HTTP  ──────────▶│  FastAPI     │        │  MCP server  │◀────── Claude Code,
                    │  /v1/research│        │  (stdio)     │        Claude Desktop
                    └──────┬───────┘        └──────┬───────┘
                           └───────┬───────────────┘
                                   ▼
                        ┌─────────────────────┐
                        │  FilingIntelRuntime │
                        └──────────┬──────────┘
                                   ▼
            ┌──────────────────────────────────────────────┐
            │  LangGraph workflow                          │
            │                                              │
            │   plan ─▶ research ⇄ tools ─▶ analyze ─▶ verify
            │            │                                 │
            └────────────┼─────────────────────────────────┘
                         ▼
        ┌────────────────────────────────┐   ┌──────────────────┐
        │  Tool registry                 │   │  Model providers │
        │  · Pydantic arg validation     │   │  · Anthropic     │
        │  · capability enforcement      │   │  · Bedrock       │
        │  · cache lookup                │   │  · replay        │
        │  · telemetry emit              │   └──────────────────┘
        └───────┬────────────────────────┘
                ▼
        ┌───────────────┐   ┌──────────────────┐
        │  SEC EDGAR    │   │  Redis / memory  │
        │  daily prices │   │  cache, sessions │
        └───────────────┘   └──────────────────┘
```

`research` and `tools` form the agentic loop. Every other node is a single model
call whose response is constrained by a JSON schema.

---

## The tools

Four, each with a Pydantic argument contract and a required capability:

| Tool | Capability | What it does |
|---|---|---|
| `search_filings` | `read_filings` | Recent filings of a form type, with accession numbers |
| `fetch_filing_section` | `read_filings` | One section of a filing: business, risk factors, MD&A, financials |
| `company_financials` | `read_financials` | Reported XBRL values for a US-GAAP concept across periods |
| `price_reaction` | `read_prices` | Cumulative return over N trading days after an event date |

A caller is granted a set of capabilities per request. Tools outside the grant
are not advertised to the model *and* are refused if it asks for one anyway —
hiding a tool is not a control on its own.

---

## Running it

```bash
make install                 # venv + dependencies
make check                   # lint and the full test suite, offline
```

### Against the live API

```bash
cp .env.example .env         # set ANTHROPIC_API_KEY and a real contact email
make serve                   # http://localhost:8000/docs
```

```bash
curl -s localhost:8000/v1/research -H 'content-type: application/json' -d '{
  "ticker": "AAPL",
  "question": "What supply chain risks does Apple disclose?"
}' | jq
```

```jsonc
{
  "ticker": "AAPL",
  "answer": "...",
  "findings": [
    {
      "claim": "...",
      "confidence": "high",
      "citations": [{"accession": "0000320193-23-000106", "form_type": "10-K", ...}]
    }
  ],
  "verified": true,
  "tool_calls_made": 3,
  "usage": {"input_tokens": 18442, "output_tokens": 1130, "cache_read_input_tokens": 12800},
  "estimated_cost_usd": 0.0584,
  "latency_ms": 9310.2
}
```

### With Redis

```bash
FILING_INTEL_SEC_USER_AGENT="you/0.1 (you@example.com)" docker compose up --build
```

### As an MCP server

```bash
make mcp
```

Or register it with an MCP host:

```jsonc
{
  "mcpServers": {
    "sec-filings": {
      "command": "filing-intel-mcp",
      "env": {
        "ANTHROPIC_API_KEY": "...",
        "FILING_INTEL_SEC_USER_AGENT": "you/0.1 (you@example.com)"
      }
    }
  }
}
```

The MCP server exposes the same four tools the internal agent uses — same
validation, same cache, same telemetry — plus `research_filings`, which runs the
whole workflow, and `telemetry_summary`.

---

## The UI

A React + Vite single-page app (`web/`) that streams the agent's run as it
happens rather than spinning until the whole workflow finishes.

- **Run timeline** — the plan, then each tool call with its actual arguments,
  then the analysis and the verifier's verdict, appearing as they complete
- **Cost telemetry** — tokens, estimated USD, latency, and tool-call count for
  the run just executed
- **Citations link to EDGAR** — every accession number resolves to the real
  filing on sec.gov
- **Light and dark** — both modes are selected from a validated palette and
  checked against their own surface, not an automatic inversion

Progress arrives over server-sent events from `GET /v1/research/stream`, one
event per completed graph node. The client uses `fetch` with a stream reader
rather than `EventSource`, because `EventSource` cannot surface a non-200 status
— a 422 from a bad ticker would otherwise appear as an opaque connection error.

```bash
make web        # Vite dev server on :5173, proxying the API on :8000
make web-build  # type-check and build into web/dist
```

When `web/dist` exists the API serves it at `/`, so the Docker image is the
whole application rather than an API needing a separate static host. The mount
is optional and happens last, so it can never shadow an API route.

<details>
<summary>Dark mode</summary>

![The same view in dark mode](docs/screenshot-dark.png)

</details>

---

## Telemetry

Every model call and tool call emits a typed event. `GET /v1/telemetry/summary`
aggregates them:

```jsonc
{
  "total_model_calls": 4,
  "total_tool_calls": 3,
  "total_usage": {"input_tokens": 18442, "output_tokens": 1130},
  "total_estimated_cost_usd": 0.0584,
  "model_failure_rate": 0.0,
  "cache_hit_rate": 0.33,
  "p50_model_latency_ms": 1840.0,
  "p95_model_latency_ms": 4210.0,
  "by_model": {"claude-opus-5": {"calls": 4, "estimated_cost_usd": 0.0584}},
  "by_tool": {"search_filings": {"calls": 1, "p95_latency_ms": 310.0}},
  "failures_by_kind": {}
}
```

Cost is computed from published per-model rates, with cached reads billed off
the *input* rate at 0.1x and cache writes at 1.25x. An unrecognised model
reports zero cost and sets `cost_is_estimated`, rather than silently guessing.

---

## Evaluation

A single run tells you the workflow *can* succeed. The harness runs each case
repeatedly and reports whether it *reliably* does:

```bash
make eval-offline     # no API key needed
```

```
==============================================================
  12 runs over 6 cases
==============================================================
  accuracy        83.3%   (graded checks passed)
  consistency    100.0%   (repeats agreed)
  reliability    100.0%   (completed without error)
  latency      p50 531ms / p95 1470ms
  cost         $0.5937 total, $0.04947/run
--------------------------------------------------------------
  failing checks:
       2x  answer_contains:not
--------------------------------------------------------------
  cases below 100%:
        0%  unanswerable-guard
==============================================================
```

Four distinct measurements, because they fail independently:

- **accuracy** — did the graded checks pass (expected tools called, citations
  present, verifier satisfied)?
- **consistency** — did repeated runs of the same case grade identically? A
  workflow that is right half the time is a different problem from one that is
  wrong every time.
- **reliability** — what fraction completed without raising?
- **cost and latency** — per run, so a quality gain has a visible price.

> **On the numbers above.** `--offline` swaps in a deterministic stub model and
> runs against *real* SEC EDGAR data. It measures the orchestration — tool
> routing, capability enforcement, caching, cost accounting, the verifier gate —
> not model quality, because there is no model in the loop. The one failing case
> is `unanswerable-guard`, which asks for a 2030 revenue forecast and expects the
> system to decline; the stub has no judgment, so it fails, and the harness
> correctly reports that. Measuring real accuracy means recording fixtures
> against the live API:
>
> ```bash
> FILING_INTEL_REPLAY_RECORD=true ANTHROPIC_API_KEY=... python -m evals.harness
> ```
>
> Subsequent runs replay those recordings for free and deterministically.

`--min-accuracy` exits non-zero below a threshold, so the suite can gate a
deploy.

---

## Retrieval: the section is four times longer than the tool showed

`fetch_filing_section` truncated to `max_chars` and returned the *front* of the
section. Measured on three real 10-Ks:

| | risk factors | the tool showed |
|---|---|---|
| Apple FY2023 | 67,995 chars | 29% |
| Microsoft FY2026 | 81,368 chars | 25% |
| NVIDIA FY2026 | 115,143 chars | **17%** |

Four-fifths of NVIDIA's disclosed risk was unreachable, and which fifth
survived was decided by position rather than by relevance.

Pass a `query` and the tool now pulls the section whole, splits it into
sentence-aligned passages carrying their character offsets, and returns the
ones that answer the question.

### Does it work? Twelve queries, three filings

Each case names a query and an **anchor** -- a phrase in the passage that
answers it. A retrieval is correct when a returned passage contains the anchor.
That is objective and recheckable: the anchors are in the committed fixture at
known offsets. Every target sits past character 20,000, which is the half of
the question truncation cannot answer at any quality.

```
truncation  recall@5   0.0%  (0/12)   mean rank of the hit —
bm25        recall@5  66.7%  (8/12)   mean rank of the hit 1.1
lsa         recall@5  83.3% (10/12)   mean rank of the hit 2.1
hybrid      recall@5  66.7%  (8/12)   mean rank of the hit 1.1
```

**Truncation scores zero**, by construction, and that is the finding: not that
it ranks badly, but that the text is not there to rank.

**The semantic retriever wins the two cases with no shared vocabulary** —
"returning cash to shareholders" finding the dividend passage, "concentrated in
particular places" finding the one about California and Asia. That is precisely
what it is supposed to buy, and the per-case table shows it is the only thing it
buys: everywhere the wording overlaps, BM25 matches it and ranks the hit higher
(1.1 against 2.1).

**Hybrid added nothing.** On the case LSA gets and BM25 misses, reciprocal rank
fusion puts the target at rank 6 — one place outside the cut, tied on score with
the passage at 5 and losing the tie-break. That is a near miss rather than a
structural failure. Lowering the fusion constant would fix this case; tuning it
on twelve cases would be fitting noise, so it is left alone and reported.

### On the word "semantic"

`SemanticRetriever` is latent semantic analysis: TF-IDF over unigrams and
bigrams, reduced by truncated SVD, compared by cosine. **It is a vector-space
embedding, not a neural one.** A sentence transformer would very likely retrieve
better; it also costs a 90 MB model download and a torch dependency, against a
standard that everything here runs offline in CI with no downloads and no keys.
The `Embedder` protocol is the seam for anyone willing to pay that.

It is also fitted on the section's own passages — a few hundred documents is a
small corpus for an SVD. It buys synonym tolerance *within the filing's*
vocabulary and nothing outside it.

```bash
python -m filing_intel.retrieval.benchmark   # reproduces the table above
```

### A bug this found

Building the fixture surfaced one. `extract_section` took the **last** match of
the Item heading, on the reasoning that the first is the table of contents.
NVIDIA's 10-K cross-references its own Items in prose — "see Item 1A. Risk
factors in this annual report" — five times. The last match landed on one of
those, found no closing boundary after it, and returned **123,360 characters of
financial-statement notes labelled as risk factors**: marketable securities, an
employee stock purchase plan, deferred tax attributes. The model would have
cited them as disclosed risks.

Headings sit at the start of a line and prose cross-references do not, so
line-start matches are now preferred, and a candidate must have a closing
boundary and clear a minimum length. Apple and Microsoft are unchanged; NVIDIA
goes from 123,360 characters to 115,143, all of which is risk disclosure.

## Testing

```bash
make test     # 322 tests, no network, no API key
```

The suite covers cost arithmetic, cache and TTL semantics, telemetry
aggregation, capability enforcement, EDGAR HTML parsing and section extraction,
provider request shaping, every branch of the agent graph (including the
tool-call ceiling, provider failure, refusal, and malformed model output), the
HTTP contract, and the eval harness itself.

Two things are faked: the network (EDGAR and prices, via `httpx.MockTransport`
and in-memory doubles) and the model (via scripted and replay providers).
Everything else is the real implementation.

---

## Configuration

Every setting is `FILING_INTEL_`-prefixed and validated by `pydantic-settings`.

| Variable | Default | Notes |
|---|---|---|
| `FILING_INTEL_PROVIDER` | `replay` | `anthropic`, `bedrock`, `replay`, or `demo` |
| `FILING_INTEL_MODEL` | `claude-opus-5` | |
| `FILING_INTEL_EFFORT` | `high` | `low` … `max` |
| `FILING_INTEL_REDIS_URL` | unset | Unset falls back to the in-process cache |
| `FILING_INTEL_SEC_USER_AGENT` | — | Must contain a contact email; EDGAR 403s otherwise |
| `FILING_INTEL_AGENT_MAX_TOOL_CALLS` | `8` | The loop ceiling |
| `FILING_INTEL_UI_DIST` | unset | Override the built-UI location |

The SEC user-agent rule is enforced at startup rather than left to surface as an
opaque 403 mid-request.

---

## Layout

```
src/filing_intel/
  contracts.py      typed boundaries shared by every layer
  config.py         validated settings
  errors.py         error taxonomy; each kind becomes a telemetry label
  providers/        Anthropic, Bedrock, replay, behind one interface
  telemetry/        typed events, per-model pricing, aggregation
  cache/            Redis with an in-process fallback; session state
  data/             SEC EDGAR and price clients
  retrieval/        chunking, BM25, LSA, and the benchmark that ranks them
  tools/            tool definitions and the registry that enforces them
  agents/           the LangGraph workflow and its prompts
  api/              FastAPI surface
  mcp_server.py     MCP surface
  providers/demo.py deterministic stub model, for running without a key
evals/              dataset, grading, harness
web/                React + Vite UI (components, SSE client, styles)
tests/              322 tests
```

---

## Notes and limits

- **Retrieval is lexical and latent-semantic, not neural.** See the section
  above: no pretrained embedding is downloaded, so "semantic" here means an SVD
  over the filing's own TF-IDF. The measured win over BM25 is two cases in
  twelve, which is one paraphrase away from a tie.
- **The retrieval benchmark is twelve queries over three filings.** Enough to
  show truncation cannot answer them and that retrieval can; not enough to rank
  BM25 against LSA with any confidence, and the README does not.
- **A passage containing the anchor is not the same as a good answer.** The
  benchmark measures whether the right text was put in front of the model, not
  whether the model then used it well. That second question needs a labelled
  answer set this does not have.

- Section extraction is regex over tag-stripped HTML. It handles the common
  10-K/10-Q layouts and the table-of-contents repetition, but EDGAR filings are
  not uniform and some will not parse. The tool reports failure rather than
  returning a wrong section.
- Cost figures are estimates against published first-party rates. Bedrock is
  partner-priced separately; those events are flagged `cost_is_estimated`.
- Sessions hold conversation state but the graph currently starts each question
  fresh; session accounting is wired, multi-turn context reuse is not.
- The UI shows one run at a time and does not persist history across reloads.
- Price data comes from a public unauthenticated endpoint with no SLA.
- XBRL returns overlapping contexts for one end date (a quarter and the
  year-to-date containing it). Facts carry their period span so the two are
  distinguishable rather than looking like contradictory values.
