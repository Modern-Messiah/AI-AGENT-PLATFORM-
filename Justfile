# AI Agent Platform — task runner.
#
#   just          — show available recipes
#   just up       — one-command full stack (infra + migrations + api + worker + ui)
#
# Recipes are split by area into just/*.just and imported here, so all
# commands stay flat (`just up`, `just test`, …). Recipes load .env
# automatically, the same file docker compose reads.

set dotenv-load

api_port := env_var_or_default('API_PORT', '8000')

import 'just/stack.just' # up / infra / down / restart / reset / logs / ps / build / tls / validate
import 'just/provision.just' # migrate / seed / key
import 'just/dev.just' # install / dev-infra / dev-api / dev-worker / dev-ui
import 'just/quality.just' # test / test-ui / test-e2e / lint / lint-ui / format
import 'just/ops.just' # backup / psql / ch / sh / clean

# Show available recipes.
[group('stack')]
@default:
    just --list
