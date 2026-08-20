# Tavily Scout

A research Slack agent backed by a LangChain Deep Agent. It has two tools: Tavily search and Tavily extract.

```text
Slack DM or @mention
        │  Events API
        ▼
FastAPI + Slack Bolt
        │
        ▼
LangChain Deep Agent
        ├── Tavily search
        └── Tavily extract
        │
        ├── live tool events ──► Slack plan/task cards
        └── final answer ──────► Slack thread reply
```

Model preferences, thread history, and event deduplication are stored in memory and reset when the process restarts.

## 1. Configure

```bash
cd backend
cp .env.example .env
# Fill in OPENAI_API_KEY, NEBIUS_API_KEY, and TAVILY_API_KEY first.
uv sync
```

Model aliases:

- `gpt` → `openai/gpt-5.6-sol` (default)
- `kimi` → `nebius:moonshoot/Kimi-K3`
- `nemotron` → `nebius:nvidia/Nemotron-3_5-Lightning`

## 2. Run locally

```bash
cd backend
uv run roundtable-agent serve --reload
```

Check <http://127.0.0.1:8000/health>.

Docker is optional:

```bash
docker compose up --build
```

## 3. Start a tunnel

From the repository root, with the agent already listening on port 8000:

```bash
./scripts/setup_cloudflare.sh
```

Copy the generated HTTPS URL into both `url` fields in [`slack-app-manifest.json`](slack-app-manifest.json):

```text
https://YOUR-TUNNEL.trycloudflare.com/events/slack
```

## 4. Create the Slack app

1. Go to <https://api.slack.com/apps> → **Create New App** → **From a manifest**.
2. Paste `slack-app-manifest.json` and replace the tunnel placeholder.
3. Install the app to the workspace.
4. Copy the **Bot User OAuth Token** and **Signing Secret** into `backend/.env`.
5. Restart the agent.
6. DM the bot or mention it in a channel.

Switch models with `/agent-model`:

```text
/agent-model list
/agent-model gpt
/agent-model kimi
/agent-model nemotron
/agent-model status
```

A model choice applies to new threads. Existing threads stay on the model they started with.

While Tavily runs, Slack shows live search/extract activity and source links. The final response lands in the same thread.
