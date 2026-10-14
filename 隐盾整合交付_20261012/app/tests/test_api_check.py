import httpx
import pytest

import llm_shield.api_check as diagnostic

SETTINGS = {'base_url': 'https://example.invalid/api/v1', 'api_key': 'DO-NOT-PRINT',
            'model': 'test-model', 'timeout': 10}


def test_no_connection_without_explicit_flag_or_key(monkeypatch):
    monkeypatch.setattr(diagnostic, 'OpenAICompatLLM', lambda *a: pytest.fail('Unexpected network client'))
    assert not diagnostic.check_connection(SETTINGS)['network_attempted']
    assert diagnostic.check_connection({**SETTINGS, 'api_key': ''}, connect=True)['status'] == 'missing_key'


@pytest.mark.parametrize('status', [401, 403, 404, 429, 500])
def test_only_status_is_reported_for_upstream_failure(monkeypatch, status):
    class Client:
        def __init__(self, *args): pass
        def chat_messages(self, *args, **kwargs):
            response = httpx.Response(status, request=httpx.Request('POST', SETTINGS['base_url']),
                                      text='DO-NOT-PRINT upstream private details')
            response.raise_for_status()
    monkeypatch.setattr(diagnostic, 'OpenAICompatLLM', Client)
    result = diagnostic.check_connection(SETTINGS, connect=True)
    assert result['network_attempted'] and not result['connected']
    assert result['http_status'] == status and 'DO-NOT-PRINT' not in str(result)


def test_probe_uses_only_fixed_public_text_and_omits_response(monkeypatch):
    class Client:
        def __init__(self, *args): pass
        def chat_messages(self, messages, **kwargs):
            assert messages == [{'role': 'user', 'content': '连接测试。请只回复 OK。'}]
            assert kwargs['max_tokens'] == 64
            return 'DO-NOT-PRINT'
    monkeypatch.setattr(diagnostic, 'OpenAICompatLLM', Client)
    result = diagnostic.check_connection(SETTINGS, connect=True)
    assert result['connected'] and 'DO-NOT-PRINT' not in str(result)
