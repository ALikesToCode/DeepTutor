"""Tests for NavyAI media generation helper."""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.tools import media_generation


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = "{}"

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *, post_payload: dict[str, Any] | None = None, get_payloads=None) -> None:
        self.post_payload = post_payload or {}
        self.get_payloads = list(get_payloads or [])
        self.posts: list[dict[str, Any]] = []
        self.gets: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url: str, headers: dict[str, str], json: dict[str, Any]):
        self.posts.append({"url": url, "headers": headers, "json": json})
        return _FakeResponse(self.post_payload)

    async def get(self, url: str, headers: dict[str, str]):
        self.gets.append(url)
        payload = self.get_payloads.pop(0) if self.get_payloads else {"status": "failed"}
        return _FakeResponse(payload)


@pytest.mark.asyncio
async def test_generate_media_posts_to_navy_images_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeAsyncClient(
        post_payload={"data": [{"url": "https://cdn.example/diagram.png"}]}
    )
    monkeypatch.setenv("NAVY_API_KEY", "sk-navy-test")
    monkeypatch.setattr(media_generation.httpx, "AsyncClient", lambda *_a, **_k: fake_client)

    result = await media_generation.generate_media(
        prompt="A clean labeled biology diagram",
        output_type="image",
        model="dall-e-3",
        aspect_ratio="16:9",
    )

    assert result["status"] == "completed"
    assert result["assets"] == [{"type": "image", "url": "https://cdn.example/diagram.png"}]
    assert fake_client.posts[0]["url"] == "https://api.navy/v1/images/generations"
    assert fake_client.posts[0]["json"]["model"] == "dall-e-3"
    assert fake_client.posts[0]["json"]["prompt"] == "A clean labeled biology diagram"
    assert fake_client.posts[0]["json"]["aspect_ratio"] == "16:9"


@pytest.mark.asyncio
async def test_generate_media_uses_image_default(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeAsyncClient(
        post_payload={"data": [{"url": "https://cdn.example/default.png"}]}
    )
    monkeypatch.setenv("NAVY_API_KEY", "sk-navy-test")
    monkeypatch.delenv("NAVY_IMAGE_MODEL", raising=False)
    monkeypatch.setattr(media_generation.httpx, "AsyncClient", lambda *_a, **_k: fake_client)

    await media_generation.generate_media(prompt="A visual summary", output_type="image")

    assert fake_client.posts[0]["json"]["model"] == "gpt-image-2"


@pytest.mark.asyncio
async def test_generate_video_defaults_to_async_job(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeAsyncClient(post_payload={"id": "job_video_1", "status": "queued"})
    monkeypatch.setenv("NAVY_API_KEY", "sk-navy-test")
    monkeypatch.setattr(media_generation.httpx, "AsyncClient", lambda *_a, **_k: fake_client)

    result = await media_generation.generate_media(
        prompt="Animate gradient descent steps",
        output_type="video",
        model="cogvideox-flash",
        seconds=6,
    )

    assert result["job_id"] == "job_video_1"
    assert result["status"] == "queued"
    assert fake_client.posts[0]["json"]["sync"] is False
    assert fake_client.posts[0]["json"]["seconds"] == 6


@pytest.mark.asyncio
async def test_generate_media_uses_video_default(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeAsyncClient(post_payload={"id": "job_video_2", "status": "queued"})
    monkeypatch.setenv("NAVY_API_KEY", "sk-navy-test")
    monkeypatch.delenv("NAVY_VIDEO_MODEL", raising=False)
    monkeypatch.setattr(media_generation.httpx, "AsyncClient", lambda *_a, **_k: fake_client)

    await media_generation.generate_media(prompt="Animate a concept", output_type="video")

    assert fake_client.posts[0]["json"]["model"] == "grok-imagine-video"


@pytest.mark.asyncio
async def test_poll_media_job_extracts_completed_video_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeAsyncClient(
        get_payloads=[
            {
                "status": "completed",
                "result": {"data": [{"video_url": "https://cdn.example/clip.mp4"}]},
            }
        ]
    )
    monkeypatch.setenv("NAVY_API_KEY", "sk-navy-test")
    monkeypatch.setattr(media_generation.httpx, "AsyncClient", lambda *_a, **_k: fake_client)

    result = await media_generation.poll_media_job("job_video_1", output_type="video")

    assert result["status"] == "completed"
    assert result["assets"] == [{"type": "video", "url": "https://cdn.example/clip.mp4"}]
    assert fake_client.gets == ["https://api.navy/v1/images/generations/job_video_1"]
