"""Tests for embedding vector validation and persisted vector-store repair."""

from __future__ import annotations

import json
import math

import pytest

from deeptutor.services.embedding.vector_sanitizer import (
    EmbeddingVectorError,
    repair_persisted_vector_stores,
    sanitize_embedding_batch,
    sanitize_embedding_vector,
)


def test_sanitize_embedding_vector_replaces_null_and_non_finite_values() -> None:
    vector, repaired = sanitize_embedding_vector(
        [0.1, None, math.nan, math.inf, -math.inf, 0.2],
        label="query",
    )

    assert vector == [0.1, 0.0, 0.0, 0.0, 0.0, 0.2]
    assert repaired == 4


def test_sanitize_embedding_vector_rejects_non_numeric_coordinates() -> None:
    with pytest.raises(EmbeddingVectorError, match="not numeric"):
        sanitize_embedding_vector([0.1, "bad", 0.2], label="query")


def test_sanitize_embedding_batch_rejects_count_mismatch() -> None:
    with pytest.raises(EmbeddingVectorError, match="count mismatch"):
        sanitize_embedding_batch(
            [[0.1, 0.2]],
            label="provider:model",
            expected_count=2,
        )


def test_sanitize_embedding_batch_rejects_dimension_drift() -> None:
    with pytest.raises(EmbeddingVectorError, match="expected 2"):
        sanitize_embedding_batch(
            [[0.1, 0.2], [0.3, 0.4, 0.5]],
            label="provider:model",
        )


def test_repair_persisted_vector_stores_rewrites_malformed_coordinates(tmp_path) -> None:
    vector_store = tmp_path / "default__vector_store.json"
    vector_store.write_text(
        json.dumps(
            {
                "embedding_dict": {
                    "good": [0.1, 0.2, 0.3],
                    "bad": [0.4, None, math.nan],
                    "missing": None,
                    "empty": [],
                    "wrong_type": [0.5, "bad", 0.6],
                },
                "text_id_to_ref_doc_id": {},
            }
        ),
        encoding="utf-8",
    )

    report = repair_persisted_vector_stores(tmp_path)

    assert report == {"files": 1, "vectors": 4, "coordinates": 11}
    repaired = json.loads(vector_store.read_text(encoding="utf-8"))
    assert repaired["embedding_dict"]["good"] == [0.1, 0.2, 0.3]
    assert repaired["embedding_dict"]["bad"] == [0.4, 0.0, 0.0]
    assert repaired["embedding_dict"]["missing"] == [0.0, 0.0, 0.0]
    assert repaired["embedding_dict"]["empty"] == [0.0, 0.0, 0.0]
    assert repaired["embedding_dict"]["wrong_type"] == [0.0, 0.0, 0.0]
