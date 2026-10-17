"""接口契约验证使用本机模拟 HTTP，不代表真实供应商已连通。"""
import json
import httpx
import llm_shield.m7_egress.llm_client as adapter

def configure(monkeypatch, handler, mode='real', key='test-key-not-real'):
    monkeypatch.setattr(adapter, 'llm_settings', lambda: {'mode': mode, 'api_key': key, 'base_url': 'https://example.invalid/v1', 'model': 'test-model', 'timeout': 10})
    original = httpx.Client
    monkeypatch.setattr(adapter.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))

def test_real_adapter_sends_full_messages_and_reads_only_final_content(monkeypatch):
    captured = []

    def endpoint(request):
        captured.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': '公开回答', 'reasoning_content': '内部推理'}, 'finish_reason': 'stop'}]})
    configure(monkeypatch, endpoint)
    messages = [{'role': 'system', 'content': '处理任务'}, {'role': 'user', 'content': '第一轮已脱敏材料'}, {'role': 'assistant', 'content': '已接收'}, {'role': 'user', 'content': '继续整理'}]
    result = adapter.chat_messages_with_fallback(messages)
    assert result == {'text': '公开回答', 'engine': 'real', 'error': ''}
    payload = json.loads(captured[0].content)
    assert str(captured[0].url) == 'https://example.invalid/v1/chat/completions'
    assert captured[0].headers['authorization'] == 'Bearer test-key-not-real'
    assert payload['messages'] == messages and payload['stream'] is False

def test_real_mode_without_key_does_not_send_or_fall_back(monkeypatch):

    def forbidden(request):
        raise AssertionError('No request should be sent')
    configure(monkeypatch, forbidden, key='')
    result = adapter.chat_messages_with_fallback([{'role': 'user', 'content': '公开内容'}])
    assert result['engine'] == 'error' and result['text'] == ''

def test_real_http_failure_does_not_expose_upstream_body(monkeypatch):
    configure(monkeypatch, lambda _: httpx.Response(401, json={'error': 'private-upstream-body-test-key-not-real'}))
    result = adapter.chat_messages_with_fallback([{'role': 'user', 'content': '公开内容'}])
    assert result['engine'] == 'error' and result['text'] == ''
    assert 'private-upstream' not in str(result) and 'test-key' not in str(result)

def test_reasoning_only_response_is_not_presented_as_answer(monkeypatch):
    configure(monkeypatch, lambda _: httpx.Response(200, json={'choices': [{'message': {'content': '', 'reasoning_content': '内部推理'}}]}))
    result = adapter.chat_messages_with_fallback([{'role': 'user', 'content': '公开内容'}])
    assert result['engine'] == 'error' and result['text'] == ''

def test_auto_with_key_reports_failure_instead_of_mock_reply(monkeypatch):
    configure(monkeypatch, lambda _: httpx.Response(429, json={'error': 'secret'}), mode='auto')
    result = adapter.chat_messages_with_fallback([{'role': 'user', 'content': '公开内容'}])
    assert result == {'text': '', 'engine': 'error', 'error': '真实模型请求失败（HTTP 429）'}
