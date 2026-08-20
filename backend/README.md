# Backend

One Python process contains the FastAPI/Slack Bolt edge and the Deep Agent.

```text
tavily_scout/
  api.py                 Slack events, App Home, /agent-model
  agents/research.py     create_deep_agent + Tavily search/extract
  model_selection.py     in-memory user defaults and thread binding
  services/agent_turns.py
                         in-process graph execution + tool event streaming
  services/slack.py      Slack status, plan/task-card updates, final replies
  slack/                 event filters, model command, rich tool-stream helpers
```

Run with `uv run tavily-scout serve --reload`.
