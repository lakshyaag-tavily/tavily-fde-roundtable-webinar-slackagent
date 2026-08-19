# Backend

One Python process contains the FastAPI/Slack Bolt edge and the Deep Agent.

```text
roundtable_agent/
  api.py                 Slack events, App Home, /agent-model
  agents/research.py     create_deep_agent + Tavily search/extract
  model_selection.py     in-memory user defaults and thread binding
  services/agent_turns.py
                         in-process graph execution + tool event streaming
  services/slack.py      Slack status, tool updates, and final replies
  slack/                 event filters, model command, and formatting helpers
```

Run with `uv run roundtable-agent serve --reload`.
