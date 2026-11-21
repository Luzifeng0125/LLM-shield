"""中文按字分词器 —— 修正 GLiNER 默认分词对中文的边界错位。

背景（本项目 v3 的关键发现）
---------------------------
GLiNER 默认用 transformers 的 WhitespaceTokenSplitter（正则 ``\\w+`` 分组）。
Python 3 的 ``\\w`` 是 Unicode 感知的，会把**整串连续中文**当成一个 token：

    "签字人是赵雨瑞，电话15063763788。" → ['签字人是赵雨瑞', '，', '电话15063763788', '。']

这导致实体 span 边界系统性错位：gold 里是"赵雨瑞"，模型看到的 token 却是
"签字人是赵雨瑞"，于是人名永远学不对、零样本也几乎检不出。

修复：CJK 汉字逐字切分；ASCII 字母/数字/@/./-/_ 整串保留（保证电话、邮箱、学号、
微信号等格式类仍是一个 token）；其余字符（含中文标点）单字。与 mdeberta 预训练
时的中文 char-level tokenization 一致。

实测（urchade/gliner_multi-v2.1）：换用本分词器后，零样本中文实体检测从「几乎
检不出」提升到 test 微平均 F1 0.594，微调后达 0.946。
"""
from __future__ import annotations

import re

# CJK 统一表意文字：基本区 + 扩展 A 区 + 兼容区
_CJK = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
# ASCII 连续串：字母 / 数字 / 下划线 / @ / . / -
_ASCII_RUN = r"[A-Za-z0-9_@.\-]+"

_SPLIT_RE = re.compile(rf"[{_CJK}]|{_ASCII_RUN}|\S")


class CharSplitter:
    """字符级分词器，符合 GLiNER 的 words_splitter 接口。

    ``__call__(text)`` 逐项 yield ``(token, char_start, char_end)``，
    与 GLiNER ``data_processor.words_splitter`` 的调用约定一致。
    """

    def __call__(self, text):
        for m in _SPLIT_RE.finditer(text):
            yield m.group(), m.start(), m.end()
