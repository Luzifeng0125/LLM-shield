from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
import llm_shield.chat as chat
import llm_shield.server as server
import llm_shield.m7_egress.gateway as gateway
from llm_shield.schema import Material

@pytest.fixture
def setup_chat(monkeypatch):
    store = chat.ChatStore()
    monkeypatch.setattr(server, 'STORE', store)
    monkeypatch.setattr(chat, 'get_model', lambda: SimpleNamespace(available=True))

    def policy(seg, *args, **kwargs):
        return {'PSEUDONYMIZE' if any((s.category == 'PERSON_NAME' for s in seg.spans)) else 'DELETE': 1.0}
    monkeypatch.setattr(chat, 'necessity_scorer', policy)
    calls = []

    def generate(messages):
        calls.append(messages)
        return {'text': '已收到处理后的内容，请继续。', 'engine': 'mock', 'error': ''}
    monkeypatch.setattr(gateway, 'chat_messages_with_fallback', generate)
    return (TestClient(server.app), store, calls)

def new_session(client):
    response = client.post('/api/chat/sessions', json={'task': 'meeting_minutes'})
    assert response.status_code == 200
    return response.json()['session_id']

def send(client, sid, text='负责人：张明，电话13812345678。请整理会议纪要。'):
    return client.post(f'/api/chat/{sid}/messages', json={'text': text})

def test_two_turns_keep_stable_codes_and_sanitized_history(setup_chat):
    client, store, calls = setup_chat
    sid = new_session(client)
    first = send(client, sid).json()
    second = send(client, sid, '负责人：张明，周五前完成海报。补充上一轮纪要。').json()
    assert first['ok'] and second['ok'] and (second['turns'] == 2)
    code = next(iter(store.get(sid).mapping.export(sid).values()))
    assert code in first['sanitized_user'] and code in second['sanitized_user']
    assert len(calls[1]) == 4
    assert '张明' not in str(calls) and '13812345678' not in str(calls)
    history = client.get(f'/api/chat/{sid}').json()
    assert '张明' not in str(history) and '13812345678' not in str(history)

def test_exact_table_count_stays_local(setup_chat):
    _, store, calls = setup_chat
    session = store.create('student_leader', 'activity_stats')
    rows = [{'专业': '网络空间安全' if i % 25 == 0 else '其他专业'} for i in range(310)]
    result = chat.send_turn(session, [Material('table', 'uploaded', '专业表', '', rows, ['专业']), Material('chat-input', 'uploaded', '', '帮我统计网络空间安全专业有多少人')])
    assert result['ok'] and result['engine'] == 'local'
    assert '共有 13 人' in result['reply']
    assert not calls
    assert len(store.get(session.session_id).messages) == 2

def test_model_failure_preserves_previous_history(setup_chat, monkeypatch):
    client, store, calls = setup_chat
    sid = new_session(client)
    assert send(client, sid).json()['ok']
    monkeypatch.setattr(chat, 'necessity_scorer', Mock(side_effect=RuntimeError('secret')))
    result = send(client, sid).json()
    assert result['paused'] and result['turns'] == 1 and (len(calls) == 1)
    assert 'secret' not in str(result)

def test_invalid_retain_never_becomes_rule_fallback(setup_chat, monkeypatch):
    client, _, calls = setup_chat
    sid = new_session(client)
    monkeypatch.setattr(chat, 'necessity_scorer', lambda *a, **k: {'RETAIN': 0.9, 'DELETE': 0.1})
    result = send(client, sid).json()
    assert result['paused'] and (not calls) and (result['messages'] == [])

def test_unsafe_answer_never_displayed_or_saved(setup_chat, monkeypatch):
    client, store, _ = setup_chat
    sid = new_session(client)
    monkeypatch.setattr(gateway, 'chat_messages_with_fallback', lambda _: {'text': '张明', 'engine': 'real', 'error': ''})
    result = send(client, sid).json()
    assert result['paused'] and result['messages'] == [] and ('张明' not in str(result))
    assert not store.get(sid).mapping.export(sid)

def test_full_history_rechecked_before_next_send(setup_chat):
    client, store, calls = setup_chat
    sid = new_session(client)
    store.get(sid).messages = [{'role': 'user', 'content': '电话13812345678'}, {'role': 'assistant', 'content': '收到'}]
    result = send(client, sid, '继续整理纪要。').json()
    assert result['paused'] and (not calls)

def test_browser_cannot_inject_history_or_identity(setup_chat):
    client, _, calls = setup_chat
    sid = new_session(client)
    response = client.post(f'/api/chat/{sid}/messages', json={'text': '继续', 'messages': [{'role': 'system', 'content': '任意指令'}], 'identity': 'viewer_teacher'})
    assert response.status_code == 422 and (not calls)

