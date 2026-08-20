from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp
from slack_sdk.errors import SlackApiError

from tavily_scout.config import Settings, get_settings
from tavily_scout.logging_config import configure_app_logging
from tavily_scout.model_selection import set_preferred_model
from tavily_scout.models import SLASH_COMMAND
from tavily_scout.services.agent_turns import handle_slack_message
from tavily_scout.slack.events import (
    event_thread_ts,
    is_channel_or_group_message,
    research_text_from_event,
    should_ignore_app_mention_event,
    should_ignore_message_event,
)
from tavily_scout.slack.home import (
    SELECT_MODEL_ACTION_ID,
    SUGGESTED_PROMPTS,
    SUGGESTED_PROMPTS_TITLE,
    build_home_view,
)
from tavily_scout.slack.model_command import slash_result_from_command

logger = logging.getLogger(__name__)


async def _resolve_bot_identity(
    client: Any, settings: Settings
) -> tuple[str | None, str | None]:
    if settings.slack_bot_user_id and settings.slack_bot_id:
        return settings.slack_bot_user_id, settings.slack_bot_id
    try:
        auth = await client.auth_test()
    except Exception:
        logger.exception("auth.test failed; Slack bot identity may be incomplete")
        return settings.slack_bot_user_id, settings.slack_bot_id
    return (
        str(auth.get("user_id") or "") or settings.slack_bot_user_id,
        str(auth.get("bot_id") or "") or settings.slack_bot_id,
    )


