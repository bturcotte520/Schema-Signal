# Schema Signal

**Turn “my JSON schema sometimes fails” into a small, reviewable OpenRouter reproduction.**

A Python CLI that sends the same synthetic extraction request with
`provider.require_parameters` off and on, checks the returned JSON locally, and
exports a redacted report plus exact request bodies and a curl replay script.

**Status: runnable prototype, tested offline. No live OpenRouter requests have
been made for this submission. No API key, credits, deployed service, or public
repository is included.** The checked-in demo is fictional and labeled as such.

## Who this is for, and the developer pain

For a developer integrating OpenRouter structured outputs, “the model supports
schemas” does not answer “did this serving endpoint support this request?”

- In [simonw/llm-openrouter #28](https://github.com/simonw/llm-openrouter/issues/28)
  (March 10, 2025), a maintainer documented the distinction between model-level
  schema support and provider-level support and the need for the routing flag.
  This is a concrete integration problem, not a hypothetical feature idea.
- [Handy #2271](https://github.com/cjpais/Handy/issues/2271) (October 12, 2026)
  reports an application requesting a schema without requiring provider parameter
  support. Those observations belong to that reporter; this project has not
  independently reproduced that issue.

The current [provider-routing documentation](https://openrouter.ai/docs/guides/routing/provider-selection#requiring-providers-to-support-all-parameters)
adds a crucial qualification: `response_format` is a soft preference even when
`require_parameters` is false. If supporting providers exist for a model, they
are preferred by that rule; if none support the parameter, it can be ignored.
With the flag true, every requested parameter must be supported. Therefore this
tool does **not** promise the off case will fail, the on case will succeed, or
that any difference was caused by this flag alone.

OpenRouter's [structured-output guide](https://openrouter.ai/docs/guides/features/structured-outputs)
also says support varies by endpoint and strict-mode enforcement varies by
provider. Local validation remains necessary. Sources checked November 7, 2026.

## Try it in two minutes

Requires Python 3.10+; curl is needed only for the optional replay script.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .

# Offline walkthrough. No key and no network calls.
python -m schema_signal --demo --out runs/demo

# Preview the exact requests without executing them.
python -m schema_signal --model openai/gpt-4o-mini --out runs/preview

# Run the tests. All HTTP is mocked; this never calls OpenRouter.
python -m unittest discover -s tests -v
```

Demo console output, from fictional fixtures:

```text
Schema Signal | DEMO: SIMULATED, NOT LIVE
  require_parameters=false  schema_mismatch   provider=Fictional fixture provider
  require_parameters=true   valid             provider=Fictional fixture provider
Bundle: runs/demo
```

The demo intentionally returns `quantity: "3"` for one response and `quantity: 3`
for the other to demonstrate JSON-valid vs schema-valid. It is **not evidence of
real routing behavior**. See [the generated demo report](examples/demo/report.md).

### Run against OpenRouter

Choose a currently available model from [OpenRouter's models](https://openrouter.ai/models).
The default model ID is a convenient starting point, not a claim about current
availability or pricing. Check the model's Providers section for endpoint support.

Set `OPENROUTER_API_KEY` in your shell or secret manager. For example, in Bash:

```sh
read -r -s -p 'OpenRouter API key: ' OPENROUTER_API_KEY; printf '\n'
export OPENROUTER_API_KEY

python -m schema_signal --live --model openai/gpt-4o-mini --out runs/live-1

# Optional: pin a provider slug copied from the model's provider list.
# Replace PROVIDER_SLUG, and choose a fresh output directory.
python -m schema_signal --live --model openai/gpt-4o-mini \
  --provider PROVIDER_SLUG --out runs/pinned-1

unset OPENROUTER_API_KEY
```

`--live` sends up to **two billable generation requests**, each with a default
`max_tokens` of 256, plus at most two read-only generation metadata requests.
The synthetic purchase sentence and schema are sent to OpenRouter and the selected
provider. There is no dollar spending cap; token limits are not price limits.
Inspect model pricing and use a separately limited key before running.

The second generation is skipped after an HTTP 401, 402, 403, or 429. Other cases
are compared as requested. No network operation is retried automatically. A
timeout may still have generated output and incurred cost on the server.

Use `--timeout 60` for a slower endpoint or `--max-tokens 512` if output is
truncated. Both values remain identical across the comparison. Increasing them
can change latency or cost. `--provider` sets `only: [slug]` and disables
fallbacks, so a requested provider without support may produce an error.

## What you receive

Every invocation creates a new directory; existing directories are never overwritten.

| File | Purpose |
| --- | --- |
| `report.md` | Human-readable comparison and interpretation caveats |
| `report.json` | Mode, timestamp, HTTP status, validation, usage, and observed provider evidence |
| `request-off.json` | Exact synthetic request with `require_parameters: false` |
| `request-on.json` | Identical request with `require_parameters: true` |
| `reproduce.sh` | Portable curl replay using an environment variable, not a saved key |

Attach the reviewed report and request files to a bug report. Run
`sh runs/live-1/reproduce.sh` to replay both requests. **Replay incurs new calls**
and prints raw responses to your own terminal. It does not validate schema and
stops at the first HTTP error. Do not publish raw responses without review.

### Reading the results

- `valid`: complete JSON matching the local schema. Not a check of extraction accuracy.
- `schema_mismatch`: JSON parsed, but fields/types or additional properties did not match.
- `invalid_json`: no repair or markdown-fence removal is attempted. Duplicate keys
  and non-finite numbers are rejected too.
- `truncated`: the API reported a length limit, even if the available text parses.
- `refusal`, `missing_content`, `malformed_response`, `invalid_api_json`: separate
  output/transport-envelope conditions, not automatically blamed on routing.
- `http_error` / `upstream_error`: inspect HTTP/numeric API codes. A 400 can mean
  bad parameters, 401 authentication, 402 credits, 429 rate limits. A 404 alone
  does not prove which routing constraint failed. Full error strings are omitted
  from exports because providers can echo request data.
- `network_or_timeout`: uncertain remote outcome. Check your OpenRouter activity
  before manually retrying.
- `unknown` provider: unavailable evidence, **not** an inferred provider name.

The tool prefers the actual response's `provider` field. When that is absent but
a valid generation ID is returned, it makes one call to
[`GET /generation?id=...`](https://openrouter.ai/docs/api/api-reference/generations/get-request-&-usage-metadata-for-a-generation)
and reads `data.provider_name`. Metadata may not be immediately available; no
polling or provider guessing is performed. This identifies a reported serving
provider, not every route attempted or an exact endpoint/region.

Exit codes: `0` = dry run/demo completed, or both live responses validated;
`1` = at least one live result was not valid; `2` = local configuration/output error.
Schema-mismatch demo fixtures deliberately exit zero so the offline walkthrough
can be used as a smoke test.

## Redaction and safety boundaries

- A fixed, synthetic prompt/schema is intentional: both request files can be
  shared without trying to guess which parts of a real customer prompt are private.
- Authorization headers are never serialized. Known key strings and bearer-token
  patterns are scrubbed defensively before export and console result summaries.
- Raw output, reasoning, raw errors, generation IDs, and arbitrary response
  metadata are not written. Reports retain operational model/provider labels,
  token counts, and cost when present. Review those before sharing.
- JSON Schema errors list only failed keywords, never offending instance values.
- API host is fixed to `https://openrouter.ai`; redirects are not followed.
  Responses have a 2 MiB cap. There is no telemetry or automatic report upload.
- Do not paste credentials into model/provider arguments. The curl script keeps
  credentials out of files, but local process inspection may expose curl arguments;
  prefer the Python CLI on a shared machine. Never run either with shell tracing.

## Technical choices and scope

- **Plain HTTP, not an SDK:** the OpenRouter-specific routing object remains
  visible, and the exported body is the same payload the CLI sends.
- **Python standard library transport:** no HTTP framework needed for two requests.
  `jsonschema` is the sole runtime dependency instead of a hand-written validator.
- **Local JSON Schema validation:** Draft 2020-12 for this small object schema;
  provider support for arbitrary schema keywords is not inferred from local validity.
- **One variable changed:** the requests differ only in the routing boolean.
  They still are two sequential stochastic observations, not proof of causation.
- **No retry/repair layer:** useful for a reproduction because failures remain
  observable, and uncertain billable requests are not silently duplicated.
- **Allowlisted evidence:** fewer details than a complete trace, but safer to
  share and less likely to turn a bug report into a data leak.

Deliberately excluded from this roughly one-hour scope: web UI, arbitrary/private
request ingestion, streaming, Responses API support, model capability crawler,
schema editor, response healing, benchmarking, automatic public issue creation,
hosting, authentication storage, and repeated paid tests.

If extending this, the next step is an explicitly reviewed **sanitized custom
request** input with provider-capability snapshots. That would make the kit more
useful for production-specific failures without pretending automatic redaction
can safely sanitize every customer schema and prompt.

## Verification record

Executed locally on November 7, 2026 with Python 3.12.14 and jsonschema 4.26.0:

- 37 unit/integration tests passed with mocked HTTP.
- CLI dry-run and offline demo passed; generated request bodies differ only in
  `provider.require_parameters`.
- Live-mode control flow tested with fake HTTP responses, including missing key,
  HTTP errors, timeout/no retry, provider metadata fallback, redaction, refusal,
  truncation, non-JSON bodies, and schema mismatch.
- Bytecode compilation and shell syntax validation passed.
- Local wheel build, installation, entry-point version check, and installed CLI
  demo passed in a temporary virtual environment reusing installed dependencies.
  A clean dependency download/install on another machine was not tested.

**Not verified:** a live API request, current endpoint capability/availability,
actual charges, behavior on another OS/Python version, external publication,
deployment, or third-party developer usability testing. No fake live result is
presented as a successful integration.

## A short DevRel demo

1. Point to the real issue and explain model support vs provider support.
2. Run `--demo`; show JSON validity and schema validity are different checks.
3. Diff `request-off.json` and `request-on.json`; exactly one flag changes.
4. Show provider evidence and the redacted support bundle.
5. Explain why matching live results are informative, and why two samples are
   not proof that the flag caused a difference.

Success for the next iteration: a developer can produce a minimal, safe,
provider-aware bug report in under five minutes, and a maintainer can replay it
without asking for the missing routing settings. This is a proposed success
criterion, not a measured result.
