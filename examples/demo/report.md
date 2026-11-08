# Schema Signal report

Mode: **DEMO: SIMULATED, NOT LIVE**

Created: 2026-11-07T17:56:04.115790+00:00
Requested model: `openai/gpt-4o-mini`

| require_parameters | Result | HTTP | Provider observed | Evidence | JSON / schema |
| --- | --- | --- | --- | --- | --- |
| false | schema_mismatch | 200 | Fictional fixture provider | chat_response.provider | True / False |
| true | valid | 200 | Fictional fixture provider | chat_response.provider | True / True |

## Read this before drawing a conclusion

- DEMO is a fictional fixture, not OpenRouter evidence. DRY RUN makes no network calls.
- A live run is one observation per setting, not a causal experiment or a benchmark.
- Matching results are useful: response_format is already a soft routing preference.
- require_parameters=true filters all requested parameters, not just the schema.
- A provider name identifies the reported serving provider, not every attempted endpoint or fallback.
- Unknown routing stays unknown. A failed metadata lookup does not imply a provider failure.
- Schema-valid means structure only, not a correct extraction.
- A timeout has an uncertain server-side outcome and may still be billed. No POST is retried.

## Shareable reproduction

The request files use synthetic input. Report content excludes raw model output, raw errors,
authorization headers, and generation IDs. Model/provider labels and usage remain.
Review these files before sharing. No report is uploaded automatically.

`reproduce.sh` replays both requests and may incur charges. It prints raw API responses
to your own terminal; do not paste them publicly without review. Its successful exit
does not prove schema validity. Run the Python CLI for validation.
