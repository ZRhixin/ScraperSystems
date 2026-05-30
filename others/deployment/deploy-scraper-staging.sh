#!/bin/bash
# Deploy ScraperSystems to staging
# Container: scraper-staging  |  Port: 8001 (host) → 8000 (container)
# noVNC:     6080 (host) → 6080 (container)  — for CAPTCHA solving

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

IMAGE="heirmatrix-scraper-staging:latest"
CONTAINER="scraper-staging"
NETWORK="heirmatrix-staging-network"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()    { echo -e "${BLUE}[deploy]${NC} $*"; }
ok()     { echo -e "${GREEN}[ok]${NC} $*"; }
warn()   { echo -e "${YELLOW}[warn]${NC} $*"; }
die()    { echo -e "${RED}[error]${NC} $*"; exit 1; }

# ---------------------------------------------------------------------------
# Load env (SCRAPER_DB_URL required)
# ---------------------------------------------------------------------------
ENV_FILE="$REPO_ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
    set -o allexport
    source "$ENV_FILE"
    set +o allexport
fi

[[ -n "${SCRAPER_DB_URL:-}" ]] || die "SCRAPER_DB_URL is not set. Add it to $ENV_FILE or export it."

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
log "Building $IMAGE from $REPO_ROOT ..."
docker build -t "$IMAGE" "$REPO_ROOT"
ok "Image built."

# ---------------------------------------------------------------------------
# Stop + remove existing container (if any)
# ---------------------------------------------------------------------------
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    log "Stopping existing $CONTAINER ..."
    docker stop "$CONTAINER" >/dev/null 2>&1 || true
    docker rm   "$CONTAINER" >/dev/null 2>&1 || true
    ok "Old container removed."
fi

# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------
log "Starting $CONTAINER ..."
docker run -d \
    --name "$CONTAINER" \
    --network "$NETWORK" \
    --restart unless-stopped \
    -p 8001:8000 \
    -p 6080:6080 \
    -v court_session:/data/court_session \
    -e PORT=8000 \
    -e SCRAPER_DEBUG=0 \
    -e PROXY_PORT="${PROXY_PORT:-12321}" \
    -e SCRAPER_DB_URL="$SCRAPER_DB_URL" \
    "$IMAGE"

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
log "Waiting for health check ..."
for i in $(seq 1 20); do
    if curl -sf http://127.0.0.1:8001/health >/dev/null 2>&1; then
        ok "scraper-staging is up at http://127.0.0.1:8001"
        ok "noVNC (CAPTCHA) at http://127.0.0.1:6080"
        exit 0
    fi
    sleep 2
done

warn "Health check timed out. Check logs:"
docker logs "$CONTAINER" --tail 40
exit 1
