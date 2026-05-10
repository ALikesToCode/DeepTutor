"""
Settings API Router
===================

UI preferences, configuration catalog management, and detailed streamed tests.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.model_access import allowed_llm_options, redacted_model_access
from deeptutor.services.config import get_config_test_runner, get_model_catalog_service
from deeptutor.services.embedding.client import reset_embedding_client
from deeptutor.services.llm.client import reset_llm_client
from deeptutor.services.llm.config import clear_llm_config_cache
from deeptutor.services.model_selection import list_llm_options
from deeptutor.services.path_service import get_path_service

router = APIRouter()

TOUR_CACHE = None


def _settings_file():
    return get_path_service().get_settings_file("interface")


def _tour_cache_file():
    if TOUR_CACHE is not None:
        return TOUR_CACHE
    return get_path_service().get_settings_dir() / ".tour_cache.json"


DEFAULT_SIDEBAR_NAV_ORDER = {
    "start": ["/", "/history", "/knowledge", "/notebook"],
    "learnResearch": ["/question", "/solver", "/research", "/co_writer"],
}

DEFAULT_UI_SETTINGS = {
    "theme": "light",
    "language": "en",
    "sidebar_description": "✨ Data Intelligence Lab @ HKU",
    "sidebar_nav_order": DEFAULT_SIDEBAR_NAV_ORDER,
}


class SidebarNavOrder(BaseModel):
    start: List[str]
    learnResearch: List[str]


class UISettings(BaseModel):
    theme: Literal["light", "dark", "glass", "snow"] = "light"
    language: Literal["zh", "en"] = "en"
    sidebar_description: Optional[str] = None
    sidebar_nav_order: Optional[SidebarNavOrder] = None


class ThemeUpdate(BaseModel):
    theme: Literal["light", "dark", "glass", "snow"]


class LanguageUpdate(BaseModel):
    language: Literal["zh", "en"]


class SidebarDescriptionUpdate(BaseModel):
    description: str


class SidebarNavOrderUpdate(BaseModel):
    nav_order: SidebarNavOrder


class CatalogPayload(BaseModel):
    catalog: dict[str, Any]


class ModelListPayload(BaseModel):
    catalog: dict[str, Any] | None = None


def _invalidate_runtime_caches() -> None:
    """Force runtime clients/config to pick up the latest saved catalog.

    The LLM and embedding clients are process-wide singletons, so resetting
    them here will affect any user turn that is mid-flight on another worker.
    Admins issuing Apply during active sessions accept that trade-off; we log
    a WARNING so the cause is visible in the audit trail.
    """
    logger.warning(
        "Admin applied catalog; resetting global LLM/embedding clients. "
        "In-flight user turns may flip backend client mid-call."
    )
    clear_llm_config_cache()
    reset_llm_client()
    reset_embedding_client()


def load_ui_settings() -> dict[str, Any]:
    settings_file = _settings_file()
    if settings_file.exists():
        try:
            with open(settings_file, encoding="utf-8") as handle:
                saved = json.load(handle)
                return {**DEFAULT_UI_SETTINGS, **saved}
        except Exception:
            pass
    return DEFAULT_UI_SETTINGS.copy()


def save_ui_settings(settings: dict[str, Any]) -> None:
    settings_file = _settings_file()
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_file, "w", encoding="utf-8") as handle:
        json.dump(settings, handle, ensure_ascii=False, indent=2)


def _require_settings_admin() -> None:
    if not get_current_user().is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Model configuration is managed by an administrator.",
        )


def _provider_choices() -> dict[str, list[dict[str, str]]]:
    """Build dropdown options for provider selection, keyed by service type."""
    from deeptutor.services.config.provider_runtime import EMBEDDING_PROVIDERS
    from deeptutor.services.provider_registry import PROVIDERS

    llm = sorted(
        [
            {
                "value": s.name,
                "label": (
                    "Custom (OpenAI API)"
                    if s.name == "custom"
                    else "Custom (Anthropic API)"
                    if s.name == "custom_anthropic"
                    else s.label
                ),
                "base_url": s.default_api_base,
            }
            for s in PROVIDERS
        ],
        key=lambda p: p["label"].lower(),
    )
    embedding = sorted(
        [
            {
                "value": name,
                "label": spec.label,
                "base_url": spec.default_api_base,
                "default_dim": str(spec.default_dim) if spec.default_dim else "",
            }
            for name, spec in EMBEDDING_PROVIDERS.items()
            if name != "custom_openai_sdk"
        ],
        key=lambda p: p["label"].lower(),
    )
    search = [
        {"value": "brave", "label": "Brave", "base_url": ""},
        {"value": "tavily", "label": "Tavily", "base_url": ""},
        {"value": "jina", "label": "Jina", "base_url": ""},
        {"value": "searxng", "label": "SearXNG", "base_url": ""},
        {"value": "duckduckgo", "label": "DuckDuckGo", "base_url": ""},
        {"value": "perplexity", "label": "Perplexity", "base_url": ""},
    ]
    return {"llm": llm, "embedding": embedding, "search": search}


def _active_profile(catalog: dict[str, Any], service_name: str) -> dict[str, Any] | None:
    service = catalog.get("services", {}).get(service_name, {})
    active_id = service.get("active_profile_id")
    profiles = service.get("profiles", [])
    if not isinstance(profiles, list):
        return None
    for profile in profiles:
        if isinstance(profile, dict) and profile.get("id") == active_id:
            return profile
    first = profiles[0] if profiles else None
    return first if isinstance(first, dict) else None


def _profile_model_api_key(service_name: str, profile: dict[str, Any]) -> str:
    explicit = str(profile.get("api_key") or "").strip()
    if explicit:
        return explicit

    from deeptutor.services.config.env_store import get_env_store

    env_store = get_env_store()
    if service_name == "llm":
        from deeptutor.services.provider_registry import find_by_name

        spec = find_by_name(str(profile.get("binding") or ""))
        env_key = spec.env_key if spec else ""
        return env_store.get(env_key, "").strip() if env_key else ""

    from deeptutor.services.config.provider_runtime import EMBEDDING_PROVIDERS

    spec = EMBEDDING_PROVIDERS.get(str(profile.get("binding") or "").strip().lower())
    if not spec:
        return ""
    for env_key in spec.api_key_envs:
        value = env_store.get(env_key, "").strip()
        if value:
            return value
    return ""


def _model_endpoint_matches(service_name: str, endpoint: str) -> bool:
    if not endpoint:
        return True
    if service_name == "embedding":
        return endpoint.rstrip("/") == "/v1/embeddings"
    return endpoint.rstrip("/") in {"/v1/chat/completions", "/v1/responses"}


def _normalize_model_items(service_name: str, items: list[Any]) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            model_id = item.strip()
            endpoint = ""
            owned_by = ""
            premium = False
        elif isinstance(item, dict):
            model_id = str(item.get("id") or item.get("model") or item.get("name") or "").strip()
            endpoint = str(item.get("endpoint") or "").strip()
            owned_by = str(item.get("owned_by") or "").strip()
            premium = bool(item.get("premium", False))
        else:
            continue

        if not model_id or model_id in seen:
            continue
        if not _model_endpoint_matches(service_name, endpoint):
            continue
        seen.add(model_id)
        label_parts = [model_id]
        if owned_by:
            label_parts.append(owned_by)
        if premium:
            label_parts.append("premium")
        models.append(
            {
                "id": model_id,
                "label": " · ".join(label_parts),
                "endpoint": endpoint,
                "owned_by": owned_by,
                "premium": premium,
            }
        )
    return sorted(models, key=lambda model: model["id"].lower())


async def _fetch_provider_models(
    *,
    service_name: str,
    binding: str,
    base_url: str,
    api_key: str,
) -> list[dict[str, Any]]:
    from deeptutor.services.llm.cloud_provider import _get_aiohttp_connector
    from deeptutor.services.llm.utils import build_auth_headers
    import aiohttp

    url = f"{base_url.rstrip('/')}/models"
    headers = build_auth_headers(api_key or None, binding or "openai")
    headers.pop("Content-Type", None)
    timeout = aiohttp.ClientTimeout(total=30)
    connector = _get_aiohttp_connector()
    async with aiohttp.ClientSession(
        timeout=timeout, connector=connector, trust_env=True
    ) as session:
        async with session.get(url, headers=headers) as response:
            response.raise_for_status()
            payload = await response.json()

    if isinstance(payload, dict):
        raw_items = payload.get("data") or payload.get("models") or payload.get("items") or []
    elif isinstance(payload, list):
        raw_items = payload
    else:
        raw_items = []
    return _normalize_model_items(service_name, raw_items if isinstance(raw_items, list) else [])


@router.get("")
async def get_settings():
    user = get_current_user()
    if not user.is_admin:
        return {
            "ui": load_ui_settings(),
            "model_access": redacted_model_access(user.id),
        }
    return {
        "ui": load_ui_settings(),
        "catalog": get_model_catalog_service().load(),
        "providers": _provider_choices(),
    }


@router.get("/catalog")
async def get_catalog():
    _require_settings_admin()
    return {"catalog": get_model_catalog_service().load()}


@router.post("/models/{service_name}")
async def list_provider_models(
    service_name: Literal["llm", "embedding"],
    payload: ModelListPayload | None = None,
):
    catalog = payload.catalog if payload and payload.catalog else get_model_catalog_service().load()
    profile = _active_profile(catalog, service_name)
    if not profile:
        return {"models": [], "source": "catalog", "message": "No active profile configured."}

    binding = str(profile.get("binding") or "openai").strip() or "openai"
    base_url = str(profile.get("base_url") or "").strip()
    api_key = _profile_model_api_key(service_name, profile)
    if not base_url:
        return {"models": [], "source": "catalog", "message": "No base URL configured."}

    models = await _fetch_provider_models(
        service_name=service_name,
        binding=binding,
        base_url=base_url,
        api_key=api_key,
    )
    return {"models": models, "source": f"{base_url.rstrip('/')}/models"}


@router.get("/llm-options")
async def get_llm_options():
    if not get_current_user().is_admin:
        return allowed_llm_options()
    return list_llm_options(get_model_catalog_service().load())


@router.put("/catalog")
async def update_catalog(payload: CatalogPayload):
    _require_settings_admin()
    catalog = get_model_catalog_service().save(payload.catalog)
    _invalidate_runtime_caches()
    return {"catalog": catalog}


@router.post("/apply")
async def apply_catalog(payload: CatalogPayload | None = None):
    _require_settings_admin()
    catalog = payload.catalog if payload is not None else get_model_catalog_service().load()
    rendered = get_model_catalog_service().apply(catalog)
    _invalidate_runtime_caches()
    return {
        "message": "Catalog applied to the active .env configuration.",
        "catalog": get_model_catalog_service().load(),
        "env": rendered,
    }


@router.put("/theme")
async def update_theme(update: ThemeUpdate):
    current_ui = load_ui_settings()
    current_ui["theme"] = update.theme
    save_ui_settings(current_ui)
    return {"theme": update.theme}


@router.put("/language")
async def update_language(update: LanguageUpdate):
    current_ui = load_ui_settings()
    current_ui["language"] = update.language
    save_ui_settings(current_ui)
    return {"language": update.language}


@router.put("/ui")
async def update_ui_settings(update: UISettings):
    current_ui = load_ui_settings()
    current_ui.update(update.model_dump(exclude_none=True))
    save_ui_settings(current_ui)
    return current_ui


@router.post("/reset")
async def reset_settings():
    save_ui_settings(DEFAULT_UI_SETTINGS)
    return DEFAULT_UI_SETTINGS


@router.get("/themes")
async def get_themes():
    return {
        "themes": [
            {"id": "snow", "name": "Snow"},
            {"id": "light", "name": "Light"},
            {"id": "dark", "name": "Dark"},
            {"id": "glass", "name": "Glass"},
        ]
    }


@router.get("/sidebar")
async def get_sidebar_settings():
    current_ui = load_ui_settings()
    return {
        "description": current_ui.get(
            "sidebar_description", DEFAULT_UI_SETTINGS["sidebar_description"]
        ),
        "nav_order": current_ui.get("sidebar_nav_order", DEFAULT_UI_SETTINGS["sidebar_nav_order"]),
    }


@router.put("/sidebar/description")
async def update_sidebar_description(update: SidebarDescriptionUpdate):
    current_ui = load_ui_settings()
    current_ui["sidebar_description"] = update.description
    save_ui_settings(current_ui)
    return {"description": update.description}


@router.put("/sidebar/nav-order")
async def update_sidebar_nav_order(update: SidebarNavOrderUpdate):
    current_ui = load_ui_settings()
    current_ui["sidebar_nav_order"] = update.nav_order.model_dump()
    save_ui_settings(current_ui)
    return {"nav_order": update.nav_order.model_dump()}


@router.post("/tests/{service}/start")
async def start_service_test(service: str, payload: CatalogPayload | None = None):
    _require_settings_admin()
    run = get_config_test_runner().start(service, payload.catalog if payload else None)
    return {"run_id": run.id}


@router.get("/tests/{service}/{run_id}/events")
async def stream_service_test_events(service: str, run_id: str, request: Request):
    _require_settings_admin()
    runner = get_config_test_runner()
    run = runner.get(run_id)

    async def event_stream():
        sent = 0
        while True:
            if await request.is_disconnected():
                return
            events = run.snapshot(sent)
            if events:
                for event in events:
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                sent += len(events)
                if events[-1]["type"] in {"completed", "failed"}:
                    return
            else:
                yield "event: heartbeat\ndata: {}\n\n"
            await asyncio.sleep(0.35)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/tests/{service}/{run_id}/cancel")
async def cancel_service_test(service: str, run_id: str):
    _require_settings_admin()
    get_config_test_runner().cancel(run_id)
    return {"message": "Cancelled"}


@router.get("/tour/status")
async def tour_status():
    tour_cache = _tour_cache_file()
    if tour_cache.exists():
        try:
            cache = json.loads(tour_cache.read_text(encoding="utf-8"))
            return {
                "active": True,
                "status": cache.get("status", "unknown"),
                "launch_at": cache.get("launch_at"),
                "redirect_at": cache.get("redirect_at"),
            }
        except Exception:
            pass
    return {"active": False, "status": "none", "launch_at": None, "redirect_at": None}


class TourCompletePayload(BaseModel):
    catalog: dict[str, Any] | None = None
    test_results: dict[str, str] | None = None


@router.post("/tour/complete")
async def complete_tour(payload: TourCompletePayload | None = None):
    _require_settings_admin()
    catalog = payload.catalog if payload and payload.catalog else get_model_catalog_service().load()
    rendered = get_model_catalog_service().apply(catalog)
    _invalidate_runtime_caches()
    now = int(time.time())
    launch_at = now + 3
    redirect_at = now + 5

    tour_cache = _tour_cache_file()
    if tour_cache.exists():
        try:
            cache = json.loads(tour_cache.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
        cache["status"] = "completed"
        cache["launch_at"] = launch_at
        cache["redirect_at"] = redirect_at
        if payload and payload.test_results:
            cache["test_results"] = payload.test_results
        tour_cache.write_text(json.dumps(cache, indent=2), encoding="utf-8")

    return {
        "status": "completed",
        "message": "Configuration saved. DeepTutor will restart shortly.",
        "launch_at": launch_at,
        "redirect_at": redirect_at,
        "env": rendered,
    }


@router.post("/tour/reopen")
async def reopen_tour():
    return {
        "message": "Run the terminal setup guide from the project root to re-open the guided setup.",
        "command": "python scripts/start_tour.py",
    }
