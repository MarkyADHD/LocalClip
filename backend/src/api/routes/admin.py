from __future__ import annotations

import asyncio
from datetime import datetime
from urllib.parse import urlsplit

import httpx

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...admin_auth import require_admin_user
from ...ai import _get_missing_llm_key_error
from ...config import Config, get_config
from ...database import get_db
from ...runtime_settings import (
    RUNTIME_SETTING_KEYS,
    encrypt_setting_value,
    get_runtime_setting_rows,
    load_runtime_settings_cache,
)

router = APIRouter(prefix="/admin", tags=["admin"])


SETTING_METADATA = {
    "ASSEMBLY_AI_API_KEY": {
        "label": "AssemblyAI API key",
        "description": "Used for video transcription.",
        "input_type": "password",
    },
    "LLM": {
        "label": "LLM model",
        "description": "Provider and model, for example openai:gpt-5.2.",
        "input_type": "text",
    },
    "OPENAI_API_KEY": {
        "label": "OpenAI API key",
        "description": "Required for openai:* models.",
        "input_type": "password",
    },
    "OPENROUTER_API_KEY": {
        "label": "OpenRouter API key",
        "description": "Required for openrouter:* models, including Sonnet with Luna fallback.",
        "input_type": "password",
    },
    "GOOGLE_API_KEY": {
        "label": "Google API key",
        "description": "Required for google-gla:* models and fallback YouTube metadata.",
        "input_type": "password",
    },
    "ANTHROPIC_API_KEY": {
        "label": "Anthropic API key",
        "description": "Required for anthropic:* models.",
        "input_type": "password",
    },
    "OLLAMA_BASE_URL": {
        "label": "Local AI server URL",
        "description": "OpenAI-compatible URL used by ollama:* and local:* models (Ollama, LM Studio, llama.cpp, ...).",
        "input_type": "text",
    },
    "OLLAMA_API_KEY": {
        "label": "Ollama API key",
        "description": "Optional, used by hosted Ollama-compatible providers.",
        "input_type": "password",
    },
    "YOUTUBE_DATA_API_KEY": {
        "label": "YouTube Data API key",
        "description": "Optional metadata provider key.",
        "input_type": "password",
    },
    "APIFY_API_TOKEN": {
        "label": "Apify API token",
        "description": "Optional YouTube download fallback provider token.",
        "input_type": "password",
    },
    "PEXELS_API_KEY": {
        "label": "Pexels API key",
        "description": "Optional B-roll stock footage provider key.",
        "input_type": "password",
    },
}


# Common local AI apps and the port their OpenAI-compatible server uses by default.
LOCAL_AI_SERVERS = (
    ("Ollama", 11434),
    ("LM Studio", 1234),
    ("Jan", 1337),
    ("llama.cpp / LocalAI", 8080),
    ("KoboldCpp", 5001),
    ("text-generation-webui", 5000),
    ("GPT4All", 4891),
)


async def _list_server_models(client: httpx.AsyncClient, name: str, base_url: str):
    try:
        response = await client.get(f"{base_url}/models")
        response.raise_for_status()
        models = sorted({str(m["id"]) for m in response.json().get("data", []) if m.get("id")})
    except Exception:
        return None
    return {"name": name, "base_url": base_url, "models": models} if models else None


async def discover_local_models(configured_base_url: str) -> list[dict]:
    host = urlsplit(Config._default_ollama_base_url()).hostname
    servers = {f"http://{host}:{port}/v1": name for name, port in LOCAL_AI_SERVERS}
    configured = configured_base_url.rstrip("/")
    servers.setdefault(configured, "Configured server")
    async with httpx.AsyncClient(timeout=2.0) as client:
        found = await asyncio.gather(
            *(_list_server_models(client, name, url) for url, name in servers.items())
        )
    return [server for server in found if server]


class RuntimeSettingsUpdate(BaseModel):
    updates: dict[str, str] = Field(default_factory=dict)
    delete_keys: list[str] = Field(default_factory=list)
    prefer_admin_values: dict[str, bool] = Field(default_factory=dict)


