"""Deterministic source races; no sleeps, external calls or real private inputs."""
import threading
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from llm_shield import chat, material_policy, pipeline, server
from llm_shield.m1_access import file_loader, loader
from llm_shield.m2_detect.pipeline import build_detectors
from llm_shield.m7_egress import gateway
from llm_shield.schema import Material, ShieldRequest


@pytest.fixture
def sources(tmp_path, monkeypatch):
    monkeypatch.setattr(file_loader, 'UPLOAD_DIR', tmp_path)
    monkeypatch.setattr(loader, 'UPLOAD_DIR', tmp_path)
    monkeypatch.setattr(server, 'STORE', chat.ChatStore())
    return tmp_path


def stub_chat(monkeypatch):
    monkeypatch.setattr(chat, 'get_model', lambda: SimpleNamespace(available=True))
    monkeypatch.setattr(chat, 'build_detectors', lambda: build_detectors(use_gliner=False))
    monkeypatch.setattr(chat, 'necessity_scorer', lambda *a, **k: {'DELETE': 1.0})


def test_first_turn_holds_source_before_any_session_policy_commit(sources, monkeypatch):
    file_loader.save_upload(Material('first', 'uploaded', '', '整理校园讲座主题。'))
    stub_chat(monkeypatch)
    entered, resume = threading.Event(), threading.Event()
    def generate(messages):
        entered.set()
        assert resume.wait(10)
        return {'text': '请补充公开的讲座要点。', 'engine': 'mock', 'error': ''}
    monkeypatch.setattr(gateway, 'chat_messages_with_fallback', generate)
    client = TestClient(server.app)
    session = server.STORE.create('student_leader', 'meeting_minutes')
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.post, f'/api/chat/{session.session_id}/messages',
                              json={'doc_ids':['first']})
        try:
            assert entered.wait(10)
            deletion = client.delete('/api/upload/first')
        finally:
            resume.set()
        assert pending.result(timeout=10).json()['ok']
    assert deletion.status_code == 409
    assert (sources/'first.json').exists()
    assert client.delete('/api/upload/first').json()['ok']
    assert not session.active and not session.messages


def test_deleted_loaded_snapshot_cannot_be_used_for_a_first_turn(sources, monkeypatch):
    file_loader.save_upload(Material('old', 'uploaded', '', '校园活动介绍。'))
    loaded = loader.load_material('old')
    assert file_loader.delete_upload('old')
    stub_chat(monkeypatch)
    monkeypatch.setattr(gateway, 'chat_messages_with_fallback', lambda *a: pytest.fail('deleted source sent'))
    session = chat.ChatStore().create('student_leader', 'meeting_minutes')
    assert chat.send_turn(session, [loaded])['paused']
    assert not session.messages


def test_expiry_during_input_precheck_blocks_the_actual_external_call(sources, monkeypatch):
    clock = [100.]
    monkeypatch.setattr(material_policy.time, 'time', lambda: clock[0])
    file_loader.save_upload(Material('expiry', 'uploaded', '', '校园活动介绍。', expires_at=110.))
    source = loader.load_material('expiry')
    stub_chat(monkeypatch)
    original = gateway.EgressGateway.precheck
    def precheck(self, *a, **k):
        result = original(self, *a, **k)
        clock[0] = 111.
        return result
    monkeypatch.setattr(gateway.EgressGateway, 'precheck', precheck)
    monkeypatch.setattr(gateway, 'chat_messages_with_fallback', lambda *a: pytest.fail('expired source sent'))
    session = chat.ChatStore().create('student_leader', 'meeting_minutes')
    result = chat.send_turn(session, [source])
    assert result['paused'] and not session.messages


def test_expiry_during_generation_does_not_commit_reply_or_private_state(sources, monkeypatch):
    clock = [100.]
    monkeypatch.setattr(material_policy.time, 'time', lambda: clock[0])
    file_loader.save_upload(Material('expiry-output', 'uploaded', '', '校园活动介绍。', expires_at=110.))
    source = loader.load_material('expiry-output')
    stub_chat(monkeypatch)
    def generate(messages):
        clock[0] = 111.
        return {'text': '已经过期的派生回答。', 'engine': 'mock', 'error': ''}
    monkeypatch.setattr(gateway, 'chat_messages_with_fallback', generate)
    session = chat.ChatStore().create('student_leader', 'meeting_minutes')
    result = chat.send_turn(session, [source])
    assert result['paused'] and '已经过期' not in str(result)
    assert not session.messages and not session.private_spans and not session.material_policies


