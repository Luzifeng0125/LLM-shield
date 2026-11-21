import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from llm_shield import integration_guards, integrations
from llm_shield.m7_egress import gateway
from scripts import make_release


def test_duplicate_recognizers_are_rejected():
    pattern = {"name": "one", "category": "STUDENT_ID", "regex": "JNU-[0-9]+"}
    with pytest.raises(ValueError):
        integrations.Presidio(patterns=[pattern, pattern])
    with pytest.raises(ValueError):
        integrations.Presidio(patterns=[pattern, {**pattern, "name": "two"}])
    assert len(integrations.Presidio(patterns=[pattern]).patterns) == 1


def test_native_rules_support_stage_scoped_patterns(monkeypatch):
    settings = integrations.Integrations(policies={"enabled": True, "rules": [{
        "name": "override", "stages": ["model_input"],
        "regex": r"(?i)ignore\s+all\s+previous\s+instructions"}]})
    monkeypatch.setattr(integration_guards, "load_integrations", lambda: (settings, "revision"))
    assert integration_guards.extra_denial("IGNORE  ALL PREVIOUS INSTRUCTIONS", "external_model")
    assert not integration_guards.extra_denial("公开活动", "external_model")
    assert not integration_guards.extra_denial("ignore all previous instructions", "external_model",
                                             stage="model_output")
    with pytest.raises(ValueError):
        integrations.Integrations(policies={"rules": [{"name": "bad", "stages": ["model_input"],
                                                       "regex": "["}]})


def test_boundary_policies_reach_normal_gateway(monkeypatch):
    settings = integrations.Integrations(nemo=integrations.Nemo(
        enabled=True, deny_phrases=["global"],
        boundaries={"model_output": ["output-only"], "tool_response": ["tool-only"]}))
    monkeypatch.setattr(integration_guards, "load_integrations", lambda: (settings, "revision"))
    seen = []

    def check(content, phrases):
        seen.append(phrases)
        return "blocked" if any(phrase in content for phrase in phrases) else ""

    monkeypatch.setattr(integration_guards, "boundary_denial", check)
    monkeypatch.setattr(gateway, "inspect_payload", lambda *a, **k: {"leaked": False})
    guard = gateway.EgressGateway()
    assert guard.precheck("external_model", "student_leader", "output-only",
                          task_key="meeting_minutes")["allowed"]
    assert not guard.precheck("external_model", "student_leader", "output-only",
                              task_key="meeting_minutes", guard_stage="model_output")["allowed"]
    assert not guard.precheck("egress_tool_public", "student_leader", "tool-only",
                              task_key="meeting_minutes", guard_stage="tool_response")["allowed"]
    assert seen == [("global",), ("global", "output-only"), ("global", "tool-only")]
    with pytest.raises(ValueError):
        integrations.Nemo(boundaries={"unknown": []})


def test_runtime_archive_has_manifest_without_private_or_research_files(monkeypatch, tmp_path):
    archive = tmp_path / "runtime.zip"
    monkeypatch.setattr("sys.argv", ["make_release", "--profile", "runtime", "--out", str(archive)])
    assert make_release.main() == 0
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        assert len(names) == len(set(names))
        assert "models/necessity_action.joblib" in names
        assert "scripts/start_service.py" in names
        assert ".env.example" in names and "start.cmd" in names
        assert not any(name.startswith(("data/generated/", "data/uploads/", "tests/", "outputs/")) for name in names)
        assert not any(name.startswith("llm_shield/m9_data/") for name in names)
        assert not any(Path(name).name == ".env" for name in names)
        manifest = json.loads(bundle.read("RELEASE_MANIFEST.json"))
        assert {item["path"] for item in manifest["files"]} == set(names) - {"RELEASE_MANIFEST.json"}
        for item in manifest["files"]:
            assert hashlib.sha256(bundle.read(item["path"])).hexdigest() == item["sha256"]
