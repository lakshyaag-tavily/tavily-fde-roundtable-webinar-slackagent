"""In-memory model defaults and per-thread binding for the demo."""

from __future__ import annotations

from roundtable_agent.models import DEFAULT_MODEL, resolve_model

_user_models: dict[str, str] = {}
_thread_models: dict[str, str] = {}


def preferred_model(user_id: str) -> str:
    return _user_models.get(user_id, DEFAULT_MODEL)


def set_preferred_model(user_id: str, value: str) -> str:
    model_id = resolve_model(value)
    if not model_id:
        raise ValueError(f"unknown model: {value}")
    _user_models[user_id] = model_id
    return model_id


def model_for_thread(*, user_id: str, thread_key: str) -> str:
    return _thread_models.setdefault(thread_key, preferred_model(user_id))