def _setting_status(
    setting_key: str, rows: dict[str, dict[str, object]]
):
    env_value = get_config()._get_optional_env(setting_key)
    has_env = bool(env_value)
    row = rows.get(setting_key, {})
    has_admin_value = bool(row.get("encrypted_value"))
    prefer_admin_value = bool(row.get("prefer_admin_value"))
    metadata = SETTING_METADATA[setting_key]

    if has_admin_value and (prefer_admin_value or not has_env):
        source = "admin"
    elif has_env:
        source = "environment"
    else:
        source = "unset"

    return {
        "key": setting_key,
        "label": metadata["label"],
        "description": metadata["description"],
        "input_type": metadata["input_type"],
        "source": source,
        "configured": has_env or has_admin_value,
        "has_admin_value": has_admin_value,
        "has_env_value": has_env,
        "prefer_admin_value": prefer_admin_value,
        "overridden_by_env": has_env and has_admin_value and not prefer_admin_value,
        "updated_at": row.get("updated_at"),
    }


@router.get("/health")
async def admin_health(
    request: Request, db: AsyncSession = Depends(get_db)
):
    await require_admin_user(request, db, get_config())
    return {"status": "ok"}


@router.get("/local-models")
async def get_local_models(request: Request, db: AsyncSession = Depends(get_db)):
    """The selected LLM plus every model the local AI servers on this PC report."""
    config = get_config()
    await require_admin_user(request, db, config)
    base_url = config.resolve_ollama_base_url()
    return {
        "llm": config.llm,
        "base_url": base_url,
        "servers": await discover_local_models(base_url),
    }


@router.get("/runtime-settings")
async def get_runtime_settings(request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin_user(request, db, get_config())
    rows = await get_runtime_setting_rows(db)
    return {
        "settings": [
            _setting_status(setting_key, rows) for setting_key in RUNTIME_SETTING_KEYS
        ]
    }


@router.patch("/runtime-settings")
async def update_runtime_settings(
    request: Request,
    payload: RuntimeSettingsUpdate,
    db: AsyncSession = Depends(get_db),
):
    user_id = await require_admin_user(request, db, get_config())
    allowed_keys = set(RUNTIME_SETTING_KEYS)
    invalid_keys = [
        key
        for key in [
            *payload.updates.keys(),
            *payload.delete_keys,
            *payload.prefer_admin_values.keys(),
        ]
        if key not in allowed_keys
    ]
    if invalid_keys:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported setting key(s): {', '.join(sorted(set(invalid_keys)))}",
        )

    if "LLM" in payload.updates:
        config_error = _get_missing_llm_key_error(
            payload.updates["LLM"].strip(), get_config()
        )
        if config_error and "API_KEY is not set" not in config_error:
            raise HTTPException(status_code=400, detail=config_error)

    for setting_key, raw_value in payload.updates.items():
        value = raw_value.strip()
        if not value:
            continue
        encrypted_value = encrypt_setting_value(value)
        await db.execute(
            text(
                """
                INSERT INTO app_settings (setting_key, encrypted_value, updated_by)
                VALUES (:setting_key, :encrypted_value, :updated_by)
                ON CONFLICT (setting_key) DO UPDATE
                SET encrypted_value = EXCLUDED.encrypted_value,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = CURRENT_TIMESTAMP
                """
            ),
            {
                "setting_key": setting_key,
                "encrypted_value": encrypted_value,
                "updated_by": user_id,
            },
        )

    for setting_key, prefer_admin_value in payload.prefer_admin_values.items():
        await db.execute(
            text(
                """
                UPDATE app_settings
                SET prefer_admin_value = :prefer_admin_value,
                    updated_by = :updated_by,
                    updated_at = CURRENT_TIMESTAMP
                WHERE setting_key = :setting_key
                """
            ),
            {
                "setting_key": setting_key,
                "prefer_admin_value": prefer_admin_value,
                "updated_by": user_id,
            },
        )

    if payload.delete_keys:
        await db.execute(
            text(
                """
                DELETE FROM app_settings
                WHERE setting_key = ANY(CAST(:setting_keys AS text[]))
                """
            ),
            {"setting_keys": payload.delete_keys},
        )

    await db.commit()
    await load_runtime_settings_cache(db)

    rows = await get_runtime_setting_rows(db)
    return {
        "settings": [
            _setting_status(setting_key, rows) for setting_key in RUNTIME_SETTING_KEYS
        ]
    }
