"""Tests for the native Gemini embedding adapter."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from deeptutor.services.embedding.adapters.base import EmbeddingRequest
from deeptutor.services.embedding.adapters.gemini import GeminiEmbeddingAdapter


class _CapturingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.payloads: list[dict[str, Any]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        import json

        self.requests.append(request)
        self.payloads.append(json.loads(request.content.decode("utf-8")))
        body = {
            "embeddings": [
                {"values": [0.1, 0.2, 0.3]},
                {"values": [0.4, 0.5, 0.6]},
            ],
            "usageMetadata": {"promptTokenCount": 4, "totalTokenCount": 4},
        }
        return httpx.Response(200, json=body)


@pytest.fixture
def capturing_httpx(monkeypatch: pytest.MonkeyPatch) -> _CapturingTransport:
    transport = _CapturingTransport()
    real_client_init = httpx.AsyncClient.__init__

    def _patched_init(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = transport
        real_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _patched_init)
    return transport


@pytest.mark.asyncio
async def test_gemini_adapter_uses_batch_embed_contents(
    capturing_httpx: _CapturingTransport,
) -> None:
    adapter = GeminiEmbeddingAdapter(
        {
            "api_key": "gemini-key",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "model": "gemini-embedding-2",
            "dimensions": 3072,
            "request_timeout": 30,
        }
    )

    response = await adapter.embed(
        EmbeddingRequest(texts=["first", "second"], model="gemini-embedding-2", dimensions=3072)
    )

    assert response.embeddings == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert response.usage == {"promptTokenCount": 4, "totalTokenCount": 4}
    assert capturing_httpx.requests[-1].url.path.endswith(
        "/v1beta/models/gemini-embedding-2:batchEmbedContents"
    )
    assert capturing_httpx.requests[-1].headers["x-goog-api-key"] == "gemini-key"
    payload = capturing_httpx.payloads[-1]
    assert [item["content"]["parts"][0]["text"] for item in payload["requests"]] == [
        "first",
        "second",
    ]
    assert all(item["model"] == "models/gemini-embedding-2" for item in payload["requests"])
    assert all("outputDimensionality" not in item for item in payload["requests"])


@pytest.mark.asyncio
async def test_gemini_adapter_can_request_reduced_dimensions(
    capturing_httpx: _CapturingTransport,
) -> None:
    adapter = GeminiEmbeddingAdapter(
        {
            "api_key": "gemini-key",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "model": "gemini-embedding-2",
            "dimensions": 768,
            "send_dimensions": None,
            "request_timeout": 30,
        }
    )

    await adapter.embed(
        EmbeddingRequest(texts=["first", "second"], model="gemini-embedding-2", dimensions=768)
    )

    assert all(
        item["outputDimensionality"] == 768 for item in capturing_httpx.payloads[-1]["requests"]
    )
