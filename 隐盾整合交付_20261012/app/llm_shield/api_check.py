"""仅使用固定公开短句的连接诊断；不输出密钥、响应正文或上游异常。"""
from __future__ import annotations

import argparse
import json
import time
from urllib.parse import urlsplit

import httpx

from .config import llm_settings
from .m7_egress.llm_client import OpenAICompatLLM


def check_connection(settings: dict, *, connect: bool = False) -> dict:
    result = {'key_configured': bool(settings.get('api_key')), 'network_attempted': False,
              'connected': False, 'status': 'configuration_only'}
    url = urlsplit(settings.get('base_url', ''))
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.query or url.fragment or not settings.get('model')):
        return {**result, 'status': 'invalid_configuration'}
    if not result['key_configured']:
        return {**result, 'status': 'missing_key'}
    if not connect:
        return result
    started = time.perf_counter()
    result['network_attempted'] = True
    try:
        client = OpenAICompatLLM(settings['base_url'], settings['api_key'], settings['model'],
                                 min(float(settings.get('timeout', 30)), 30))
        reply = client.chat_messages([{'role': 'user', 'content': '连接测试。请只回复 OK。'}], max_tokens=64)
        result.update(connected=True, status='connected', response_characters=len(reply))
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        result.update(status={401: 'authentication_failed', 403: 'permission_denied',
                              404: 'endpoint_or_model_not_found', 429: 'quota_or_rate_limit'}.get(code, 'http_error'),
                      http_status=code)
    except httpx.TimeoutException:
        result['status'] = 'timeout'
    except httpx.RequestError:
        result['status'] = 'network_error'
    except Exception:
        result['status'] = 'invalid_response_or_configuration'
    result['elapsed_ms'] = round((time.perf_counter() - started) * 1000)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--connect', action='store_true', help='使用固定公开短句发起一次真实请求，可能消耗 API 额度')
    args = parser.parse_args()
    result = check_connection(llm_settings(), connect=args.connect)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['connected'] or result['status'] == 'configuration_only' else 1


if __name__ == '__main__':
    raise SystemExit(main())
