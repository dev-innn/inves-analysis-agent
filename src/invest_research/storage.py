from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from uuid import uuid4
from contextlib import contextmanager

from .schemas import RunRequest, STAGES, utcnow


class Store:
    def __init__(self, root: str | Path, database: str | Path | None = None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = Path(database).resolve() if database else self.root / "runs.db"
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, request TEXT NOT NULL, status TEXT NOT NULL,
                    stage TEXT, error TEXT, candidates TEXT, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS stages (
                    run_id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, started_at TEXT, finished_at TEXT,
                    artifact_ids TEXT NOT NULL DEFAULT '[]', error TEXT,
                    PRIMARY KEY (run_id, name)
                );
                CREATE TABLE IF NOT EXISTS idempotency (
                    run_id TEXT NOT NULL, action TEXT NOT NULL, key TEXT NOT NULL,
                    PRIMARY KEY (run_id, action, key)
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    run_id TEXT NOT NULL, name TEXT NOT NULL, content_hash TEXT NOT NULL,
                    written_at TEXT NOT NULL, PRIMARY KEY (run_id, name)
                );
                CREATE TABLE IF NOT EXISTS revisions (
                    parent_id TEXT NOT NULL, key TEXT NOT NULL, run_id TEXT NOT NULL,
                    PRIMARY KEY (parent_id, key)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                    stage TEXT NOT NULL, tool TEXT NOT NULL, status TEXT NOT NULL,
                    latency_ms INTEGER NOT NULL, error_code TEXT, created_at TEXT NOT NULL
                );
            """)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.database, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, request: RunRequest) -> str:
        run_id = uuid4().hex
        now = utcnow()
        with self._db() as db:
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)", (run_id, request.model_dump_json(), "queued", "identity", None, "[]", now, now))
            db.executemany("INSERT INTO stages(run_id,name,status) VALUES (?,?,?)", [(run_id, name, "queued") for name in STAGES])
        (self.root / run_id).mkdir()
        return run_id

    def get(self, run_id: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                return None
            stages = db.execute("SELECT * FROM stages WHERE run_id=? ORDER BY rowid", (run_id,)).fetchall()
            artifacts = db.execute("SELECT name,content_hash,written_at FROM artifacts WHERE run_id=? ORDER BY written_at", (run_id,)).fetchall()
            events = db.execute("SELECT stage,tool,status,latency_ms,error_code,created_at FROM events WHERE run_id=? ORDER BY id DESC LIMIT 100", (run_id,)).fetchall()
        result = dict(row)
        result["request"] = json.loads(result["request"])
        result["candidates"] = json.loads(result["candidates"])
        result["stages"] = [{**dict(s), "artifact_ids": json.loads(s["artifact_ids"])} for s in stages]
        result["artifact_manifest"] = [dict(item) for item in artifacts]
        result["events"] = [dict(event) for event in reversed(events)]
        return result

    def list(self, limit: int = 20) -> list[dict]:
        with self._db() as db:
            ids = [r["id"] for r in db.execute("SELECT id FROM runs ORDER BY created_at DESC LIMIT ?", (limit,))]
        return [self.get(run_id) for run_id in ids]

    def pending(self) -> list[str]:
        with self._db() as db:
            return [r["id"] for r in db.execute("SELECT id FROM runs WHERE status IN ('queued','running')")]

    def update_run(self, run_id: str, **fields):
        allowed = {"status", "stage", "error", "candidates"}
        if not set(fields) <= allowed:
            raise ValueError("Unsupported run field")
        if "candidates" in fields:
            fields["candidates"] = json.dumps(fields["candidates"])
        fields["updated_at"] = utcnow()
        assignment = ",".join(f"{key}=?" for key in fields)
        with self._db() as db:
            db.execute(f"UPDATE runs SET {assignment} WHERE id=?", (*fields.values(), run_id))

    def update_stage(self, run_id: str, name: str, status: str, artifacts: list[str] | None = None, error: str | None = None):
        now = utcnow()
        with self._db() as db:
            if status == "running":
                db.execute("UPDATE stages SET status=?,attempts=attempts+1,started_at=?,finished_at=NULL,error=NULL WHERE run_id=? AND name=?", (status, now, run_id, name))
            else:
                db.execute("UPDATE stages SET status=?,finished_at=?,artifact_ids=?,error=? WHERE run_id=? AND name=?", (status, now, json.dumps(artifacts or []), error, run_id, name))

    def idempotent(self, run_id: str, action: str, key: str) -> bool:
        with self._db() as db:
            cur = db.execute("INSERT OR IGNORE INTO idempotency VALUES (?,?,?)", (run_id, action, key))
            return cur.rowcount == 1

    def has_idempotency_key(self, run_id: str, action: str, key: str) -> bool:
        with self._db() as db:
            return db.execute("SELECT 1 FROM idempotency WHERE run_id=? AND action=? AND key=?", (run_id, action, key)).fetchone() is not None

    def log_event(self, run_id: str, stage: str, tool: str, status: str, latency_ms: int, error_code: str | None = None):
        with self._db() as db:
            db.execute("INSERT INTO events(run_id,stage,tool,status,latency_ms,error_code,created_at) VALUES (?,?,?,?,?,?,?)", (run_id, stage, tool, status, latency_ms, error_code, utcnow()))

    def path(self, run_id: str, name: str) -> Path:
        if "/" in name or "\\" in name or name.startswith(".") or name not in {"00_company.json", "01_research.json", "01_sources.json", "01_search_results.json", "02_facts.json", "02_metrics.json", "02_analysis.json", "03_report_draft.json", "03_writing_validation.json", "01_evidence_review.json", "04_validation.json", "report.md", "filing.pdf", "filing.txt", "01_filing_texts.json", "revision.json"}:
            raise ValueError("Artifact path is not allowed")
        target = (self.root / run_id / name).resolve()
        if target.parent != self.root / run_id:
            raise ValueError("Artifact path escaped run directory")
        return target

    def write(self, run_id: str, name: str, data: object):
        path = self.path(run_id, name)
        content = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2)
        fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        digest = hashlib.sha256(content.encode()).hexdigest()
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO artifacts VALUES (?,?,?,?)", (run_id, name, digest, utcnow()))
        return digest

    def write_binary(self, run_id: str, name: str, content: bytes):
        if name != "filing.pdf":
            raise ValueError("Binary artifacts are restricted to PDF filings")
        path = self.path(run_id, name)
        fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        digest = hashlib.sha256(content).hexdigest()
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO artifacts VALUES (?,?,?,?)", (run_id, name, digest, utcnow()))
        return digest

    def read(self, run_id: str, name: str):
        content = self.path(run_id, name).read_text(encoding="utf-8")
        with self._db() as db:
            row = db.execute("SELECT content_hash FROM artifacts WHERE run_id=? AND name=?", (run_id, name)).fetchone()
        if row and hashlib.sha256(content.encode()).hexdigest() != row["content_hash"]:
            raise ValueError(f"Artifact checksum mismatch: {name}")
        return content if name.endswith(".md") or name.endswith(".txt") else json.loads(content)

    def exists(self, run_id: str, name: str) -> bool:
        return self.path(run_id, name).exists()

    def create_revision(self, parent_id: str, key: str, supplements: list[dict], mode: str = "complete_evidence") -> str:
        """Create a fresh run with immutable input; keep the previous report intact."""
        company = self.read(parent_id, "00_company.json") if self.exists(parent_id, "00_company.json") else None
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT run_id FROM revisions WHERE parent_id=? AND key=?", (parent_id, key)).fetchone()
            if existing:
                return existing["run_id"]
            parent = db.execute("SELECT * FROM runs WHERE id=?", (parent_id,)).fetchone()
            if not parent or parent["status"] not in {"needs_review", "succeeded", "failed"}:
                raise ValueError("仅已结束的任务可以重新分析")
            run_id, now = uuid4().hex, utcnow()
            # Persist inputs before exposing a queued run to the restart recovery loop.
            directory = self.root / run_id
            directory.mkdir()
            content = json.dumps({"parent_run_id": parent_id, "supplements": supplements, "mode": mode}, ensure_ascii=False, indent=2)
            (directory / "revision.json").write_text(content, encoding="utf-8")
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)", (run_id, parent["request"], "queued", "identity", None, "[]", now, now))
            db.executemany("INSERT INTO stages(run_id,name,status) VALUES (?,?,?)", [(run_id, name, "queued") for name in STAGES])
            db.execute("INSERT INTO artifacts VALUES (?,?,?,?)", (run_id, "revision.json", hashlib.sha256(content.encode()).hexdigest(), now))
            if company:
                company_content = json.dumps(company, ensure_ascii=False, indent=2)
                (directory / "00_company.json").write_text(company_content, encoding="utf-8")
                db.execute("INSERT INTO artifacts VALUES (?,?,?,?)", (run_id, "00_company.json", hashlib.sha256(company_content.encode()).hexdigest(), now))
                db.execute("UPDATE stages SET status='succeeded',finished_at=?,artifact_ids=? WHERE run_id=? AND name='identity'", (now, '["00_company.json"]', run_id))
            db.execute("INSERT INTO revisions VALUES (?,?,?)", (parent_id, key, run_id))
            return run_id
