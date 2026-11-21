"""Run a small, declarative candidate against buyer-provided acceptance cases."""

from __future__ import annotations

import hashlib
import json
from time import perf_counter
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .task_surrogate import Contract


Column = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,31}$")]
Cell = Annotated[str, StringConstraints(max_length=150)]


class AcceptanceCase(Contract):
    rows: list[dict[Column, Cell]] = Field(max_length=300)
    expected: int = Field(strict=True, ge=0, le=300)

    @model_validator(mode="after")
    def bound_columns(self):
        if any(len(row) > 16 for row in self.rows):
            raise ValueError("每条记录最多支持 16 个字段")
        return self


class AcceptanceSuite(Contract):
    cases: list[AcceptanceCase] = Field(min_length=8, max_length=32)
    max_candidates: int = Field(default=5, strict=True, ge=1, le=20)


class CountAll(Contract):
    operation: Literal["count_all"]


class CountEqual(Contract):
    operation: Literal["count_equal"]
    field: Column
    value: Cell


class Candidate(Contract):
    name: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,60}$")]
    version: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,60}$")]
    spec: Annotated[CountAll | CountEqual, Field(discriminator="operation")]
    quoted_cents_per_task: int | None = Field(default=None, strict=True, ge=0, le=100000000)


def manifest_digest(candidate: Candidate) -> str:
    encoded = json.dumps(candidate.model_dump(), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def evaluate(suite: AcceptanceSuite, candidate: Candidate, manifest: str) -> dict:
    start = perf_counter()
    spec = candidate.spec
    correct = 0
    for case in suite.cases:
        if isinstance(spec, CountEqual):
            if any(spec.field not in row for row in case.rows):
                continue
            actual = sum(row.get(spec.field) == spec.value for row in case.rows)
        else:
            actual = len(case.rows)
        correct += actual == case.expected
    return {
        "name": candidate.name,
        "version": candidate.version,
        "manifest_sha256": manifest,
        "passed": correct,
        "total": len(suite.cases),
        "quoted_cents_per_task": candidate.quoted_cents_per_task,
        "execution_ms": round((perf_counter() - start) * 1000, 3),
    }