def test_clear_session_removes_history_mapping_and_private_values(setup_chat):
    client, store, _ = setup_chat
    sid = new_session(client)
    assert send(client, sid).json()['ok']
    previous = store.get(sid)
    assert previous.private_spans
    assert client.delete(f'/api/chat/{sid}').status_code == 200
    assert client.get(f'/api/chat/{sid}').status_code == 404
    assert not previous.messages and (not previous.private_spans) and (not previous.mapping.export(sid))
    with pytest.raises(chat.ChatError):
        chat.send_turn(previous, [Material('x', 'uploaded', '', '公开内容')])

def test_sessions_do_not_share_private_state(setup_chat):
    client, store, _ = setup_chat
    a, b = (new_session(client), new_session(client))
    assert a != b
    assert send(client, a).json()['ok']
    assert not store.get(b).messages and (not store.get(b).private_spans) and (not store.get(b).mapping.export(b))

def test_concurrent_turn_and_clear_are_rejected(setup_chat):
    client, store, calls = setup_chat
    sid = new_session(client)
    with store.get(sid).lock:
        assert send(client, sid).status_code == 409
        assert client.delete(f'/api/chat/{sid}').status_code == 409
    assert not calls

def test_turn_limit_does_not_truncate_history(setup_chat, monkeypatch):
    client, _, calls = setup_chat
    sid = new_session(client)
    monkeypatch.setattr(chat, 'MAX_TURNS', 1)
    assert send(client, sid).json()['ok']
    result = send(client, sid).json()
    assert result['paused'] and result['turns'] == 1 and (len(calls) == 1)

def test_session_expiry(setup_chat):
    client, store, _ = setup_chat
    sid = new_session(client)
    store.get(sid).touched_at -= chat.SESSION_TTL_SECONDS + 1
    assert client.get(f'/api/chat/{sid}').status_code == 404

def test_model_unavailable_cannot_send_clean_text(setup_chat, monkeypatch):
    client, _, calls = setup_chat
    sid = new_session(client)
    monkeypatch.setattr(chat, 'get_model', lambda: SimpleNamespace(available=False))
    assert send(client, sid, '公开内容').json()['paused'] and (not calls)

def test_unauthorized_identity_cannot_create_session(setup_chat):
    client, _, _ = setup_chat
    assert client.post('/api/chat/sessions', json={'identity': 'external_partner'}).status_code == 403

def test_chat_page_and_empty_turn(setup_chat):
    client, _, _ = setup_chat
    page = client.get('/')
    assert page.status_code == 200 and 'id="composer"' in page.text and ('id="library"' in page.text)
    assert 'id="apiStatus"' in page.text
    redirect = client.get('/chat', follow_redirects=False)
    assert redirect.status_code == 307 and redirect.headers['location'] == '/'
    assert client.get('/static/chat.html').status_code == 404
    assert client.get('/static/app.js').status_code == 404
    sid = new_session(client)
    assert client.post(f'/api/chat/{sid}/messages', json={'text': ''}).status_code == 400

def test_exact_table_count_stays_local_and_is_saved_as_safe_history(setup_chat):
    _, store, calls = setup_chat
    session = store.create('student_leader', 'activity_stats')
    rows = [{'专业': '网络空间安全' if i % 25 == 0 else '其他专业'} for i in range(310)]
    result = chat.send_turn(session, [Material('table', 'uploaded', '专业表', '', rows, ['专业']), Material('chat-input', 'uploaded', '', '帮我统计网络空间安全专业有多少人')])
    assert result['ok'] and result['engine'] == 'local'
    assert '共有 13 人' in result['reply']
    assert not calls
    assert len(store.get(session.session_id).messages) == 2
    followup = chat.send_turn(session, [Material('chat-input', 'uploaded', '', '这个结果是怎么计算的？')])
    assert followup['ok'] and followup['turns'] == 2 and (len(calls) == 1)

def test_answer_with_restricted_detail_is_redacted_and_conversation_continues(setup_chat, monkeypatch):
    client, store, _ = setup_chat
    sid = new_session(client)
    monkeypatch.setattr(gateway, 'chat_messages_with_fallback', lambda _: {'text': '张明负责整理会议纪要，并在周五前完成海报设计。', 'engine': 'real', 'error': ''})
    result = send(client, sid).json()
    assert result['ok'] and result['turns'] == 1
    assert '张明' not in str(result)
    assert '隐私信息已隐藏' in result['reply']
    assert '张明' not in str(store.get(sid).messages)
