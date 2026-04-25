from __future__ import annotations

from datetime import datetime, timedelta
import json

from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.knowledge.progress_tracker import ProgressStage, ProgressTracker
from deeptutor.services.config.knowledge_base_config import KnowledgeBaseConfigService


def test_progress_tracker_persists_snapshot_and_config(tmp_path) -> None:
    tracker = ProgressTracker("demo-kb", tmp_path)

    tracker.update(
        ProgressStage.PROCESSING_DOCUMENTS,
        "Embedding batches: 2/8 complete",
        current=2,
        total=8,
    )

    assert tracker.progress_file.exists()

    with open(tracker.progress_file, encoding="utf-8") as f:
        payload = json.load(f)

    assert payload["stage"] == "processing_documents"
    assert payload["progress_percent"] == 25
    assert payload["message"] == "Embedding batches: 2/8 complete"

    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    status = manager.get_kb_status("demo-kb")

    assert status is not None
    assert status["status"] == "processing"
    assert status["progress"]["message"] == "Embedding batches: 2/8 complete"


def test_progress_tracker_get_progress_falls_back_to_config(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.update_kb_status(
        name="demo-kb",
        status="processing",
        progress={
            "stage": "processing_documents",
            "message": "Recovered from kb_config",
            "percent": 60,
            "current": 3,
            "total": 5,
        },
    )

    tracker = ProgressTracker("demo-kb", tmp_path)

    assert tracker.get_progress() == {
        "stage": "processing_documents",
        "message": "Recovered from kb_config",
        "percent": 60,
        "current": 3,
        "total": 5,
    }


def test_config_service_mutations_preserve_fresh_manager_status(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    processing_progress = {
        "stage": "processing_documents",
        "message": "Embedding batches: 1/1 complete",
        "percent": 100,
        "timestamp": datetime.now().isoformat(),
    }
    manager.update_kb_status("demo-kb", "processing", progress=processing_progress)

    stale_service = KnowledgeBaseConfigService(tmp_path / "kb_config.json")
    manager.update_kb_status(
        "demo-kb",
        "ready",
        progress={
            "stage": "completed",
            "message": "Knowledge base ready",
            "percent": 100,
            "timestamp": datetime.now().isoformat(),
        },
    )

    stale_service.set_kb_config("demo-kb", {"needs_reindex": False})

    status = manager.get_kb_status("demo-kb")
    assert status is not None
    assert status["status"] == "ready"
    assert status["progress"] is None


def test_manager_get_info_recovers_ready_state_from_completed_snapshot(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    kb_dir = tmp_path / "demo-kb"
    (kb_dir / "raw").mkdir(parents=True)
    (kb_dir / "raw" / "notes.txt").write_text("hello", encoding="utf-8")
    (kb_dir / "llamaindex_storage").mkdir()
    (kb_dir / "llamaindex_storage" / "docstore.json").write_text("{}", encoding="utf-8")

    old_timestamp = (datetime.now() - timedelta(minutes=5)).isoformat()
    manager.update_kb_status(
        "demo-kb",
        "processing",
        progress={
            "stage": "processing_documents",
            "message": "Embedding batches: 1/1 complete",
            "percent": 100,
            "current": 1,
            "total": 1,
            "timestamp": old_timestamp,
            "task_id": "stale-task",
        },
    )
    with open(kb_dir / ".progress.json", "w", encoding="utf-8") as progress_file:
        json.dump(
            {
                "stage": "completed",
                "message": "Knowledge base initialization complete!",
                "progress_percent": 100,
                "current": 1,
                "total": 1,
                "timestamp": datetime.now().isoformat(),
                "task_id": "completed-task",
            },
            progress_file,
        )

    info = manager.get_info("demo-kb")

    assert info["status"] == "ready"
    assert info["progress"] is None
    assert info["statistics"]["status"] == "ready"
    assert info["statistics"]["progress"] is None
    assert info["statistics"]["rag_initialized"] is True

    status = manager.get_kb_status("demo-kb")
    assert status is not None
    assert status["status"] == "ready"
    assert status["progress"] is None


def test_manager_get_info_recovers_stale_finished_processing_progress(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    kb_dir = tmp_path / "demo-kb"
    (kb_dir / "raw").mkdir(parents=True)
    (kb_dir / "raw" / "notes.txt").write_text("hello", encoding="utf-8")
    (kb_dir / "llamaindex_storage").mkdir()
    (kb_dir / "llamaindex_storage" / "docstore.json").write_text("{}", encoding="utf-8")

    manager.update_kb_status(
        "demo-kb",
        "processing",
        progress={
            "stage": "processing_documents",
            "message": "Embedding batches: 1/1 complete",
            "percent": 100,
            "current": 1,
            "total": 1,
            "timestamp": (datetime.now() - timedelta(minutes=6)).isoformat(),
            "task_id": "stale-task",
        },
    )

    info = manager.get_info("demo-kb")

    assert info["status"] == "ready"
    assert info["progress"] is None
    status = manager.get_kb_status("demo-kb")
    assert status is not None
    assert status["status"] == "ready"
    assert status["progress"] is None
