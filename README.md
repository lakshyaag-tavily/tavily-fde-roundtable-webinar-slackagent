# Roundtable Webinar Slack Agent

A deliberately small Slack Q&A bot for demonstrating the complete path from a
Slack app manifest and public tunnel to a LangChain Deep Agent with web access.
The agent has exactly two external tools: Tavily search and Tavily extract.

## Architecture

```text
Slack DM or @mention
        │  Events API
        ▼
FastAPI + Slack Bolt  ── immediate ack
        │
        ▼
LangChain Deep Agent (in-process LangGraph + in-memory thread history)
        │
        ├── Tavily search
        └── Tavily extract
        │
        ├── live tool events ──► updated Slack "Web research" activity
        └── final answer ──────► Slack thread reply
```

There is no UI, product database, worker, webhook callback service, HubSpot,
Confluence, Grain, or skills layer. Model preferences, thread/model bindings,
conversation checkpoints, and event deduplication are intentionally in memory
and reset when the process restarts.

## 1. Configure

```bash
cd fde-roundtable-webinar-slackagent/backend
cp .env.example .env
# Fill in LANGSMITH_API_KEY and TAVILY_API_KEY first.
uv sync
```

Model calls use the LangSmith LLM Gateway. The demo exposes two model aliases:

- `gpt` → `openai/gpt-5.6-sol` (default)
- `opus` → `anthropic/claude-opus-5`

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

Copy the generated HTTPS URL into both `url` fields in
[`slack-app-manifest.json`](slack-app-manifest.json):

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

The manifest includes `/agent-model`:

```text
/agent-model list
/agent-model gpt
/agent-model opus
/agent-model status
```

A model choice applies to new threads. Existing threads remain bound to the
model they started with.

## Suggested webinar prompt

```text
What changed in LangGraph recently? Use official sources and explain the three
updates most relevant to teams building production research agents.
```

While Tavily runs, Slack shows live search/extract activity and source links.
The final response lands in the same Slack thread.
