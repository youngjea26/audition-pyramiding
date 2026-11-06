"""SQLite 접근과 마이그레이션. migrations/*.sql 을 파일명 순으로 한 번씩만 적용한다."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


def migrate(conn, directory=MIGRATIONS):
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for p in sorted(Path(directory).glob("*.sql")):
        if p.stem in done:
            continue
        conn.executescript(p.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                     (p.stem, datetime.now(timezone.utc).isoformat(timespec="seconds")))
        conn.commit()
        applied.append(p.stem)
    return applied


def connect(path=":memory:"):
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)    # 접근은 서비스의 잠금으로 직렬화한다
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    migrate(conn)
    return conn


def set_meta(conn, key, value):
    conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, str(value)))


def get_meta(conn, key, default=None):
    r = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def load_baselines(conn, asof=None):
    """엔진이 쓰는 기준 dict 를 DB 에서 읽는다: {종목코드: daily_metrics 열 + score_total}. asof 를 안 주면 가장 최근 기준일."""
    asof = asof or get_meta(conn, "last_asof")
    rows = conn.execute(
        "SELECT m.*, s.total AS score_total FROM daily_metrics m LEFT JOIN scores s ON s.symbol=m.symbol AND s.asof=m.asof "
        "WHERE m.asof=?", (asof,)).fetchall()
    return {r["symbol"]: dict(r) for r in rows}
