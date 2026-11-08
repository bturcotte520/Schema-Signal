#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"
: "${OPENROUTER_API_KEY:?Set OPENROUTER_API_KEY in your environment}"
printf '%s\n' 'This sends TWO requests to OpenRouter and may incur charges.' >&2
for setting in off on; do
  printf '\n%s\n' "require_parameters=$setting" >&2
  curl --silent --show-error --fail-with-body --max-time 120 \
    'https://openrouter.ai/api/v1/chat/completions' \
    -H "Authorization: Bearer ${OPENROUTER_API_KEY}" \
    -H 'Content-Type: application/json' \
    --data-binary "@request-$setting.json"
  printf '\n'
done
