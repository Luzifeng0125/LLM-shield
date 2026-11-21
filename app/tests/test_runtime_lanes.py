"""三条结果分开记录：离线规则、在线必要性模型、实际端到端。

词典测试模式只证明本地链路能跑到暂停点，不证明识别已经安全。
"""

from llm_shield.config import llm_settings
from llm_shield.m2_detect.gliner_ner import GLiNERDetector
from llm_shield.pipeline import run_pipeline
from llm_shield.schema import Material, ShieldRequest
from llm_shield.campus_v11.r0 import decide


DUTY = (
    "班级事务群，周日晚上。\n\n"
    "林知夏：本周值日我按教室排了。周一教学楼A201，周晚宁擦黑板并检查门窗；"
    "周三同一间教室，陈予安负责关门、断电和归还钥匙。\n\n"
    "周晚宁：周三我有实验，可能提前走。到时候打电话13800001001。\n\n"
    "陈予安：钥匙在我书包侧袋。邮箱是chenyuan@example.edu，人没到就发邮件。\n"
)
NOTICE = "本周五下午在学生活动中心举办招新说明会，欢迎各学院同学参加。不收集个人联系方式。"


def _request(task, text):
    return ShieldRequest(
        session_id="lane-check",
        identity="student_leader",
        task=task,
        recipient="external_model",
        materials=[Material(doc_id="doc", doc_type="uploaded", title="材料", text=text)],
        user_instruction="整理成通知，把时间和分组讲清楚。",
    )


def test_missing_gliner_keeps_the_default_pause(monkeypatch):
    monkeypatch.setenv("SHIELD_DETECTOR_MODE", "gliner")
    monkeypatch.setenv("SHIELD_USE_GLINER", "true")
    if GLiNERDetector().available:
        return
    result = run_pipeline(_request("class_coordination", DUTY))
    assert result.paused is True
    assert "GLiNER" in result.pause_reason
    assert result.model_output == ""
    assert result.sanitized_text == ""
    assert result.recognition_assurance == ""


def test_dictionary_test_runs_locally_then_pauses_before_sending(monkeypatch):
    monkeypatch.setenv("SHIELD_DETECTOR_MODE", "dictionary_test")
    result = run_pipeline(_request("class_coordination", DUTY))
    assert result.paused is True
    assert result.model_output == ""
    assert result.decision_lane == "online_necessity_model"
    assert "本地模拟" not in result.model_output
    person = [span["text"] for span in result.spans if span.get("category") == "PERSON_NAME"]
    if result.spans:
        assert "林知夏" in person and "周晚宁" in person and "陈予安" in person
        assert "关门" not in person
    for secret in ("林知夏", "周晚宁", "陈予安", "13800001001", "chenyuan@example.edu"):
        assert secret not in result.sanitized_text
        assert secret not in result.model_output
    if result.recognition_assurance == "dictionary_test_unverified":
        assert "未经验证" in result.pause_reason
    else:
        assert result.decisions
        assert any(item.get("action") == "PAUSE" for item in result.decisions)


def test_other_campus_workflows_stay_offline(monkeypatch):
    monkeypatch.setenv("SHIELD_DETECTOR_MODE", "dictionary_test")
    result = run_pipeline(_request("coursework_grades", "补交作业截止到周五。"))
    assert result.paused is True
    assert "未知任务" in result.pause_reason
    assert result.decision_lane == ""


def test_activity_notice_uses_its_own_online_task(monkeypatch):
    monkeypatch.setenv("SHIELD_DETECTOR_MODE", "dictionary_test")
    result = run_pipeline(_request("activity_notice", NOTICE))
    assert result.task == "activity_notice"
    assert "未知任务" not in result.pause_reason
    assert result.decision_lane == "online_necessity_model"
    assert result.paused is True
    assert result.model_output == ""


def test_offline_rule_is_not_the_online_lane():
    offline = decide({
        "policy_version": "campus-min-disclosure-v1.1",
        "unit_id": "u",
        "workflow_id": "class_coordination",
        "boundary_id": "external_generation",
        "recipient_id": "external_model",
        "identity_key": "student_leader",
        "task_key": None,
        "purpose_id": "duty",
        "purpose_source": "user_explicit",
        "category": "PERSON_NAME",
        "confidence": 1,
        "target_text": "周晚宁",
        "user_task": "整理这份值日安排",
        "trusted_permissions": [
            {"source_id": "config/identities.yaml", "version": "identities-v0.1"},
            {"source_id": "config/recipients.yaml", "version": "recipients-v0.1"},
            {"source_id": "config/tasks.yaml", "version": "tasks-v0.1"},
            {"source_id": "config/rules.yaml", "version": "rules-v0.1"},
        ],
    })
    assert offline["final_action"] == "PSEUDONYMIZE"
    assert "online" not in str(offline.get("rule_version"))


def test_real_mode_without_a_key_is_still_not_a_mock_call(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "real")
    monkeypatch.setenv("LLM_API_KEY", "")
    settings = llm_settings()
    has_key = bool(settings.get("api_key"))
    assert not has_key
    assert settings.get("mode") == "real"
