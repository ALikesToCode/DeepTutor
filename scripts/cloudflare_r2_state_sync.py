#!/usr/bin/env python3
"""Sync DeepTutor container data snapshots through the Worker R2 bridge."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


APP_ROOT = Path(os.environ.get("DEEPTUTOR_APP_ROOT", "/app")).resolve()
DATA_DIR = Path(os.environ.get("DEEPTUTOR_DATA_DIR", str(APP_ROOT / "data"))).resolve()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _enabled() -> bool:
    flag = _env("DEEPTUTOR_R2_STATE_SYNC_ENABLED").lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    return bool(_env("DEEPTUTOR_R2_SYNC_URL") and _env("DEEPTUTOR_R2_SYNC_TOKEN"))


def _interval_seconds() -> int:
    try:
        return max(30, int(_env("DEEPTUTOR_R2_SYNC_INTERVAL_SECONDS", "300")))
    except ValueError:
        return 300


def _request_timeout_seconds() -> int:
    try:
        return max(5, int(_env("DEEPTUTOR_R2_SYNC_REQUEST_TIMEOUT_SECONDS", "20")))
    except ValueError:
        return 20


def _request(method: str, body=None, content_length: int | None = None):
    headers = {
        "authorization": f"Bearer {_env('DEEPTUTOR_R2_SYNC_TOKEN')}",
        "user-agent": "DeepTutor-R2-State-Sync/1.0",
    }
    if body is not None:
        headers["content-type"] = "application/gzip"
    if content_length is not None:
        headers["content-length"] = str(content_length)

    request = Request(
        _env("DEEPTUTOR_R2_SYNC_URL"),
        data=body,
        method=method,
        headers=headers,
    )
    return urlopen(request, timeout=_request_timeout_seconds())


def _safe_extract(archive_path: Path, target_dir: Path) -> None:
    target = target_dir.resolve()
    has_data_root = False
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            if Path(member.name).parts[:1] == ("data",):
                has_data_root = True
            member_path = (target / member.name).resolve()
            if member_path != target and target not in member_path.parents:
                raise RuntimeError(f"Unsafe snapshot path: {member.name}")
        if has_data_root and DATA_DIR.exists():
            shutil.rmtree(DATA_DIR)
        archive.extractall(target)


def hydrate() -> int:
    if not _enabled():
        print("[R2 sync] Disabled or incomplete configuration; skipping hydrate.")
        return 0

    print("[R2 sync] Hydrating /app/data from R2 snapshot...")
    try:
        response = _request("GET")
    except HTTPError as exc:
        if exc.code == 204:
            print("[R2 sync] No existing snapshot found.")
            return 0
        print(f"[R2 sync] Hydrate failed: HTTP {exc.code}", file=sys.stderr)
        return 1
    except URLError as exc:
        print(f"[R2 sync] Hydrate failed: {exc}", file=sys.stderr)
        return 1

    with response:
        if response.status == 204:
            print("[R2 sync] No existing snapshot found.")
            return 0
        with tempfile.NamedTemporaryFile(prefix="deeptutor-r2-hydrate-", suffix=".tar.gz") as tmp:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                tmp.write(chunk)
            tmp.flush()
            if Path(tmp.name).stat().st_size == 0:
                print("[R2 sync] Empty snapshot response; skipping hydrate.")
                return 0
            _safe_extract(Path(tmp.name), APP_ROOT)

    print("[R2 sync] Hydrate complete.")
    return 0


def snapshot() -> int:
    if not _enabled():
        print("[R2 sync] Disabled or incomplete configuration; skipping snapshot.")
        return 0

    if not DATA_DIR.exists():
        print("[R2 sync] Data directory does not exist; skipping snapshot.")
        return 0

    print("[R2 sync] Writing /app/data snapshot to R2...")
    with tempfile.NamedTemporaryFile(prefix="deeptutor-r2-snapshot-", suffix=".tar.gz") as tmp:
        with tarfile.open(tmp.name, "w:gz") as archive:
            archive.add(DATA_DIR, arcname="data", recursive=True)
        archive_size = Path(tmp.name).stat().st_size
        with open(tmp.name, "rb") as body:
            try:
                with _request("PUT", body=body, content_length=archive_size) as response:
                    if response.status not in {200, 201, 204}:
                        print(
                            f"[R2 sync] Snapshot failed: HTTP {response.status}",
                            file=sys.stderr,
                        )
                        return 1
            except HTTPError as exc:
                print(f"[R2 sync] Snapshot failed: HTTP {exc.code}", file=sys.stderr)
                return 1
            except URLError as exc:
                print(f"[R2 sync] Snapshot failed: {exc}", file=sys.stderr)
                return 1

    print("[R2 sync] Snapshot complete.")
    return 0


def loop() -> int:
    if not _enabled():
        print("[R2 sync] Disabled or incomplete configuration; sync loop not started.")
        return 0

    interval = _interval_seconds()
    print(f"[R2 sync] Snapshot loop running every {interval} seconds.")
    while True:
        time.sleep(interval)
        snapshot()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("hydrate", "snapshot", "loop"))
    args = parser.parse_args()

    if args.command == "hydrate":
        return hydrate()
    if args.command == "snapshot":
        return snapshot()
    return loop()


if __name__ == "__main__":
    raise SystemExit(main())
