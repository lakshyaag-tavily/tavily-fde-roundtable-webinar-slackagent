#!/usr/bin/env bash
# Tavily Scout — Cloudflare quick tunnel for local Slack Events API testing.
# Mirrors AI-FDE's setup_ngrok.sh, using cloudflared instead of ngrok.

set -euo pipefail

PORT="${PORT:-8000}"
HEALTH_URL="http://127.0.0.1:${PORT}/health"
TUNNEL_TARGET="http://127.0.0.1:${PORT}"

echo "Tavily Scout — Cloudflare tunnel for Slack testing"
echo "==============================================="

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared is not installed."
  echo ""
  echo "Install:"
  echo "  Mac:  brew install cloudflared"
  echo "  Docs: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/"
  echo ""
  echo "After installing, run this script again."
  exit 1
fi

echo "OK: cloudflared $(cloudflared --version 2>&1 | head -1)"

if ! curl -sf "$HEALTH_URL" >/dev/null; then
  echo ""
  echo "API is not healthy at ${HEALTH_URL}"
  echo "Start the stack first:"
  echo "  docker compose up --build"
  echo "  # or host API: cd backend && uv run tavily-scout serve --reload"
  echo ""
  echo "After the API is up, run this script again."
  exit 1
fi

echo "OK: API healthy at ${HEALTH_URL}"
echo ""
echo "Starting Cloudflare quick tunnel → ${TUNNEL_TARGET}"
echo "=================================================="
echo ""
echo "Once the tunnel starts:"
echo "  1. Copy the HTTPS URL (https://….trycloudflare.com)"
echo "  2. Slack App → Event Subscriptions → Request URL:"
echo "       https://YOUR-TUNNEL-URL/events/slack"
echo "  3. Slack should verify (url_verification → challenge echo)."
echo "  4. Ensure bot event message.im is subscribed; Messages Tab on."
echo "  5. DM the bot: What changed in LangGraph recently?"
echo ""
echo "Note: quick-tunnel URLs change every restart — update Slack when they do."
echo "Press Ctrl+C to stop the tunnel."
echo ""

exec cloudflared tunnel --url "$TUNNEL_TARGET"
