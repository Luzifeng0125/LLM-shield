#!/usr/bin/env python
"""★ 敏感实体识别微调（BIO 序列标注）—— 模块 ② 的第二步。

输入：合成案例的 gold_spans（data/generated/cases_dev.jsonl）自动转成 BIO 标注，
     无需人工逐条标注；有人工标注时可放到 data/annotated/ 下覆盖。

基座：默认用上一步产出的 models/roberta_campus（领域继续预训练后的 RoBERTa），
     未训练时自动回退到 hfl/chinese-roberta-wwm-ext。

运行（RTX 4060 8GB，约 5-15 分钟）：
  python -m llm_shield.m2_detect.pretrain.finetune_ner --epochs 4 --batch-size 16

产出：models/campus_ner/  —— 放置后 CampusNERDetector 会自动加载并接管识别
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Tuple

from ...config import DATA_DIR, ROOT
from . import resolve_base_model

OUT_DIR = ROOT / "models" / "campus_ner"
DEFAULT_BASE = str(ROOT / "models" / "roberta_campus")
FALLBACK_BASE = "hfl/chinese-roberta-wwm-ext"

# 内部类别 -> BIO 标签名（需与 campus_ner.py 的 LABEL_TO_CATEGORY 对应）
CAT_TO_LABEL = {
    "PERSON_NAME": "NAME", "ORG": "ORG", "LOCATION": "LOC", "PHONE": "PHONE",
    "EMAIL": "EMAIL", "STUDENT_ID": "SID", "DORM": "DORM", "BUDGET": "BUDGET",
    "WECHAT": "WECHAT", "GRADE": "GRADE", "ID_CARD": "ID",
    "BANK_CARD": "ID", "SENSITIVE_ATTR": "ATTR", "API_KEY": "ATTR",
}

LABELS = ["O"]
for _lab in dict.fromkeys(CAT_TO_LABEL.values()):
    LABELS += [f"B-{_lab}", f"I-{_lab}"]
LABEL2ID = {l: i for i, l in enumerate(LABELS)}
ID2LABEL = {i: l for l, i in LABEL2ID.items()}


def build_bio(text: str, spans: List[dict]) -> Tuple[List[str], List[str]]:
    """把字符级 gold 片段转成 BIO 标签序列。"""
    tags = ["O"] * len(text)
    for s in spans:
        cat = s.get("category")
        lab = CAT_TO_LABEL.get(cat)
        if not lab:
            continue
        start, end = int(s["start"]), int(s["end"])
        if start >= len(text):
            continue
        end = min(end, len(text))
        for i in range(start, end):
            tags[i] = f"B-{lab}" if i == start else f"I-{lab}"
    return list(text), tags


def load_cases() -> List[dict]:
    path = DATA_DIR / "generated" / "cases_dev.jsonl"
    if not path.exists():
        raise FileNotFoundError(
            f"未找到 {path}，请先运行：python -m llm_shield.m9_data.synthesize")
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description="敏感实体识别微调")
    ap.add_argument("--base-model", default=None, help="默认优先用 models/roberta_campus")
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--lr", type=float, default=3e-5)
    ap.add_argument("--max-length", type=int, default=256)
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args()

    try:
        import torch
        from torch.utils.data import DataLoader, Dataset
        from transformers import AutoModelForTokenClassification, AutoTokenizer
    except ImportError:
        print("缺少依赖，请先安装：pip install -r requirements-gpu.txt")
        return 1

    base = args.base_model or (DEFAULT_BASE if Path(DEFAULT_BASE).exists() else FALLBACK_BASE)
    base = resolve_base_model(base)
    print(f"基座模型: {base}")

    cases = load_cases()
    print(f"标注样本: {len(cases)} 条（由合成案例自动转换，无需人工逐条标注）")

    tokenizer = AutoTokenizer.from_pretrained(base)
    model = AutoModelForTokenClassification.from_pretrained(
        base, num_labels=len(LABELS), id2label=ID2LABEL, label2id=LABEL2ID)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"设备: {device}" + (f" ({torch.cuda.get_device_name(0)})" if device == "cuda" else ""))

    # ---- 构造训练样本（按 max_length 切窗，逐字标注）----
    features: List[dict] = []
    max_len = args.max_length
    for c in cases:
        chars, tags = build_bio(c["text"], c["gold_spans"])
        for off in range(0, len(chars), max_len - 2):
            chunk_chars = chars[off: off + max_len - 2]
            chunk_tags = tags[off: off + max_len - 2]
            if not chunk_chars:
                continue
            input_ids = [tokenizer.cls_token_id] + \
                tokenizer.convert_tokens_to_ids(chunk_chars) + [tokenizer.sep_token_id]
            label_ids = [-100] + [LABEL2ID[t] for t in chunk_tags] + [-100]
            attn = [1] * len(input_ids)
            pad = max_len - len(input_ids)
            input_ids += [tokenizer.pad_token_id] * pad
            label_ids += [-100] * pad
            attn += [0] * pad
            features.append({"input_ids": input_ids, "labels": label_ids,
                             "attention_mask": attn})

    class NERDS(Dataset):
        def __len__(self): return len(features)
        def __getitem__(self, i): return {k: torch.tensor(v) for k, v in features[i].items()}

    loader = DataLoader(NERDS(), batch_size=args.batch_size, shuffle=True)
    model.to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)

    model.train()
    for ep in range(args.epochs):
        total, nb = 0.0, 0
        for batch in loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            out = model(**batch)
            loss = out.loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            optimizer.zero_grad()
            total += loss.item(); nb += 1
        print(f"  epoch {ep+1}/{args.epochs} loss {total/max(nb,1):.4f}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out)
    tokenizer.save_pretrained(out)
    # 保存标签映射，供 CampusNERDetector 校验
    (out / "label_map.json").write_text(
        json.dumps({"id2label": ID2LABEL, "label2id": LABEL2ID}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    print(f"\n已保存 NER 模型 -> {out}")
    print("重启服务后 CampusNERDetector 会自动加载并接管识别（无需改代码）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
