"""Build a surrogate for a capacity-constrained assignment and check its solution."""

from __future__ import annotations

from collections import Counter
from secrets import SystemRandom
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Index = Annotated[int, Field(strict=True, ge=0, le=63)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Resource(Contract):
    label: Label
    capacity: int = Field(strict=True, ge=1, le=64)


class Assignment(Contract):
    subject: Label
    eligible: list[Index] = Field(min_length=1, max_length=64)


class AssignmentTask(Contract):
    resources: list[Resource] = Field(min_length=1, max_length=64)
    assignments: list[Assignment] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_references(self):
        if len({a.subject for a in self.assignments}) != len(self.assignments):
            raise ValueError("任务对象标签须唯一")
        if len({r.label for r in self.resources}) != len(self.resources):
            raise ValueError("资源标签须唯一")
        if any(i >= len(self.resources) for a in self.assignments for i in a.eligible):
            raise ValueError("资源索引超出范围")
        return self


class Placement(Contract):
    subject: Index
    resource: Index


class AssignmentSolution(Contract):
    placements: list[Placement] = Field(min_length=1, max_length=64)


def project(task: AssignmentTask) -> tuple[dict, dict]:
    """Only integer aliases, eligibility constraints and capacities leave this function as public data."""
    rng = SystemRandom()
    subjects = list(range(len(task.assignments)))
    resources = list(range(len(task.resources)))
    rng.shuffle(subjects)
    rng.shuffle(resources)
    aliases = {original: alias for alias, original in enumerate(resources)}
    public = {
        "resources": [{"id": alias, "capacity": task.resources[i].capacity}
                      for alias, i in enumerate(resources)],
        "subjects": [{"id": alias, "eligible": sorted({aliases[r] for r in task.assignments[i].eligible})}
                     for alias, i in enumerate(subjects)],
    }
    private = {"subjects": [task.assignments[i].subject for i in subjects],
               "resources": [task.resources[i].label for i in resources]}
    return public, private


def solve(public: dict) -> AssignmentSolution:
    """Compute a feasible solution by finding augmenting paths over resource slots."""
    size = len(public["subjects"])
    slots = [[] for _ in public["resources"]]
    for resource in public["resources"]:
        begin = sum(map(len, slots))
        slots[resource["id"]] = list(range(begin, begin + min(resource["capacity"], size)))
    eligible = [[slot for rid in subject["eligible"] for slot in slots[rid]]
                for subject in public["subjects"]]
    owners = {}

    def reserve(subject: int, visited: set[int]) -> bool:
        for slot in eligible[subject]:
            if slot in visited:
                continue
            visited.add(slot)
            if slot not in owners or reserve(owners[slot], visited):
                owners[slot] = subject
                return True
        return False

    for subject in range(size):
        if not reserve(subject, set()):
            raise ValueError("当前资格和容量下没有可行分配")
    slot_resources = {slot: rid for rid, group in enumerate(slots) for slot in group}
    return AssignmentSolution(placements=[
        Placement(subject=subject, resource=slot_resources[slot])
        for slot, subject in sorted(owners.items(), key=lambda item: item[1])
    ])


def restore(public: dict, private: dict, solution: AssignmentSolution) -> list[dict]:
    options = {subject["id"]: subject["eligible"] for subject in public["subjects"]}
    capacities = {resource["id"]: resource["capacity"] for resource in public["resources"]}
    placements = solution.placements
    if Counter(p.subject for p in placements) != Counter(options.keys()):
        raise ValueError("结果须对每个对象恰好分配一次")
    if any(p.resource not in options[p.subject] for p in placements):
        raise ValueError("结果包含无资格的分配")
    if any(count > capacities[rid] for rid, count in Counter(p.resource for p in placements).items()):
        raise ValueError("结果超过资源容量")
    return [{"subject": private["subjects"][p.subject], "resource": private["resources"][p.resource]}
            for p in sorted(placements, key=lambda p: p.subject)]
