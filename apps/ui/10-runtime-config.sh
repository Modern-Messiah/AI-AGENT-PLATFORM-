#!/bin/sh
# Write the runtime deployment config consumed by src/utils/apiConfig.js.
# The tenant API key is injected HERE, at container start — never as a
# Vite build arg, which would inline it into the publicly served bundle.
set -e

js_escape() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr -d '\n\r'
}

key="$(js_escape "${UI_API_KEY:-}")"
base="$(js_escape "${UI_API_BASE_URL:-/api}")"

printf 'window.__AAP_CONFIG__ = { apiKey: "%s", baseUrl: "%s" };\n' "$key" "$base" \
  > /usr/share/nginx/html/runtime-config.js
