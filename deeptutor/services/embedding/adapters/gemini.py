"""Native Gemini embedding adapter."""

from __future__ import annotations

from typing import Any

import httpx

from .base import BaseEmbeddingAdapter, EmbeddingRequest, EmbeddingResponse


class GeminiEmbeddingAdapter(BaseEmbeddingAdapter):
    """Call the native Gemini `batchEmbedContents` endpoint."""

    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    DEFAULT_DIMENSIONS = 3072

    @staticmethod
    def _model_resource(model: str) -> str:
        clean = (model or "").strip()
        if not clean:
            raise ValueError("Gemini embedding model is required")
        return clean if clean.startswith("models/") else f"models/{clean}"

    @staticmethod
    def _extract_embeddings(data: Any) -> list[list[float]]:
        if not isinstance(data, dict):
            raise ValueError(f"Gemini embedding response is not a JSON object: {type(data).__name__}")
        if "error" in data:
            raise ValueError(f"Gemini embedding provider returned error payload: {data['error']}")

        raw_embeddings = data.get("embeddings")
        if raw_embeddings is None and isinstance(data.get("embedding"), dict):
            raw_embeddings = [data["embedding"]]
        if not isinstance(raw_embeddings, list) or not raw_embeddings:
            keys = sorted(data.keys())
            raise ValueError(
                "Cannot parse Gemini embeddings from response JSON. "
                f"Top-level keys={keys}, expected embeddings[].values."
            )

        embeddings: list[list[float]] = []
        for item in raw_embeddings:
            if not isinstance(item, dict) or not isinstance(item.get("values"), list):
                raise ValueError("Gemini embedding item is missing a values array.")
            embeddings.append(item["values"])
        return embeddings

    def _should_send_output_dimensionality(self, dimensions: int | None) -> bool:
        if not dimensions:
            return False
        if self.send_dimensions is False:
            return False
        if self.send_dimensions is True:
            return True
        return dimensions != self.DEFAULT_DIMENSIONS

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY or EMBEDDING_API_KEY is required for Gemini embeddings")

        model = request.model or self.model
        model_resource = self._model_resource(model)
        base_url = (self.base_url or self.DEFAULT_BASE_URL).rstrip("/")
        endpoint = f"{base_url}/{model_resource}:batchEmbedContents"
        dimensions = request.dimensions or self.dimensions

        requests: list[dict[str, Any]] = []
        for text in request.texts:
            item: dict[str, Any] = {
                "model": model_resource,
                "content": {"parts": [{"text": text}]},
            }
            if self._should_send_output_dimensionality(dimensions):
                item["outputDimensionality"] = dimensions
            requests.append(item)

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
            **{str(k): str(v) for k, v in self.extra_headers.items()},
        }
        timeout = httpx.Timeout(
            connect=10.0,
            read=max(self.request_timeout, 60),
            write=10.0,
            pool=10.0,
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(endpoint, headers=headers, json={"requests": requests})
            response.raise_for_status()
            data = response.json()

        embeddings = self._extract_embeddings(data)
        if len(embeddings) != len(request.texts):
            raise ValueError(
                "Gemini embedding response count mismatch: "
                f"expected {len(request.texts)}, got {len(embeddings)}."
            )

        actual_dims = len(embeddings[0]) if embeddings else 0
        return EmbeddingResponse(
            embeddings=embeddings,
            model=model,
            dimensions=actual_dims,
            usage=data.get("usageMetadata", {}) if isinstance(data, dict) else {},
        )

    def get_model_info(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "dimensions": self.dimensions or self.DEFAULT_DIMENSIONS,
            "supported_dimensions": [768, 1536, 3072],
            "supports_variable_dimensions": True,
            "provider": "gemini",
        }