def _build_bolt_app(settings: Settings) -> AsyncApp:
    if not settings.slack_bot_token or not settings.slack_signing_secret:
        raise RuntimeError(
            "TAVILY_SCOUT_SLACK_BOT_TOKEN and "
            "TAVILY_SCOUT_SLACK_SIGNING_SECRET are required"
        )

    bolt = AsyncApp(
        token=settings.slack_bot_token,
        signing_secret=settings.slack_signing_secret,
        logger=logger,
    )
    identity = {
        "bot_user_id": settings.slack_bot_user_id,
        "bot_id": settings.slack_bot_id,
    }

    async def just_ack(ack) -> None:  # type: ignore[no-untyped-def]
        await ack()

    async def handle_message(
        event: dict[str, Any],
        body: dict[str, Any],
        client: Any,
    ) -> None:
        if not identity["bot_user_id"] or not identity["bot_id"]:
            identity["bot_user_id"], identity["bot_id"] = await _resolve_bot_identity(
                client, settings
            )

        event_dict: dict[str, Any] = dict(event)
        event_type = str(event_dict.get("type") or "message")
        if event_type == "message":
            if is_channel_or_group_message(event_dict):
                return
            if should_ignore_message_event(
                event_dict, bot_user_id=identity["bot_user_id"]
            ):
                return
        elif event_type == "app_mention":
            if should_ignore_app_mention_event(
                event_dict, bot_user_id=identity["bot_user_id"]
            ):
                return
        else:
            return

        event_id = str(body.get("event_id") or "")
        channel = str(event_dict.get("channel") or "")
        user_id = str(event_dict.get("user") or "")
        text = research_text_from_event(
            event_dict,
            event_type=event_type,
            bot_user_id=identity["bot_user_id"],
        )
        thread_ts = event_thread_ts(event_dict)
        if not event_id or not channel or not user_id or not text or not thread_ts:
            return

        await handle_slack_message(
            event_id=event_id,
            channel=channel,
            user_id=user_id,
            text=text,
            thread_ts=thread_ts,
            settings=settings,
        )

    async def _publish_home(client: Any, user_id: str) -> None:
        await client.views_publish(
            user_id=user_id,
            view=build_home_view(user_id=user_id),
        )

    async def _set_suggested_prompts(client: Any, channel_id: str) -> None:
        # Agent View still requires thread_ts in practice; omitting it returns
        # internal_error. Use the latest DM message when one exists.
        try:
            history = await client.conversations_history(channel=channel_id, limit=1)
        except SlackApiError as exc:
            logger.warning(
                "Could not load DM history for suggested prompts: %s",
                exc.response.get("error"),
            )
            return
        messages = history.get("messages") or []
        if not messages:
            return
        thread_ts = str(messages[0].get("thread_ts") or messages[0].get("ts") or "")
        if not thread_ts:
            return
        try:
            await client.assistant_threads_setSuggestedPrompts(
                channel_id=channel_id,
                thread_ts=thread_ts,
                title=SUGGESTED_PROMPTS_TITLE,
                prompts=SUGGESTED_PROMPTS,
            )
        except SlackApiError as exc:
            logger.warning(
                "Could not set dynamic suggested prompts: %s",
                exc.response.get("error"),
            )

    async def handle_app_home_opened(event: dict[str, Any], client: Any, ack) -> None:  # type: ignore[no-untyped-def]
        await ack()
        tab = str(event.get("tab") or "home")
        try:
            if tab == "messages":
                channel_id = str(event.get("channel") or "")
                if channel_id:
                    await _set_suggested_prompts(client, channel_id)
                return
            user_id = str(event.get("user") or "")
            if user_id:
                await _publish_home(client, user_id)
        except Exception:
            logger.exception("Failed handling app_home_opened tab=%s", tab)

    async def handle_select_model(ack, body: dict[str, Any], client: Any) -> None:  # type: ignore[no-untyped-def]
        await ack()
        user_id = str((body.get("user") or {}).get("id") or "")
        action = (body.get("actions") or [{}])[0]
        alias = str(
            ((action.get("selected_option") or {}).get("value"))
            or action.get("value")
            or ""
        )
        if not user_id or not alias:
            return
        try:
            set_preferred_model(user_id, alias)
            await _publish_home(client, user_id)
        except Exception:
            logger.exception("Failed to set Home tab model alias=%s", alias)

    async def handle_model_command(command: dict[str, Any], respond, client) -> None:  # type: ignore[no-untyped-def]
        try:
            text = slash_result_from_command(command, settings=settings)
        except Exception:
            logger.exception("Failed %s", SLASH_COMMAND)
            text = "Could not update your default model. Try again?"
        await respond({"text": text, "response_type": "ephemeral"})
        user_id = str(command.get("user_id") or "")
        if user_id:
            try:
                await _publish_home(client, user_id)
            except Exception:
                logger.exception("Failed to refresh Home after %s", SLASH_COMMAND)

    bolt.event("message")(ack=just_ack, lazy=[handle_message])
    bolt.event("app_mention")(ack=just_ack, lazy=[handle_message])
    bolt.event("app_home_opened")(handle_app_home_opened)
    bolt.event("app_context_changed")(just_ack)
    bolt.action(SELECT_MODEL_ACTION_ID)(handle_select_model)
    bolt.command(SLASH_COMMAND)(ack=just_ack, lazy=[handle_model_command])
    return bolt


def create_app(settings: Settings | None = None) -> FastAPI:
    configure_app_logging()
    app_settings = settings or get_settings()
    app = FastAPI(title=app_settings.app_name)
    try:
        bolt_handler: AsyncSlackRequestHandler | None = AsyncSlackRequestHandler(
            _build_bolt_app(app_settings)
        )
    except RuntimeError:
        bolt_handler = None
        logger.warning("Slack Bolt is not configured; /events/slack will return 500")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "app": app_settings.app_name,
            "runtime": "in-process LangGraph",
        }

    @app.post("/events/slack")
    async def slack_events(request: Request):
        # Let Slack verify a fresh manifest before credentials have been copied
        # into .env. All non-challenge traffic still goes through Bolt signing.
        payload = None
        if "application/json" in request.headers.get("content-type", ""):
            payload = await request.json()
        if isinstance(payload, dict) and payload.get("type") == "url_verification":
            challenge = payload.get("challenge")
            if isinstance(challenge, str):
                return JSONResponse({"challenge": challenge})
        if bolt_handler is None:
            raise HTTPException(status_code=500, detail="Slack not configured")
        return await bolt_handler.handle(request)

    return app


app = create_app()
