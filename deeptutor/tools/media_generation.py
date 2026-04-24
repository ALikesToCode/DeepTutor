"""NavyAI image/video generation helper for visual learning assets."""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any

import httpx

NAVY_DEFAULT_BASE_URL = "https://api.navy/v1"
NAVY_IMAGES_ENDPOINT = "/images/generations"
DEFAULT_IMAGE_MODEL = "gpt-image-2"
DEFAULT_VIDEO_MODEL = "grok-imagine-video"
DEFAULT_OUTPUT_DIR = Path("data/user/generated/media")


def _env_value(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    try:
        from deeptutor.services.config.env_store import get_env_store

        return get_env_store().get(name, "").strip()
    except Exception:
        return ""


def _resolve_api_key(explicit: str | None = None) -> str:
    if explicit:
        return explicit.strip()

    navy_key = _env_value("NAVY_API_KEY")
    if navy_key:
        return navy_key

    llm_binding = _env_value("LLM_BINDING").lower()
    llm_host = _env_value("LLM_HOST").lower()
    if llm_binding == "navy" or "api.navy" in llm_host:
        llm_key = _env_value("LLM_API_KEY")
        if llm_key:
            return llm_key

    embedding_binding = _env_value("EMBEDDING_BINDING").lower()
    embedding_host = _env_value("EMBEDDING_HOST").lower()
    if embedding_binding == "navy" or "api.navy" in embedding_host:
        embedding_key = _env_value("EMBEDDING_API_KEY")
        if embedding_key:
            return embedding_key

    return ""


def _normalize_base_url(base_url: str | None = None) -> str:
    value = (
        (base_url or "").strip()
        or _env_value("NAVY_API_BASE")
        or _env_value("NAVY_API_HOST")
        or _env_value("NAVY_BASE_URL")
        or _env_value("NAVY_HOST")
    )
    if not value:
        llm_host = _env_value("LLM_HOST")
        embedding_host = _env_value("EMBEDDING_HOST")
        if "api.navy" in llm_host.lower():
            value = llm_host
        elif "api.navy" in embedding_host.lower():
            value = embedding_host
    if not value:
        value = NAVY_DEFAULT_BASE_URL

    clean = value.rstrip("/")
    for suffix in ("/images/generations", "/chat/completions", "/embeddings"):
        if clean.endswith(suffix):
            clean = clean[: -len(suffix)]
    if clean == "https://api.navy":
        clean = NAVY_DEFAULT_BASE_URL
    return clean.rstrip("/")


def _coerce_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    return None


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _media_type_from_model(model: str, requested: str) -> str:
    requested = (requested or "").strip().lower()
    if requested in {"image", "video"}:
        return requested
    model_lower = model.lower()
    if "video" in model_lower or model_lower.startswith(("veo", "cogvideox")):
        return "video"
    return "image"


def _default_model(output_type: str) -> str:
    if output_type == "video":
        return _env_value("NAVY_VIDEO_MODEL") or DEFAULT_VIDEO_MODEL
    return _env_value("NAVY_IMAGE_MODEL") or DEFAULT_IMAGE_MODEL


def _extract_assets(payload: Any, output_type: str, output_dir: Path) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []

    def add_url(url: Any, media_type: str = output_type) -> None:
        if isinstance(url, str) and url.strip():
            assets.append({"type": media_type, "url": url.strip()})

    def add_b64(value: Any, index: int, media_type: str = output_type) -> None:
        if not isinstance(value, str) or not value.strip():
            return
        output_dir.mkdir(parents=True, exist_ok=True)
        ext = "mp4" if media_type == "video" else "png"
        filename = f"navy-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{index}.{ext}"
        path = output_dir / filename
        path.write_bytes(base64.b64decode(value))
        assets.append({"type": media_type, "path": str(path), "filename": filename})

    def walk(value: Any, index: int = 0) -> None:
        if isinstance(value, dict):
            media_type = str(value.get("type") or output_type).lower()
            if media_type not in {"image", "video"}:
                media_type = output_type
            add_url(value.get("url"), media_type)
            add_url(value.get("video_url"), "video")
            add_url(value.get("image_url"), "image")
            add_b64(value.get("b64_json"), index, media_type)
            for key in ("data", "result", "output", "images", "videos"):
                if key in value:
                    walk(value[key], index)
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                walk(item, idx)

    walk(payload)
    return assets


def _extract_job_id(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("id", "job_id", "jobId"):
        value = payload.get(key)
        if isinstance(value, str) and value.startswith("job_"):
            return value
    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_job_id(data)
    return ""


def _status_from_payload(payload: Any) -> str:
    if isinstance(payload, dict):
        status = payload.get("status")
        if isinstance(status, str) and status:
            return status
    return "completed"


async def _read_json(response: httpx.Response) -> dict[str, Any]:
    text = response.text
    try:
        data = response.json()
    except ValueError as exc:
        snippet = text.strip().replace("\n", " ")[:300]
        raise RuntimeError(
            f"NavyAI returned non-JSON response: HTTP {response.status_code}: {snippet}"
        ) from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"NavyAI returned unexpected JSON type: {type(data).__name__}")
    if response.status_code >= 400:
        raise RuntimeError(f"NavyAI API error HTTP {response.status_code}: {data}")
    return data


async def poll_media_job(
    job_id: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    poll_interval: float = 3.0,
    timeout_seconds: float = 600.0,
    output_type: str = "image",
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Poll a NavyAI async image/video generation job."""
    if not job_id:
        raise ValueError("job_id is required for media job polling")
    resolved_key = _resolve_api_key(api_key)
    if not resolved_key:
        raise ValueError("NAVY_API_KEY is not configured")

    resolved_base = _normalize_base_url(base_url)
    endpoint = f"{resolved_base}{NAVY_IMAGES_ENDPOINT}/{job_id}"
    out_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
    deadline = asyncio.get_running_loop().time() + max(1.0, timeout_seconds)
    interval = max(1.0, poll_interval)
    headers = {"Authorization": f"Bearer {resolved_key}"}

    last_payload: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        while True:
            response = await client.get(endpoint, headers=headers)
            payload = await _read_json(response)
            last_payload = payload
            status = _status_from_payload(payload)
            if status in {"completed", "failed"}:
                assets = _extract_assets(payload.get("result", payload), output_type, out_dir)
                return {
                    "provider": "navy",
                    "endpoint": endpoint,
                    "job_id": job_id,
                    "status": status,
                    "output_type": output_type,
                    "assets": assets,
                    "raw": payload,
                }
            if asyncio.get_running_loop().time() >= deadline:
                return {
                    "provider": "navy",
                    "endpoint": endpoint,
                    "job_id": job_id,
                    "status": status or "timeout",
                    "output_type": output_type,
                    "assets": [],
                    "raw": last_payload,
                    "timeout": True,
                }
            await asyncio.sleep(interval)


async def generate_media(
    *,
    prompt: str = "",
    output_type: str = "image",
    purpose: str = "general",
    model: str | None = None,
    size: str | None = None,
    aspect_ratio: str | None = None,
    image_url: str | None = None,
    negative_prompt: str | None = None,
    seed: int | str | None = None,
    quality: str | None = None,
    style: str | None = None,
    seconds: float | str | None = None,
    sync: bool | str | None = None,
    response_format: str | None = "url",
    job_id: str | None = None,
    poll: bool | str | None = None,
    poll_interval: float | str = 3.0,
    timeout_seconds: float | str = 600.0,
    api_key: str | None = None,
    base_url: str | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Generate or poll NavyAI image/video assets."""
    if job_id:
        return await poll_media_job(
            job_id=job_id,
            api_key=api_key,
            base_url=base_url,
            poll_interval=_coerce_float(poll_interval) or 3.0,
            timeout_seconds=_coerce_float(timeout_seconds) or 600.0,
            output_type=output_type,
            output_dir=output_dir,
        )

    if not prompt.strip():
        raise ValueError("prompt is required when job_id is not provided")

    resolved_model = (model or "").strip()
    resolved_output_type = (output_type or "image").strip().lower()
    if not resolved_model:
        resolved_model = _default_model(resolved_output_type)
    resolved_output_type = _media_type_from_model(resolved_model, resolved_output_type)

    resolved_key = _resolve_api_key(api_key)
    if not resolved_key:
        raise ValueError("NAVY_API_KEY is not configured")

    resolved_base = _normalize_base_url(base_url)
    endpoint = f"{resolved_base}{NAVY_IMAGES_ENDPOINT}"
    out_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR

    payload: dict[str, Any] = {
        "model": resolved_model,
        "prompt": prompt.strip(),
    }
    if size:
        payload["size"] = str(size).strip()
    if aspect_ratio:
        payload["aspect_ratio"] = str(aspect_ratio).strip()
    if image_url:
        payload["image_url"] = str(image_url).strip()
    if negative_prompt:
        payload["negative_prompt"] = str(negative_prompt).strip()
    seed_value = _coerce_int(seed)
    if seed_value is not None:
        payload["seed"] = seed_value
    if quality:
        payload["quality"] = str(quality).strip()
    if style:
        payload["style"] = str(style).strip()
    seconds_value = _coerce_float(seconds)
    if seconds_value is not None:
        payload["seconds"] = max(0.0, min(seconds_value, 10.0))
    sync_value = _coerce_bool(sync)
    if sync_value is not None:
        payload["sync"] = sync_value
    elif resolved_output_type == "video":
        payload["sync"] = False
    if response_format:
        payload["response_format"] = str(response_format).strip()

    headers = {
        "Authorization": f"Bearer {resolved_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        response = await client.post(endpoint, headers=headers, json=payload)
        data = await _read_json(response)

    assets = _extract_assets(data, resolved_output_type, out_dir)
    status = _status_from_payload(data)
    returned_job_id = _extract_job_id(data)
    result: dict[str, Any] = {
        "provider": "navy",
        "endpoint": endpoint,
        "model": resolved_model,
        "output_type": resolved_output_type,
        "purpose": purpose,
        "prompt": prompt.strip(),
        "status": status,
        "job_id": returned_job_id,
        "assets": assets,
        "raw": data,
    }

    should_poll = _coerce_bool(poll) is True
    if returned_job_id and should_poll:
        polled = await poll_media_job(
            job_id=returned_job_id,
            api_key=resolved_key,
            base_url=resolved_base,
            poll_interval=_coerce_float(poll_interval) or 3.0,
            timeout_seconds=_coerce_float(timeout_seconds) or 600.0,
            output_type=resolved_output_type,
            output_dir=out_dir,
        )
        result.update(
            {
                "status": polled.get("status", result["status"]),
                "assets": polled.get("assets", assets),
                "raw": polled.get("raw", data),
                "poll_result": polled,
            }
        )
    return result
