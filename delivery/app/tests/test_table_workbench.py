import csv
import io

from fastapi.testclient import TestClient

from llm_shield.m1_access import file_loader, loader
from llm_shield.server import app


def test_workbench_from_upload_through_export_and_revocation(monkeypatch, tmp_path):
    monkeypatch.setattr(file_loader, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(loader, "UPLOAD_DIR", tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50123))
    assert client.get("/workbench").status_code == 200

    def upload(text, task="activity_stats"):
        response = client.post("/api/upload", files={"file": ("sheet.csv", text.encode(), "text/csv")},
                               data={"task": task})
        assert response.status_code == 200, response.text
        return response.json()["doc_id"]

    def schema(doc_id):
        return client.post("/api/workbench/source", json={
            "identity": "student_leader", "source": {"doc_id": doc_id}})

    def source(doc_id):
        response = schema(doc_id)
        assert response.status_code == 200, response.text
        return {"doc_id": doc_id, "version": response.json()["version"]}

    people = upload("学号,专业,职责\n001,网络空间安全,学员\n001,网络空间安全,学员\n"
                    "002,网络空间安全,助教\n003,网络空间安全,学员\n004,密码科学与技术,学员\n")
    buses = upload("编号,车辆\n001,甲车\n002,乙车\n003,=1+1\n")
    query = {
        "identity": "student_leader", "source": source(people),
        "join": {"source": source(buses), "left_column": "学号", "right_column": "编号"},
        "conditions": [{"column": "专业", "op": "eq", "value": "网络空间安全"},
                       {"column": "职责", "op": "ne", "value": "助教"}],
        "group_by": "关联表 · 车辆", "distinct_by": "学号",
    }
    response = client.post("/api/workbench/query", json=query)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "source_rows": 5, "joined_rows": 4, "unmatched_rows": 1, "matched_rows": 3,
        "missing_keys": 0, "total": 2, "mode": "distinct",
        "groups": [{"value": "=1+1", "count": 1}, {"value": "甲车", "count": 1}],
    }

    response = client.post("/api/workbench/export", json=query)
    assert response.status_code == 200
    assert ["'=1+1", "1"] in list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    xlsx = client.post("/api/workbench/export?format=xlsx", json=query)
    assert xlsx.status_code == 200
    from openpyxl import load_workbook

    with io.BytesIO(xlsx.content) as stream:
        workbook = load_workbook(stream)
        try:
            groups = [cell for cell in workbook["统计汇总"]["A"] if cell.value == "=1+1"]
            assert len(groups) == 1 and groups[0].data_type == "s"
            criteria = list(workbook["来源与口径"].values)
            assert ("等于", "专业", "网络空间安全") in criteria
        finally:
            workbook.close()

    duplicate = upload("编号,车辆\n001,甲车\n００１,乙车\n")
    duplicate_query = query | {"join": query["join"] | {"source": source(duplicate)}}
    assert client.post("/api/workbench/query", json=duplicate_query).status_code == 422
    other_purpose = upload("编号,车辆\n001,甲车\n", "meeting_minutes")
    assert schema(other_purpose).status_code == 410
    stale = query | {"source": {"doc_id": people, "version": "0" * 64}}
    assert client.post("/api/workbench/export", json=stale).status_code == 409
    assert client.delete(f"/api/upload/{buses}").status_code == 200
    assert client.post("/api/workbench/export", json=query).status_code == 404


def test_workbench_rejects_nonlocal_client():
    client = TestClient(app, base_url="http://127.0.0.1", client=("192.0.2.1", 50123))
    response = client.post("/api/workbench/source", json={
        "identity": "student_leader", "source": {"doc_id": "test"}})
    assert response.status_code == 403


def test_tabular_upload_rejects_lossy_csv_headers(monkeypatch, tmp_path):
    monkeypatch.setattr(file_loader, "UPLOAD_DIR", tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50123))
    for content in ("field,field\none,two\n", "field\none,two\n"):
        result = client.post("/api/upload", files={"file": ("sheet.csv", content, "text/csv")},
                             data={"task": "activity_stats"})
        assert result.status_code == 400, result.text
    assert not list(tmp_path.iterdir())
