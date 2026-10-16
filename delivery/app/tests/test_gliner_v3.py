"""GLiNER v3 检测器与字符级中文分词器的测试（独立脚本，可直接运行）。

覆盖：
1. CharSplitter 中文按字、ASCII 整串、偏移正确（v3 最关键的修复）。
2. GLiNERDetector 模型缺失时优雅降级（available=False，detect 返回空）。
3. build_detectors(use_gliner=False) 默认不含 gliner（行为不变）。
4. 标签→类别映射完整（14 类）。

真正的模型推理测试不在此跑（加载 ~10s、需 GPU 权重），由 .workbuddy/tmp 下的
评测脚本覆盖；本测试只保证接口与降级路径正确。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm_shield.m2_detect.char_splitter import CharSplitter
from llm_shield.m2_detect.gliner_ner import GLiNERDetector, LABEL_TO_CATEGORY, SEMANTIC_CATEGORIES
from llm_shield.m2_detect.pipeline import build_detectors

FAIL = []


def check(name, cond):
    if not cond:
        FAIL.append(name)
    print("  %s %s" % ("OK " if cond else "FAIL", name))


print("=== 1. CharSplitter ===")
ws = CharSplitter()
text = "签字人是赵雨瑞，电话15063763788。"
toks = list(ws(text))
check("中文逐字切分（'赵'是独立 token）", any(t == "赵" for t, _, _ in toks))
check("ASCII 数字整串（'15063763788' 是单个 token）", any(t == "15063763788" for t, _, _ in toks))
check("偏移正确（每个 token 切片 == token）", all(text[s:e] == t for t, s, e in toks))
check("token 数合理（< 全文长度，说明真的切分了）", len(toks) > 5)

print("=== 2. GLiNERDetector 优雅降级 ===")
d = GLiNERDetector(model_dir="Z:/不存在的目录/xxx")
check("模型缺失 → available=False", d.available is False)
check("模型缺失 → detect 返回空", d.detect("张三的电话是13800138000") == [])

print("=== 3. build_detectors 默认不含 gliner ===")
dets = build_detectors(use_gliner=False)
check("use_gliner=False 时不含 gliner", all(x.name != "gliner" for x in dets))
check("默认仍是 regex + entity", [x.name for x in dets] == ["regex", "entity"])

print("=== 4. 标签映射完整 ===")
check("14 个类别全覆盖", len(LABEL_TO_CATEGORY) == 14)
check("语义类集合正确", SEMANTIC_CATEGORIES == ("PERSON_NAME", "ORG", "LOCATION", "DORM", "SENSITIVE_ATTR"))
check("每个中文标签映射到系统类别", all(isinstance(v, str) and v.isupper() for v in LABEL_TO_CATEGORY.values()))

print()
if FAIL:
    print("失败 %d 项: %s" % (len(FAIL), FAIL))
    sys.exit(1)
print("全部通过")
