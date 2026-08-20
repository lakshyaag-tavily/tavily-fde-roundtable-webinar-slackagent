from __future__ import annotations

import os

import typer

app = typer.Typer(help="Tavily Scout Slack agent")


@app.callback()
def main() -> None:
    """Run the Tavily Scout Slack agent."""


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host."),
    port: int = typer.Option(8000, help="Bind port."),
    reload: bool = typer.Option(False, "--reload", help="Enable uvicorn reload."),
) -> None:
    import uvicorn

    from tavily_scout.logging_config import configure_app_logging

    configure_app_logging()
    uvicorn.run(
        "tavily_scout.api:app",
        host=host,
        port=port,
        reload=reload,
        log_level=os.environ.get("TAVILY_SCOUT_LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    app()