def test_replacing_source_rejects_stale_copy_and_keeps_fresh_copy(sources, monkeypatch):
    file_loader.save_upload(Material('version', 'uploaded', '', '第一版校园说明。'))
    old = loader.load_material('version')
    file_loader.save_upload(Material('version', 'uploaded', '', '第二版校园说明。'))
    fresh = loader.load_material('version')
    stub_chat(monkeypatch)
    calls = []
    monkeypatch.setattr(gateway, 'chat_messages_with_fallback', lambda m: (calls.append(m) or
        {'text':'请补充公开要点。','engine':'mock','error':''}))
    store = chat.ChatStore()
    assert chat.send_turn(store.create('student_leader','meeting_minutes'),[old])['paused']
    assert chat.send_turn(store.create('student_leader','meeting_minutes'),[fresh])['ok']
    assert len(calls) == 1


def test_pipeline_expiry_after_generation_cannot_reach_viewer_or_tool(sources, monkeypatch):
    clock = [100.]
    monkeypatch.setattr(material_policy.time, 'time', lambda: clock[0])
    file_loader.save_upload(Material('pipeline-expiry','uploaded','','校园公开活动说明。',expires_at=110.))
    source = loader.load_material('pipeline-expiry')
    monkeypatch.setattr(pipeline,'get_model',lambda:SimpleNamespace(available=True))
    monkeypatch.setattr(pipeline,'build_detectors',lambda:build_detectors(use_gliner=False))
    def generate(*a):
        clock[0] = 111.
        return {'text':'过期后不能展示的派生内容。','engine':'mock','error':''}
    monkeypatch.setattr(gateway,'chat_with_fallback',generate)
    monkeypatch.setattr(gateway.EgressGateway,'send_to_viewer',lambda *a,**k:pytest.fail('expired viewer output'))
    monkeypatch.setattr(gateway.EgressGateway,'send_to_tool',lambda *a,**k:pytest.fail('expired tool output'))
    result = pipeline.run_pipeline(ShieldRequest('test','student_leader','meeting_minutes','external_model',[source]))
    assert result.paused and '过期后不能展示' not in str(result.to_dict())
    assert file_loader.delete_upload('pipeline-expiry')  # lease was released on failure


def test_preview_holds_source_until_analysis_finishes(sources, monkeypatch):
    file_loader.save_upload(Material('preview','uploaded','','校园公开材料。'))
    source = loader.load_material('preview')
    monkeypatch.setattr(pipeline,'get_model',lambda:SimpleNamespace(available=True))
    def detectors():
        with pytest.raises(material_policy.SourcePolicyError) as exc:
            file_loader.delete_upload('preview')
        assert exc.value.status == 409
        return build_detectors(use_gliner=False)
    monkeypatch.setattr(pipeline,'build_detectors',detectors)
    result = pipeline.preview_only(ShieldRequest('test','student_leader','meeting_minutes','external_model',[source]))
    assert not result.paused
    assert file_loader.delete_upload('preview')


def test_cleanup_skips_busy_expired_file_and_retries_after_scope(sources, monkeypatch):
    clock = [100.]
    monkeypatch.setattr(material_policy.time,'time',lambda:clock[0])
    file_loader.save_upload(Material('cleanup','uploaded','','合成材料',expires_at=110.,storage_mode='temporary'))
    source = loader.load_material('cleanup')
    with pytest.raises(material_policy.SourcePolicyError):
        with material_policy.material_scope([source],'meeting_minutes'):
            clock[0] = 111.
            assert file_loader.cleanup_expired_uploads() == 0
    assert file_loader.cleanup_expired_uploads() == 1


def test_save_snapshot_keeps_its_own_version_when_next_writer_wins_immediately(sources, monkeypatch):
    original = material_policy.SOURCES.mutate
    race = [True]
    @contextmanager
    def immediately_replaced(key):
        with original(key) as committed_version:
            yield committed_version
        if race[0]:
            race[0] = False
            file_loader.save_upload(Material('race-version','uploaded','','较新版本。'))
    monkeypatch.setattr(material_policy.SOURCES,'mutate',immediately_replaced)
    old = Material('race-version','uploaded','','较旧版本。')
    file_loader.save_upload(old)
    fresh = loader.load_material('race-version')
    assert old.source_version != fresh.source_version
    assert material_policy.material_denial([old],'meeting_minutes')
    assert not material_policy.material_denial([fresh],'meeting_minutes')
