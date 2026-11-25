"""实验用 HMAC。密钥不得写入仓库，示例密钥不得用于真实数据。"""
from __future__ import annotations

import hmac
import hashlib
from pathlib import Path


EXAMPLE_VAULT_KEY = "example-only-not-for-real-data"
REPO_ROOT = Path(__file__).resolve().parents[2]


class KeyPolicyError(ValueError):
    """密钥位置或用途不符合冻结方案。"""


def assert_key_outside_repo(path: Path) -> Path:
    resolved = path.resolve()
    root = REPO_ROOT.resolve()
    if resolved == root or root in resolved.parents:
        raise KeyPolicyError("vault_key 必须放在仓库外，不能从项目目录读取")
    return resolved


def vault_key_bytes(key: str, *, for_real_data: bool) -> bytes:
    if not isinstance(key, str) or not key.strip():
        raise KeyPolicyError("缺少 vault_key")
    if for_real_data and key == EXAMPLE_VAULT_KEY:
        raise KeyPolicyError("示例密钥 example-only-not-for-real-data 不得用于真实数据")
    if (not for_real_data) and key != EXAMPLE_VAULT_KEY:
        raise KeyPolicyError("夹具和单元测试只能使用示例密钥")
    return key.encode("utf-8")


def hmac_sha256_display(key: bytes, message: str) -> str:
    """返回 HMAC-SHA256 的前 16 位十六进制。完整摘要不进入注册表字段。"""
    digest = hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:16]
