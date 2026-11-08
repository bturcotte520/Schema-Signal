# Schema Signal

**Turn “my JSON schema sometimes fails” into a small, reviewable OpenRouter reproduction.**

A Python CLI that sends the same structured-output request with
`provider.require_parameters` off and on, checks the returned JSON locally, and
exports a diagnostic report plus scrubbed request bodies and a curl replay script.
Use the built-in synthetic example or your own local prompt and JSON Schema.

**Status: offline verification complete; live verification and recording outstanding.**
No live OpenRouter result has been observed by the finishing assistant. The owner
approved a $0.01 local test and chose to supply the key in their own terminal.
The checked-in demo is fictional, not evidence of an API integration succeeding.
Repository: [Schema-Signal](https://github.com/bturcotte520/Schema-Signal).
No public deployment, API credentials, or private input files are included.

## Who this is for, and the developer pain

For a developer integrating OpenRouter structured outputs, “the model supports
schemas” does not answer “did this serving endpoint support this request?”

- In [simonw/llm-openrouter #28](https://github.com/simonw/llm-openrouter/issues/28)
  (March 10, 2025), a maintainer documented the distinction between model-level
  schema support and provider-level support and the need for the routing flag.
  This is historical integration evidence; the issue was closed in September 2025.
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
provider. Local validation remains necessary. Sources rechecked November 8, 2026.

**Two separate settings:** `response_format.json_schema.strict` requests the
provider's strict schema behavior and is **true in both runs**.
`provider.require_parameters` controls provider eligibility and is the only value
changed. It does not guarantee valid output or fix a routing bug. Both responses
may validate, both may fail, or the results may differ. Two requests are not a
benchmark or proof of causation.

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
Review all bundle files before sharing. Request files retain prompt/schema contents; scrubbing is not anonymization.
  require_parameters=false  schema_mismatch   provider=Fictional fixture provider
  require_parameters=true   valid             provider=Fictional fixture provider
Bundle: runs/demo
```

The demo intentionally returns `quantity: "3"` for one response and `quantity: 3`
for the other to demonstrate JSON-valid vs schema-valid. It is **not evidence of
real routing behavior**. See [the generated demo report](examples/demo/report.md).

The checked-in demo is an earlier fictional snapshot. Generate `runs/demo` with
the current CLI to see the expanded timing, settings, and privacy sections.

### Use your own prompt and schema

Create a UTF-8 text prompt and a UTF-8 JSON Schema in `private-inputs/` (gitignored).
Supply both files; omit both to retain the purchase example:

```sh
python -m schema_signal \
  --prompt-file private-inputs/prompt.txt \
  --schema-file private-inputs/schema.json \
  --acknowledge-private-inputs --out runs/custom-preview
```

This is a **dry run**. Inspect the request files before adding `--live` and choosing
a fresh output directory. Live mode sends both your prompt and schema to OpenRouter
and a serving provider. Check their data policies before using private inputs.

Each file is capped at 64 KiB. Empty prompts, invalid UTF-8/JSON, duplicate JSON
keys, non-finite numbers, and invalid schemas fail locally before network calls.
Schemas must be JSON objects using Draft 2020-12 (omit `$schema` or use
`https://json-schema.org/draft/2020-12/schema`). Reference keys (`$ref`, `$dynamicRef`,
`$recursiveRef`) are conservatively rejected anywhere in the schema document;
inline definitions instead. No remote schema is retrieved. Other drafts are
rejected rather than silently validated with the wrong dialect. `format` remains
an annotation, not an assertion. Local validity does not mean a provider supports
every keyword. `--demo` cannot be combined with custom files.

The response validator uses **the schema sent in that request**, including nested
properties, arrays, required fields, and constraints, not the purchase schema.
Schema failures expose keyword names only, not values or private property names.

**Review required:** the acknowledgment permits local saving, not publication.
`request-off.json` and `request-on.json` retain prompt text, schema property names,
descriptions, examples, and other business data. Secret-pattern scrubbing is not
anonymization. Review every bundle file before sharing it; never upload a whole
custom bundle automatically. A scrubbed request may differ from what was sent
when a secret-like string was removed, so it may not be an exact replay.

### Run against OpenRouter

Choose a currently available model from [OpenRouter's models](https://openrouter.ai/models).
On November 8, 2026, the public [GPT-4o-mini endpoint listing](https://openrouter.ai/api/v1/models/openai/gpt-4o-mini/endpoints)
listed `openai`, `azure`, and `azure/swedencentral`, all advertising
`response_format` and `structured_outputs`. The `openai` endpoint listed $0.15 per
million input tokens and $0.60 per million output tokens. This catalog check is
not an inference test or an availability guarantee. Recheck pricing before running:

```sh
curl --fail --silent --show-error \
  https://openrouter.ai/api/v1/models/openai/gpt-4o-mini/endpoints
```

For the approved local test, use synthetic defaults, `--provider openai`, and 256
maximum output tokens. Two capped outputs cost at most $0.0003072 at that output
rate, plus input charges. This estimate is not a hard spending cap; use a key
limited to $0.01. Pinning one provider makes this a deliberately narrow diagnostic,
not a comparison of providers. Both requests still go through **OpenRouter**.

The following works in Bash or zsh from the project root. It reads the OpenRouter
key with hidden input, places it only in the process environment, and exits after
the run. Never paste a key into chat, command arguments, a recording, or a report.
Do not use shell tracing. Keep credential entry off-camera.

```sh
.venv/bin/python -c 'import getpass, os; from schema_signal.cli import main; os.environ["OPENROUTER_API_KEY"] = getpass.getpass("OpenRouter key (hidden): "); raise SystemExit(main(["--live", "--model", "openai/gpt-4o-mini", "--provider", "openai", "--max-tokens", "256", "--out", "runs/live-1"]))'
```

`--live` sends up to **two billable generation requests**, each with a default
`max_tokens` of 256, plus at most two read-only generation metadata requests.
The prompt and schema are sent to OpenRouter and the selected provider.
There is no CLI dollar spending cap; token limits are not price limits.
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
| `report.json` | Mode, per-request UTC start, settings, HTTP status, returned model/provider, latency, validation, and usage/cost when returned |
| `request-off.json` | Prompt/schema request with `require_parameters: false`, secret-scrubbed but potentially private |
| `request-on.json` | Same request with `require_parameters: true`, subject to the same privacy limitations |
| `reproduce.sh` | Portable curl replay using an environment variable, not a saved key |

Only after reviewing and sanitizing their contents, attach selected files to a bug report. Run
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

`elapsed_ms` measures the generation HTTP round trip, excluding metadata lookup;
it is not time to first token. Missing/null usage, cost, model, or provider fields
mean unavailable, never zero. The API's `usage.cost` is reported as a credit charge
per [Usage Accounting](https://openrouter.ai/docs/guides/guides/usage-accounting).
No output text is stored, so two `valid` statuses establish identical validation
outcomes, not identical response content.
When a provider metadata lookup also returns `total_cost`, it is retained as
`usage.total_cost_usd`. No extra metadata call is made solely to obtain cost.

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

- The default prompt/schema is synthetic. Custom request files are potentially
  private and require explicit acknowledgment before being saved. The CLI prints
  a review warning and records `review_required_before_sharing: true`.
- Authorization headers are never serialized. Known key strings and bearer-token
  patterns are scrubbed defensively before export and console result summaries.
- Raw output, reasoning, raw errors, generation IDs, and arbitrary response
  metadata are not written. Reports retain operational model/provider labels,
  token counts, and cost when present. Review those before sharing.
- JSON Schema errors list only failed keywords, never offending instance values.
- API host is fixed to `https://openrouter.ai`; redirects are not followed.
  Responses have a 2 MiB cap. There is no telemetry or automatic report upload.
- New bundle directories use owner-only permissions on POSIX. `runs/`, `.env*`,
  and `private-inputs/` are gitignored; this is not protection for files placed
  elsewhere or force-added to Git. Input paths are not stored in reports.
- Do not paste credentials into model/provider arguments. The curl script keeps
  credentials out of files, but local process inspection may expose curl arguments;
  prefer the Python CLI on a shared machine. Never run either with shell tracing.

## Technical choices and scope

- **Plain HTTP, not an SDK:** the OpenRouter-specific routing object remains
  visible, and the exported body mirrors the payload apart from secret scrubbing.
- **Python standard library transport:** no HTTP framework needed for two requests.
  `jsonschema` is the sole runtime dependency instead of a hand-written validator.
- **Local JSON Schema validation:** Draft 2020-12 for the actual request schema;
  provider support for arbitrary schema keywords is not inferred from local validity.
- **One variable changed:** the requests differ only in the routing boolean.
  They still are two sequential stochastic observations, not proof of causation.
- **No retry/repair layer:** useful for a reproduction because failures remain
  observable, and uncertain billable requests are not silently duplicated.
- **Allowlisted evidence:** fewer details than a complete trace, but safer to
  share and less likely to turn a bug report into a data leak.

Deliberately excluded: web UI, arbitrary full API request ingestion, streaming,
Responses API support, model capability crawler,
schema editor, response healing, benchmarking, automatic public issue creation,
hosting, authentication storage, and repeated paid tests.

No dashboard, schema editor, or new runtime dependency was added for custom input.

## Verification record

Finishing verification on November 8, 2026, using Python 3.14 and jsonschema 4.26.0:

- 46 unit/integration tests passed with mocked HTTP. Run
  `python -m unittest discover -s tests -v` to reproduce, not a live-test command.
- CLI dry-run and offline demo passed; generated request bodies differ only in
  `provider.require_parameters`.
- Live-mode control flow tested with fake HTTP responses, including missing key,
  HTTP errors, timeout/no retry, provider metadata fallback, redaction, refusal,
  truncation, non-JSON bodies, and schema mismatch.
- Custom-schema tests cover nested arrays/constraints, rejection of the old
  purchase-shaped output, and an empty schema that must not fall back to defaults.
- Privacy tests inspect every generated file for fake secret strings and verify
  arbitrary customer/schema data stays out of reports but remains in request files.
- The first test attempt failed because the active Python lacked `jsonschema`.
  Creating `.venv` and installing with `pip install -e .` resolved it. This is an
  environment/setup finding, not a live API failure.
- Installed CLI demo/dry-run, bytecode compilation, replay shell syntax, and
  gitignore exclusions passed. Generated fictional reports were inspected: no
  private user data or credentials appeared. The old 37-test transcript was
  removed rather than presented as current verification.

**Not verified:** live inference, actual charges, runtime endpoint compliance,
behavior on another OS/Python version, or third-party usability. Advertised
endpoint capability/pricing was checked, not proven. No fake live result is
presented as a successful integration. No public deployment is planned.

### Real results: outstanding

No real report is checked in. The owner selected local credential entry and local
execution; the assistant has neither an API key nor an observed live result.
After the approved run, inspect `runs/live-1/report.md` and `report.json`. They
record the actual response model/provider when returned, UTC start, settings,
status/error code, JSON/schema validation, generation latency, and usage/cost when
available. Review the files before adding any real result to the repository.
Do not replace missing values with estimates or convert a mocked result to LIVE.

If both runs validate, the finding is simply that both observed responses matched
the schema. That is compatible with the documented soft routing preference and
does not show the flag is unnecessary. If results differ, preserve the errors and
provider evidence without claiming the flag caused the difference. If a timeout
occurs, check account activity before spending again. This section must remain
outstanding until an actual run has been inspected.

## Learnings and time

- The routing docs already prefer response-format-capable providers even with
  `require_parameters=false`. A forced success/failure story would misrepresent
  the feature; the fictional fixture demonstrates report states only.
- Adding custom input is not just adding CLI flags: validation must follow the
  exact supplied schema. A test using a non-purchase schema caught that boundary.
- Redacting API-key patterns does not remove customer names or business schemas.
  Keeping raw responses out helps, but request files still need human review.
- Local schema validity, advertised endpoint support, and observed runtime
  compliance are different kinds of evidence. Live-run learnings are pending;
  there are no observed latency, cost, or success claims yet.

**Time accounting:** the assignment allows three hours total, including the
separate Discord task. This finishing session began November 8 at 20:14 UTC;
implementation and the first 46-test pass were complete by 20:41 UTC (about 27
minutes elapsed, including approval waits). Documentation and final offline
verification continued through 21:57 UTC, bringing this session's elapsed wall
time to at least 1 hour 43 minutes, including user-response waits; publication
adds further time. Active work time was not separately measured.
The previous build's actual duration and time already spent
on Discord are not known; the old README's "roughly one-hour" wording was not a
verified time log. The owner must add their actual total before submission. This
repository does not claim the three-hour requirement has been met.

**AI assistance:** Kilo (OpenAI gpt-6-astra) inspected and edited code/tests/docs,
used an internal research agent to verify sources and public endpoint pricing,
and ran local verification. This is an AI-assisted implementation, not solely
handwritten work. Earlier AI involvement and owner work time are not independently
known. Source reports are attributed; no Discord participation or live API
experience is invented.

## Recording script (80 seconds)

**Recording outstanding.** No recording was created by the assistant. Record a
terminal/editor window only, hide notifications, and keep credentials/account
pages off-camera. Use synthetic data. Preinstall dependencies and precheck price;
enter the key with capture paused. Do not rerun an already completed paid test
just to get a nicer result without approving the extra spend.

1. **0-12s:** Show the README pain/evidence. Say: "Schema Signal makes a small
   OpenRouter structured-output reproduction. Model support alone does not tell
   me what happened on the serving provider."
2. **12-22s:** Show setup commands: `python3 -m venv .venv`, activate, and
   `python -m pip install -e .`. Explain the API key is supplied through the
   environment, never stored. Do not show credential entry.
3. **22-40s:** Show the actual approved live command/result, using the synthetic
   defaults and `--provider openai --max-tokens 256`. If the call takes longer,
   cut the waiting time, not the outcome. Say it makes at most two generations.
4. **40-52s:** Show `diff -u runs/live-1/request-off.json runs/live-1/request-on.json`.
   Say: "Strict is true in both. Only require_parameters changes; it filters
   provider support, not the validity of the returned JSON."
5. **52-70s:** Open the actual `runs/live-1/report.md`. Read the real statuses,
   returned model/provider, validation, latency, and available usage. If both
   validate, say so. If either fails or data is missing, show that honestly.
6. **70-80s:** Say: "Two observations are not a benchmark or proof of causation.
   Custom prompt/schema files work too, but request files may contain private
   data and must be reviewed before sharing."

If the live run is not completed, record only an explicitly fictional offline
walkthrough and state that the submission's real-run requirement is unfinished.

## Submission and Discord

Use the existing [Schema-Signal repository](https://github.com/bturcotte520/Schema-Signal),
not a duplicate. The owner explicitly overrode the initial private-only request
and authorized this existing public repository. No deployment is needed; submit
its URL plus the completed recording link. Keep generated runs and private inputs
out of Git unless individual sanitized files have been deliberately reviewed.

The **Discord assignment is separate and outstanding**. It needs firsthand
observations from the actual OpenRouter Discord, recorded by the owner with
channel/date/context and respectful treatment of members' private information.
The GitHub issues above are GitHub research, not Discord research. No Discord
observations, participation, or announcement posts were fabricated or made.

Success for the next iteration: a developer can produce a minimal, safe,
provider-aware bug report in under five minutes, and a maintainer can replay it
without asking for the missing routing settings. This is a proposed success
criterion, not a measured result.
