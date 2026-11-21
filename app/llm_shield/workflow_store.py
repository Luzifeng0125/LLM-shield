"""Local project storage and transactional partner check-in."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import time


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS objects (
    project TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
    PRIMARY KEY(project,id)
);
CREATE TABLE IF NOT EXISTS suppliers (
    project TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    id TEXT NOT NULL, secret_hash TEXT NOT NULL UNIQUE,
    PRIMARY KEY(project,id)
);
CREATE TABLE IF NOT EXISTS passes (
    project TEXT NOT NULL, supplier TEXT NOT NULL, secret_hash TEXT NOT NULL UNIQUE,
    subject TEXT NOT NULL, expires_at INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(project,supplier) REFERENCES suppliers(project,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS checkins (
    project TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    PRIMARY KEY(project,subject)
);
CREATE TABLE IF NOT EXISTS acknowledgements (
    project TEXT NOT NULL, supplier TEXT NOT NULL, event TEXT NOT NULL,
    pass_hash TEXT NOT NULL,
    PRIMARY KEY(project,supplier,event),
    FOREIGN KEY(project,supplier) REFERENCES suppliers(project,id) ON DELETE CASCADE
);
"""


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class WorkflowStore:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA secure_delete = ON")
            db.executescript(SCHEMA)
            db.execute("BEGIN IMMEDIATE")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def create_project(db):
        project = secrets.token_hex(16)
        db.execute("INSERT INTO projects VALUES (?)", (project,))
        return project

    @staticmethod
    def put(db, project: str, kind: str, payload: dict) -> str:
        key = secrets.token_hex(16)
        db.execute("INSERT INTO objects VALUES (?,?,?,?)", (project, key, kind, json.dumps(payload)))
        return key

    @staticmethod
    def get(db, project: str, key: str, kind: str) -> dict | None:
        row = db.execute("SELECT payload FROM objects WHERE project=? AND id=? AND kind=?",
                         (project, key, kind)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def add_supplier(db, project: str) -> tuple[str, str]:
        supplier, token = secrets.token_hex(16), secrets.token_urlsafe(32)
        db.execute("INSERT INTO suppliers VALUES (?,?,?)", (project, supplier, digest(token)))
        return supplier, token

    @staticmethod
    def issue_pass(db, project: str, supplier: str, subject: str, ttl: int) -> str:
        token = secrets.token_urlsafe(32)
        db.execute("INSERT INTO passes(project,supplier,secret_hash,subject,expires_at) VALUES (?,?,?,?,?)",
                   (project, supplier, digest(token), subject, int(time.time()) + ttl))
        return token

    @staticmethod
    def check_in(db, supplier_token: str, pass_token: str, event: str) -> bool:
        issuer = db.execute("SELECT project,id FROM suppliers WHERE secret_hash=?",
                            (digest(supplier_token),)).fetchone()
        if not issuer:
            return False
        project, supplier = issuer
        pass_hash = digest(pass_token)
        previous = db.execute("SELECT pass_hash FROM acknowledgements WHERE project=? AND supplier=? AND event=?",
                              (project, supplier, event)).fetchone()
        if previous:
            return previous[0] == pass_hash
        grant = db.execute(
            "SELECT subject FROM passes WHERE project=? AND supplier=? AND secret_hash=? AND used=0 AND expires_at>?",
            (project, supplier, pass_hash, time.time())).fetchone()
        if not grant:
            return False
        result = db.execute("INSERT OR IGNORE INTO checkins VALUES (?,?)", (project, grant[0]))
        if result.rowcount != 1:
            return False
        db.execute("UPDATE passes SET used=1 WHERE secret_hash=?", (pass_hash,))
        db.execute("INSERT INTO acknowledgements VALUES (?,?,?,?)", (project, supplier, event, pass_hash))
        return True
