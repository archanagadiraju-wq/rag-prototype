"""Persistent job cache: in-memory first, file-system backed.

Each job gets its own directory:
    {data_dir}/jobs/{job_id}/

Each cache key is stored as a separate JSON file:
    {data_dir}/jobs/{job_id}/{key}.json

On get(): memory is checked first; on a miss the file is loaded and warm-cached.
On put(): value is written to memory and flushed to disk.
On clear(): memory entry removed and job directory deleted.

NetworkX Graph objects are transparently serialized via node_link_data /
node_link_graph so the knowledge graph survives restarts.
"""
from __future__ import annotations
import json
import logging
import shutil
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_store: dict[str, dict[str, Any]] = {}


# ── Path helpers ──────────────────────────────────────────────────────────────

def _root() -> Path:
    from config import settings
    if settings.data_dir:
        base = Path(settings.data_dir)
    else:
        # backend/services/job_cache.py → go up two levels to backend/, then data/jobs/
        base = Path(__file__).resolve().parent.parent / "data" / "jobs"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _job_dir(job_id: str) -> Path:
    d = _root() / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _key_file(job_id: str, key: str) -> Path:
    safe = key.replace("/", "_").replace("\\", "_").replace(" ", "_")
    return _job_dir(job_id) / f"{safe}.json"


# ── Serialization ─────────────────────────────────────────────────────────────

def _to_json(value: Any) -> Any:
    try:
        import networkx as nx
        if isinstance(value, nx.Graph):
            return {"__nx__": True, "data": nx.node_link_data(value)}
    except ImportError:
        pass
    return value


def _from_json(value: Any) -> Any:
    if isinstance(value, dict) and value.get("__nx__"):
        try:
            import networkx as nx
            return nx.node_link_graph(value["data"])
        except Exception as exc:
            log.warning("job_cache: networkx deserialize failed: %s", exc)
    return value


# ── Public API ────────────────────────────────────────────────────────────────

def put(job_id: str, key: str, value: Any) -> None:
    if job_id not in _store:
        _store[job_id] = {}
    _store[job_id][key] = value

    try:
        path = _key_file(job_id, key)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_to_json(value), f)
    except Exception as exc:
        log.warning("job_cache: disk write failed [%s/%s]: %s", job_id[:8], key, exc)


def get(job_id: str, key: str, default: Any = None) -> Any:
    # Memory-first
    val = _store.get(job_id, {}).get(key)
    if val is not None:
        return val

    # Disk fallback (warm-cache the result)
    try:
        path = _key_file(job_id, key)
        if path.exists():
            with open(path, encoding="utf-8") as f:
                val = _from_json(json.load(f))
            if job_id not in _store:
                _store[job_id] = {}
            _store[job_id][key] = val
            return val
    except Exception as exc:
        log.warning("job_cache: disk read failed [%s/%s]: %s", job_id[:8], key, exc)

    return default


def exists(job_id: str, key: str) -> bool:
    """Cheap presence check — true if a key is in memory or on disk."""
    if key in _store.get(job_id, {}):
        return True
    return _key_file(job_id, key).exists()


def clear(job_id: str) -> None:
    _store.pop(job_id, None)
    try:
        job_path = _root() / job_id
        if job_path.exists():
            shutil.rmtree(job_path)
    except Exception as exc:
        log.warning("job_cache: disk clear failed [%s]: %s", job_id[:8], exc)
