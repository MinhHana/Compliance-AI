from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "logs" / "audit.db"


def _conn(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lien_ket (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sop_chunk_id TEXT NOT NULL,
            quydinh_chunk_id TEXT NOT NULL,
            ghi_chu TEXT,
            nguon_tao TEXT NOT NULL,
            ngay_tao TEXT NOT NULL,
            UNIQUE(sop_chunk_id, quydinh_chunk_id)
        )
        """
    )
    conn.commit()
    return conn


def create_link(
    sop_chunk_id: str,
    quydinh_chunk_id: str,
    ghi_chu: str | None,
    nguon_tao: str,
    db_path: str | Path | None = None,
) -> int:
    conn = _conn(db_path)
    conn.execute(
        """
        INSERT OR IGNORE INTO lien_ket
            (sop_chunk_id, quydinh_chunk_id, ghi_chu, nguon_tao, ngay_tao)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            sop_chunk_id,
            quydinh_chunk_id,
            ghi_chu or "",
            nguon_tao,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    row = conn.execute(
        """
        SELECT id FROM lien_ket
        WHERE sop_chunk_id = ? AND quydinh_chunk_id = ?
        """,
        (sop_chunk_id, quydinh_chunk_id),
    ).fetchone()
    conn.close()
    return int(row["id"])


def delete_link(link_id: int, db_path: str | Path | None = None) -> None:
    conn = _conn(db_path)
    conn.execute("DELETE FROM lien_ket WHERE id = ?", (link_id,))
    conn.commit()
    conn.close()


def list_links(db_path: str | Path | None = None) -> list[dict]:
    conn = _conn(db_path)
    rows = conn.execute("SELECT * FROM lien_ket ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def links_for_sop_chunk(
    sop_chunk_id: str,
    db_path: str | Path | None = None,
) -> list[dict]:
    conn = _conn(db_path)
    rows = conn.execute(
        "SELECT * FROM lien_ket WHERE sop_chunk_id = ? ORDER BY id",
        (sop_chunk_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
