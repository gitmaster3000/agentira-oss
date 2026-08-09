#!/usr/bin/env bash
#
# Automate the frontend PR-preview on Railway (AP-287).
#
# Railway auto-creates an EMPTY environment "agentira-frontend-pr-<N>" for each
# PR (the project has botPrEnvironments + focusedPrEnvironments on), but the
# "focused" mode never actually attaches the frontend service — so the env is
# an empty shell and nothing deploys. This script does, via the API, exactly
# what you'd otherwise do by hand in the dashboard:
#
#   1. find the PR's auto-created environment
#   2. if it has no service, create one from the repo on the PR branch
#   3. give that service a public domain
#   4. wait for the deploy and print the preview URL
#
# The frontend's nginx proxies /api -> the prod API (see nginx.conf), so a
# preview is frontend-only: real data, zero backend spun up, cheap.
#
# Usage:
#   scripts/railway-pr-preview.sh <PR_NUMBER> [BRANCH]
#   RAILWAY_API_TOKEN=... scripts/railway-pr-preview.sh 85 fix/ap286-ap284-chat-surface
#
# Token: $RAILWAY_API_TOKEN, else /tmp/.rwtok. Get one at
# railway.com -> Account -> Tokens (and revoke when done).

set -euo pipefail

PROJECT_ID="5757a4f8-41d2-46ae-b5e0-108857540386"   # flowty
REPO="gitmaster3000/agentira-frontend"
ENV_PREFIX="agentira-frontend-pr-"
SERVICE_NAME="agentira-frontend"
GQL="https://backboard.railway.com/graphql/v2"

TOK="${RAILWAY_API_TOKEN:-$(cat /tmp/.rwtok 2>/dev/null || true)}"
[ -n "$TOK" ] || { echo "ERROR: no Railway token (set RAILWAY_API_TOKEN or write /tmp/.rwtok)"; exit 1; }

PR="${1:?usage: railway-pr-preview.sh <PR_NUMBER> [BRANCH]}"
BRANCH="${2:-$(git rev-parse --abbrev-ref HEAD)}"
ENVNAME="${ENV_PREFIX}${PR}"

# POST a GraphQL query/mutation (arg $1 = JSON body) and echo the raw response.
gql() { curl -s "$GQL" -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" -d "$1"; }
# Run a python snippet over stdin (json on stdin as `d`).
pick() { python3 -c "import sys,json;d=json.load(sys.stdin);$1"; }

echo "→ resolving env $ENVNAME"
ENVID=$(gql "{\"query\":\"query{ project(id:\\\"$PROJECT_ID\\\"){ environments{edges{node{id name}}} } }\"}" \
  | pick "print(next((e['node']['id'] for e in d['data']['project']['environments']['edges'] if e['node']['name']=='$ENVNAME'),''))")
[ -n "$ENVID" ] || { echo "ERROR: no environment '$ENVNAME' — open PR #$PR first so Railway creates it."; exit 1; }
echo "  env id: $ENVID"

echo "→ checking for a service in the env"
SVCID=$(gql "{\"query\":\"query{ environment(id:\\\"$ENVID\\\"){ serviceInstances{edges{node{serviceId}}} } }\"}" \
  | pick "e=d['data']['environment']['serviceInstances']['edges'];print(e[0]['node']['serviceId'] if e else '')")

if [ -z "$SVCID" ]; then
  echo "  none — creating '$SERVICE_NAME' from $REPO @ $BRANCH"
  SVCID=$(gql "{\"query\":\"mutation{ serviceCreate(input:{ name:\\\"$SERVICE_NAME\\\", projectId:\\\"$PROJECT_ID\\\", environmentId:\\\"$ENVID\\\", branch:\\\"$BRANCH\\\", source:{ repo:\\\"$REPO\\\" } }){ id } }\"}" \
    | pick "print(d['data']['serviceCreate']['id'])")
  echo "  created service: $SVCID"
else
  echo "  service exists: $SVCID"
fi

echo "→ ensuring a public domain"
DOM=$(gql "{\"query\":\"mutation{ serviceDomainCreate(input:{ environmentId:\\\"$ENVID\\\", serviceId:\\\"$SVCID\\\" }){ domain } }\"}" \
  | pick "print(((d.get('data') or {}).get('serviceDomainCreate') or {}).get('domain',''))" 2>/dev/null || true)
if [ -z "$DOM" ]; then   # already had one — read it back
  DOM=$(gql "{\"query\":\"query{ environment(id:\\\"$ENVID\\\"){ serviceInstances{edges{node{domains{serviceDomains{domain}}}}} } }\"}" \
    | pick "sd=d['data']['environment']['serviceInstances']['edges'][0]['node']['domains']['serviceDomains'];print(sd[0]['domain'] if sd else '')")
fi
echo "  https://$DOM"

echo "→ waiting for the deploy"
for _ in $(seq 1 40); do
  ST=$(gql "{\"query\":\"query{ environment(id:\\\"$ENVID\\\"){ serviceInstances{edges{node{latestDeployment{status}}}} } }\"}" \
    | pick "n=d['data']['environment']['serviceInstances']['edges'][0]['node']['latestDeployment'];print(n['status'] if n else 'NONE')")
  echo "  deploy: $ST"
  case "$ST" in
    SUCCESS)        echo "✓ preview live: https://$DOM"; exit 0;;
    FAILED|CRASHED) echo "✗ deploy $ST — check the Railway dashboard"; exit 1;;
  esac
  sleep 10
done
echo "… still building — it'll come up at https://$DOM"
