"""Validation and repair helpers for embedding vectors.

Embedding providers occasionally return malformed vectors with ``null`` or
non-finite values. LlamaIndex similarity code assumes every coordinate is a
finite number, so sanitize at the boundary before vectors reach retrieval or
persistence.
"""

from __future__ import annotations

import json
import math
import os
from numbers import Real
from pathlib import Path
from typing import Any


class EmbeddingVectorError(ValueError):
    """Raised when an embedding vector cannot be made usable."""


def sanitize_embedding_vector(
    vector: Any,
    *,
    label: str,
    expected_dim: int | None = None,
    allow_all_invalid: bool = False,
) -> tuple[list[float], int]:
    """Return a finite-float vector and the number of repaired coordinates.

    ``None``/``NaN``/``Infinity`` coordinates are replaced with ``0.0``. Empty
    vectors, non-list vectors, non-numeric coordinates, and dimension drift are
    rejected because those cases indicate a provider/schema mismatch rather than
    a small recoverable coordinate-level defect.
    """

    if vector is None and allow_all_invalid and expected_dim:
        return [0.0] * expected_dim, expected_dim
    if not isinstance(vector, list):
        raise EmbeddingVectorError(f"{label} is not a list vector")
    if not vector:
        if allow_all_invalid and expected_dim:
            return [0.0] * expected_dim, expected_dim
        raise EmbeddingVectorError(f"{label} is empty")
    if expected_dim is not None and expected_dim > 0 and len(vector) != expected_dim:
        raise EmbeddingVectorError(
            f"{label} has {len(vector)} dimensions, expected {expected_dim}"
        )

    sanitized: list[float] = []
    repaired = 0
    for idx, value in enumerate(vector):
        if isinstance(value, bool):
            raise EmbeddingVectorError(f"{label}[{idx}] is boolean, not numeric")
        if isinstance(value, Real):
            numeric = float(value)
            if math.isfinite(numeric):
                sanitized.append(numeric)
                continue
        elif value is not None:
            raise EmbeddingVectorError(
                f"{label}[{idx}] is {type(value).__name__}, not numeric"
            )

        sanitized.append(0.0)
        repaired += 1

    if repaired == len(sanitized) and not allow_all_invalid:
        raise EmbeddingVectorError(f"{label} has no finite numeric coordinates")

    return sanitized, repaired


def sanitize_embedding_batch(
    embeddings: Any,
    *,
    label: str,
    expected_count: int | None = None,
    expected_dim: int | None = None,
    allow_all_invalid: bool = False,
) -> tuple[list[list[float]], int]:
    """Sanitize a batch of embeddings and return ``(vectors, repaired_count)``."""

    if not isinstance(embeddings, list):
        raise EmbeddingVectorError(f"{label} response is not a list of vectors")
    if expected_count is not None and len(embeddings) != expected_count:
        raise EmbeddingVectorError(
            f"{label} response count mismatch: expected {expected_count}, got {len(embeddings)}"
        )

    inferred_dim = expected_dim
    if not inferred_dim:
        inferred_dim = next(
            (len(vector) for vector in embeddings if isinstance(vector, list) and vector),
            None,
        )

    sanitized: list[list[float]] = []
    repaired = 0
    for idx, vector in enumerate(embeddings):
        clean, fixed = sanitize_embedding_vector(
            vector,
            label=f"{label}[{idx}]",
            expected_dim=inferred_dim,
            allow_all_invalid=allow_all_invalid,
        )
        sanitized.append(clean)
        repaired += fixed

    return sanitized, repaired


def repair_persisted_vector_stores(
    storage_dir: Path,
    *,
    expected_dim: int | None = None,
) -> dict[str, int]:
    """Repair persisted LlamaIndex simple-vector-store JSON files in-place.

    Existing indexes from a bad embedding response may contain ``null`` values.
    This replaces coordinate-level defects with ``0.0`` so retrieval does not
    crash. The function is intentionally tolerant of LlamaIndex storage layout
    variants and only edits dictionaries named ``embedding_dict``.
    """

    report = {"files": 0, "vectors": 0, "coordinates": 0}
    if not storage_dir.exists():
        return report

    for path in storage_dir.glob("*vector_store*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        changed = _repair_embedding_dicts(data, expected_dim=expected_dim, report=report)
        if not changed:
            continue

        tmp_path = path.with_suffix(f"{path.suffix}.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, path)
        report["files"] += 1

    return report


def _repair_embedding_dicts(
    value: Any,
    *,
    expected_dim: int | None,
    report: dict[str, int],
) -> bool:
    changed = False
    if isinstance(value, dict):
        for key, child in list(value.items()):
            if key == "embedding_dict" and isinstance(child, dict):
                inferred_dim = expected_dim or _infer_embedding_dim(child)
                for vector_id, vector in list(child.items()):
                    try:
                        clean, fixed = sanitize_embedding_vector(
                            vector,
                            label=f"embedding_dict[{vector_id}]",
                            expected_dim=inferred_dim,
                            allow_all_invalid=True,
                        )
                    except EmbeddingVectorError:
                        if inferred_dim:
                            child[vector_id] = [0.0] * inferred_dim
                            report["vectors"] += 1
                            report["coordinates"] += inferred_dim
                            changed = True
                        continue
                    if fixed:
                        child[vector_id] = clean
                        report["vectors"] += 1
                        report["coordinates"] += fixed
                        changed = True
                continue
            if _repair_embedding_dicts(child, expected_dim=expected_dim, report=report):
                changed = True
    elif isinstance(value, list):
        for child in value:
            if _repair_embedding_dicts(child, expected_dim=expected_dim, report=report):
                changed = True
    return changed


def _infer_embedding_dim(embedding_dict: dict[str, Any]) -> int | None:
    for vector in embedding_dict.values():
        if isinstance(vector, list) and vector:
            return len(vector)
    return None
