from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from llm_shield import workflows
from llm_shield.server import app
from llm_shield.workflow_store import WorkflowStore


@pytest.fixture
def project_api(monkeypatch, tmp_path):
    token = "owner-for-test-only-xxyyzz-123456789"
    monkeypatch.setenv("SHIELD_WORKFLOW_ADMIN_TOKEN", token)
    monkeypatch.setattr(workflows, "STORE", WorkflowStore(tmp_path / "workflows.sqlite3"))
    http = TestClient(app)
    root = "/api/workflows"
    admin = {"Authorization": f"Bearer {token}"}
    response = http.post(root + "/projects", headers=admin)
    assert response.status_code == 201
    project_url = root + "/projects/" + response.json()["project_id"]
    return http, root, project_url, admin


def test_surrogate_verification_scope_and_revocation(project_api, monkeypatch):
    http, root, url, admin = project_api
    assert http.post(root + "/projects").status_code == 401
    body = {
        "resources": [{"label": "仅本机的甲室", "capacity": 2}, {"label": "仅本机的乙室", "capacity": 1}],
        "assignments": [
            {"subject": "虚构人员甲", "eligible": [0]},
            {"subject": "虚构人员乙", "eligible": [0]},
            {"subject": "虚构人员丙", "eligible": [0, 1]},
        ],
    }
    response = http.post(url + "/assignments", json=body, headers=admin)
    assert response.status_code == 201
    assert "虚构人员" not in response.text and "仅本机" not in response.text
    data = response.json()
    assignment = url + "/assignments/" + data["assignment_id"]
    solution = data["local_solution"]
    invalid = {"placements": [solution["placements"][0]] * 3}
    assert http.post(assignment + "/verify", json=invalid, headers=admin).status_code == 422
    expected = {"虚构人员甲": "仅本机的甲室", "虚构人员乙": "仅本机的甲室", "虚构人员丙": "仅本机的乙室"}
    valid = http.post(assignment + "/verify", json=solution, headers=admin).json()
    assert {r["subject"]: r["resource"] for r in valid["placements"]} == expected
    calls = []

    def vendor(_, task_key, content, identity):
        calls.append((task_key, content, identity))
        return {"allowed": True, "text": '[[0,0]]'}

    monkeypatch.setenv("LLM_MODE", "real")
    monkeypatch.setattr(workflows.EgressGateway, "send_to_model", vendor)
    candidate = assignment + "/propose"
    assert http.post(candidate, json={}, headers=admin).status_code == 422
    assert not calls
    rejected = http.post(candidate, json={"confirm_structure_disclosure": True}, headers=admin)
    assert rejected.status_code == 422
    (task, content, _), = calls
    assert task == "assignment_planning"
    assert "虚构人员" not in content and "仅本机" not in content
    other = http.post(root + "/projects", headers=admin).json()["project_id"]
    cross = root + f"/projects/{other}/assignments/{data['assignment_id']}/verify"
    assert http.post(cross, json=solution, headers=admin).status_code == 404
    assert http.delete(assignment, headers=admin).status_code == 200
    assert http.post(assignment + "/verify", json=solution, headers=admin).status_code == 404


def test_checkin_binding_retries_and_supplier_replacement(project_api, monkeypatch):
    http, root, url, admin = project_api
    issued = [http.post(url + "/suppliers", headers=admin).json() for _ in range(2)]
    paths = [url + "/suppliers/" + supplier["supplier_id"] for supplier in issued]
    headers = [{"Authorization": "Bearer " + supplier["supplier_token"]} for supplier in issued]

    def issue(supplier, subject):
        return http.post(paths[supplier] + "/passes", headers=admin, json={
            "subject_key": subject, "ttl_seconds": 60,
        }).json()["pass_token"]

    def submit(supplier, token, event):
        return http.post(root + "/check-ins", headers=headers[supplier], json={
            "pass_token": token, "event_id": event,
        })

    token = issue(0, "internal-1")
    event = str(uuid4())
    assert submit(1, token, event).status_code == 403
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda e: submit(0, token, e), [event, str(uuid4())]))
    assert sorted(r.status_code for r in results) == [200, 403]
    successful_event = results[0].request.content if results[0].status_code == 200 else results[1].request.content
    retry = http.post(root + "/check-ins", headers={**headers[0], "Content-Type": "application/json"},
                      content=successful_event)
    assert retry.json() == {"checked_in": True}
    assert submit(1, issue(1, "internal-1"), str(uuid4())).status_code == 403
    expired = issue(1, "internal-expired")
    from llm_shield import workflow_store
    now = workflow_store.time.time()
    with monkeypatch.context() as patch:
        patch.setattr(workflow_store.time, "time", lambda: now + 61)
        assert submit(1, expired, str(uuid4())).status_code == 403
    old = issue(0, "internal-2")
    assert http.delete(paths[0], headers=admin).status_code == 200
    assert submit(0, old, str(uuid4())).status_code == 403
    assert submit(1, issue(1, "internal-2"), str(uuid4())).json() == {"checked_in": True}
    assert http.get(url + "/check-ins/summary", headers=admin).json() == {"checked_in_count": 2}


def test_private_acceptance_has_no_row_output_and_freezes_versions(project_api):
    http, _, url, admin = project_api
    private_case = {"rows": [{"team": "match", "notes": "private-example"}] * 2
                    + [{"team": "other"}], "expected": 2}
    suite = {"cases": [private_case] * 8, "max_candidates": 1}
    key = http.post(url + "/benchmarks", json=suite, headers=admin).json()["benchmark_id"]
    bench = url + "/benchmarks/" + key
    candidate = {"name": "supplier-A", "version": "1", "quoted_cents_per_task": 200,
                 "spec": {"operation": "count_equal", "field": "team", "value": "match"}}
    endpoint = bench + "/candidates"
    assert http.post(endpoint, json=candidate).status_code == 401
    assert http.post(endpoint, headers=admin, json={**candidate, "spec": {"operation": "exec"}}).status_code == 422
    report = http.post(endpoint, headers=admin, json=candidate).json()
    assert report["passed"] == report["total"] == 8
    assert report == http.post(endpoint, headers=admin, json=candidate).json()
    assert http.post(endpoint, headers=admin, json={**candidate, "quoted_cents_per_task": 201}).status_code == 409
    assert http.post(endpoint, headers=admin, json={**candidate, "version": "2"}).status_code == 409
    summary = http.get(bench + "/report", headers=admin)
    assert summary.json() == {"reports": [report]}
    assert "private-example" not in summary.text
    assert http.delete(url, headers=admin).status_code == 200
    assert http.get(bench + "/report", headers=admin).status_code == 404
