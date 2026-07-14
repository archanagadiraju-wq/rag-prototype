"""SQLite-backed structured store for document table data.

Each job gets its own database file at:
    {data_dir}/jobs/{job_id}/tables_{prefix}.db

Tables extracted from the document are loaded as SQL tables so numerical /
aggregation queries can be run alongside vector and graph retrieval.
The database survives server restarts because it lives in the persistent
data directory, not in /tmp.
"""
from __future__ import annotations
import re
import sqlite3
from pathlib import Path


def _job_dir(job_id: str) -> Path:
    from config import settings
    if settings.data_dir:
        base = Path(settings.data_dir)
    else:
        base = Path(__file__).resolve().parent.parent / "data" / "jobs"
    d = base / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path(job_id: str, cache_prefix: str = "") -> str:
    pfx = cache_prefix.replace("_", "")
    filename = f"tables_{pfx}.db" if pfx else "tables.db"
    return str(_job_dir(job_id) / filename)


def _safe_col(name: str) -> str:
    col = re.sub(r"[^A-Za-z0-9_]", "_", name.strip())
    col = re.sub(r"_+", "_", col).strip("_").lower()
    return col or "col"


# Match a leading currency token: ₱, P, $, €, £, ¥ (case-insensitive for letters)
_CURRENCY_PREFIX = re.compile(r"^\s*[₱$€£¥]\s*|^\s*P\s+", re.IGNORECASE)


def _try_parse_numeric(value) -> float | None:
    """Parse a cell as a number, tolerating common formatting in document tables.

    Handles:
      - thousand separators: '3,000.00' -> 3000.0
      - currency prefixes:   'P 100,000,000.00' -> 100000000.0, '₱ 35,018' -> 35018.0
      - accounting negatives: '(123)' -> -123.0
      - empty/None -> None
      - non-numeric strings like 'DECLINED TO BID' -> None
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Drop currency prefix
    s = _CURRENCY_PREFIX.sub("", s).strip()
    # Accounting parens for negatives
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1].strip()
    # Drop thousands commas
    s = s.replace(",", "")
    try:
        n = float(s)
        return -n if negative else n
    except ValueError:
        return None


def _infer_col_types(rows: list, n_cols: int, threshold: float = 0.7) -> list[str]:
    """For each column, decide if it should be REAL or TEXT.

    A column is declared REAL when at least `threshold` of its non-empty cells
    parse cleanly as numbers via _try_parse_numeric. Otherwise TEXT.

    This matters because SQLite's loose typing silently coerces strings like
    '3,000.00' to the integer 3 inside SUM/AVG/GROUP BY, producing wildly wrong
    aggregate results. Storing them as REAL up-front avoids that whole class
    of bug.
    """
    numeric = [0] * n_cols
    non_empty = [0] * n_cols
    for row in rows:
        padded = (list(row) + [""] * n_cols)[:n_cols]
        for i, v in enumerate(padded):
            s = "" if v is None else str(v).strip()
            if not s:
                continue
            non_empty[i] += 1
            if _try_parse_numeric(v) is not None:
                numeric[i] += 1
    types: list[str] = []
    for i in range(n_cols):
        if non_empty[i] > 0 and numeric[i] / non_empty[i] >= threshold:
            types.append("REAL")
        else:
            types.append("TEXT")
    return types


def create_tables(tables: list[dict], job_id: str, cache_prefix: str = "") -> dict[str, dict]:
    """Load extracted document tables into SQLite.  Returns registry of created tables."""
    path = db_path(job_id, cache_prefix)
    conn = sqlite3.connect(path)
    registry: dict[str, dict] = {}

    for i, tbl in enumerate(tables):
        headers = tbl.get("headers") or []
        rows    = tbl.get("rows")    or []
        if not headers or not rows:
            continue

        # Build unique, SQL-safe column names
        seen: dict[str, int] = {}
        cols: list[str] = []
        for h in headers:
            base = _safe_col(h) or f"col{len(cols) + 1}"
            if base in seen:
                seen[base] += 1
                cols.append(f"{base}_{seen[base]}")
            else:
                seen[base] = 0
                cols.append(base)

        tname = f"doc_table_{i + 1}"
        col_types = _infer_col_types(rows, len(cols))
        col_defs = ", ".join(f'"{c}" {col_types[j]}' for j, c in enumerate(cols))
        conn.execute(f"DROP TABLE IF EXISTS {tname}")
        conn.execute(f"CREATE TABLE {tname} ({col_defs})")

        ph = ", ".join(["?"] * len(cols))
        for row in rows:
            padded = (list(row) + [""] * len(cols))[:len(cols)]
            coerced: list = []
            for j, v in enumerate(padded):
                if col_types[j] == "REAL":
                    coerced.append(_try_parse_numeric(v))  # None for un-parseable
                else:
                    coerced.append(v)
            conn.execute(f"INSERT INTO {tname} VALUES ({ph})", coerced)

        # Sample rows (capped) for UI preview — stringified to keep payload JSON-safe
        sample_rows = [
            ["" if v is None else str(v) for v in (list(r) + [""] * len(cols))[:len(cols)]]
            for r in rows[:20]
        ]

        registry[tname] = {
            "original_headers": headers,
            "columns":          cols,
            "column_types":     col_types,
            "row_count":        len(rows),
            "page":             tbl.get("page"),
            "sample_rows":      sample_rows,
        }

    conn.commit()
    conn.close()
    return registry


def run_query(sql: str, job_id: str, cache_prefix: str = "") -> tuple[list[str], list[list]]:
    """Execute SQL and return (column_names, rows).  Raises sqlite3.Error on failure."""
    path = db_path(job_id, cache_prefix)
    if not Path(path).exists():
        raise FileNotFoundError(f"No SQL database for job {job_id[:8]}")
    conn = sqlite3.connect(path)
    try:
        cursor = conn.execute(sql)
        col_names = [d[0] for d in (cursor.description or [])]
        rows = [list(r) for r in cursor.fetchall()]
        return col_names, rows
    finally:
        conn.close()


def cleanup(job_id: str, cache_prefix: str = "") -> None:
    path = Path(db_path(job_id, cache_prefix))
    if path.exists():
        path.unlink()
