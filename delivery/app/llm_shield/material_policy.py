"""Purpose and retention constraints for local source material and derived views."""
from __future__ import annotations

import math
import time
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from numbers import Real
from typing import Sequence

from .schema import Material

TEMPORARY_TTL_SECONDS = 1800


class SourcePolicyError(ValueError):
    def __init__(self, message, status=410):
        super().__init__(message)
        self.status = status


class SourceCoordinator:
    """Single-process leases. Never hold this mutex while acquiring session locks."""
    def __init__(self):
        self.lock = threading.RLock()
        self.versions = {}
        self.readers = {}
        self.writers = set()

    def version(self, key):
        with self.lock:
            return self.versions.get(key, 0)

    @contextmanager
    def use(self, versions):
        with self.lock:
            for key, expected in versions.items():
                if key in self.writers:
                    raise SourcePolicyError("材料正在更新或删除，请稍后重试", 409)
                if expected is not None and expected != self.versions.get(key, 0):
                    raise SourcePolicyError("材料版本已失效，请重新选择材料")
            snapshot = {k:self.versions.get(k, 0) for k in versions}
            for key in versions:
                self.readers[key] = self.readers.get(key, 0) + 1
        try:
            yield snapshot
        finally:
            with self.lock:
                for key in versions:
                    self.readers[key] -= 1
                    if not self.readers[key]:
                        del self.readers[key]

    @contextmanager
    def mutate(self, key):
        with self.lock:
            if self.readers.get(key) or key in self.writers:
                raise SourcePolicyError("材料正用于处理，请完成后再删除或更新", 409)
            self.writers.add(key)
            committed_version = self.versions.get(key, 0) + 1
        # Mutation reservation prevents new readers, without locking ChatStore.
        try:
            yield committed_version
        except BaseException:
            raise
        else:
            with self.lock:
                self.versions[key] = committed_version
        finally:
            with self.lock:
                self.writers.remove(key)


SOURCES = SourceCoordinator()
_SCOPES = ContextVar('material_scopes', default=())


def require_source_access():
    """Recheck at the actual side effect/commit, after potentially slow checks."""
    for materials, task in _SCOPES.get():
        denial = material_denial(materials, task)
        if denial:
            raise SourcePolicyError(denial)


@contextmanager
def material_scope(materials, task):
    materials = tuple(materials)
    versions = {}
    for m in materials:
        if m.source_key is not None:
            if m.source_key in versions and versions[m.source_key] != m.source_version:
                raise SourcePolicyError("同一材料包含不同版本，请重新选择")
            versions[m.source_key] = m.source_version
    with SOURCES.use(versions):
        token = _SCOPES.set((*_SCOPES.get(), (materials, task)))
        try:
            require_source_access()
            yield
            require_source_access()
        finally:
            _SCOPES.reset(token)


def is_expired(expires_at: object, *, now: float | None = None) -> bool:
    if expires_at is None:
        return False
    if (isinstance(expires_at, bool) or not isinstance(expires_at, Real)
            or not math.isfinite(expires_at)):
        return True
    return expires_at <= (time.time() if now is None else now)


def material_denial(materials: Sequence[Material], task: str) -> str:
    """Return a content-free reason; a user instruction cannot override metadata."""
    for material in materials:
        if (material.source_key is not None
                and material.source_version != SOURCES.version(material.source_key)):
            return "材料版本已失效，请重新选择材料"
        if is_expired(material.expires_at):
            return "材料已过保存期限，请删除或重新上传并确认用途"
        purposes = material.allowed_purposes
        if purposes is not None and (
                not isinstance(purposes, list) or not purposes
                or any(not isinstance(value, str) for value in purposes)
                or task not in purposes):
            return "材料未获准用于当前任务，请按获准用途处理或重新确认后上传"
    return ""
