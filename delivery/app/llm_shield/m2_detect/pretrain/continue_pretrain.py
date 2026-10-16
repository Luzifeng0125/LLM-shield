#!/usr/bin/env python
"""★ 校园领域继续预训练（MLM）—— 模块 ② 的第一步。

思路参考 CCFBDCI2020：在哈工大中文 RoBERTa 基础上，用校园公开语料继续做掩码语言模型
预训练，得到 RoBERTa-campus，使下游敏感实体识别更适应校园表述（学号、宿舍号、社团称谓等）。

语料要求：
  - 放到 data/campus_corpus/ 目录下，*.txt，每行一段；
  - 必须是公开文本或经审核的合成材料，禁止使用真实个人信息；
  - 若目录为空，脚本会自动使用内置的合成校园语料兜底。

运行（RTX 4060 8GB，约 10-30 分钟）：
  python -m llm_shield.m2_detect.pretrain.continue_pretrain --epochs 3 --batch-size 16

产出：models/roberta_campus/
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from ...config import DATA_DIR, ROOT
from . import resolve_base_model

CORPUS_DIR = DATA_DIR / "campus_corpus"
OUT_DIR = ROOT / "models" / "roberta_campus"
BASE_MODEL = "hfl/chinese-roberta-wwm-ext"

# 内置兜底语料（合成，非真实个人信息）
FALLBACK_CORPUS = [
    "校团委志愿服务中心定于本月开展春季校园志愿服务月活动，欢迎各学院同学报名参加。",
    "学生组织负责人需在活动结束后三个工作日内提交总结材料与参与人数统计表。",
    "各社团请将本学期经费使用情况报送至学生会财务部，预算明细另行说明。",
    "会议纪要应包含会议时间、地点、参会人员、讨论事项、任务分工与完成期限。",
    "项目负责人负责整体推进，各组组长负责本组任务的落实与进度反馈。",
    "学号、宿舍号、联系方式等信息属于个人信息，未经授权不得对外提供。",
    "图书馆报告厅可容纳一百五十人，借用需提前三个工作日提交申请。",
    "本次招新共收到报名表一百二十余份，覆盖计算机学院、经济管理学院等多个院系。",
    "志愿者培训手册由实践部整理，包含服务规范、安全须知与应急流程。",
    "活动场地设在中心操场，遇雨天改为体育馆副馆，具体安排另行通知。",
    "课程小组成员需按时完成分工任务，并在截止日期前提交阶段性成果。",
    "学生活动中心三楼会议室配备投影设备，可用于社团例会与项目评审。",
    "校园二手书循环平台旨在降低教材支出，促进校内资源循环利用。",
    "对外发布的宣传材料不得包含内部预算、人员联系方式等未公开信息。",
    "各学院学生会主席参加本次联席会议，讨论下学期重点工作安排。",
    "项目结项需提交结项报告、经费决算表与成果清单，由指导老师审核。",
]


def load_corpus() -> list[str]:
    files = sorted(CORPUS_DIR.glob("*.txt"))
    lines: list[str] = []
    for f in files:
        lines += [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        print(f"[提示] {CORPUS_DIR} 下没有语料，使用内置合成语料兜底（{len(FALLBACK_CORPUS)} 段）")
        lines = FALLBACK_CORPUS
    else:
        print(f"读取语料 {len(files)} 个文件，共 {len(lines)} 段")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description="校园领域继续预训练")
    ap.add_argument("--base-model", default=BASE_MODEL)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--max-length", type=int, default=128)
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args()

    try:
        import torch
        from torch.utils.data import DataLoader, Dataset
        from transformers import (AutoModelForMaskedLM, AutoTokenizer,
                                  DataCollatorForLanguageModeling, get_linear_schedule_with_warmup)
    except ImportError:
        print("缺少依赖，请先安装：pip install -r requirements-gpu.txt")
        return 1

    corpus = load_corpus()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"设备: {device}" + (f" ({torch.cuda.get_device_name(0)})" if device == "cuda" else ""))

    base_model = resolve_base_model(args.base_model)
    print(f"基座模型: {base_model}")
    tokenizer = AutoTokenizer.from_pretrained(base_model)
    model = AutoModelForMaskedLM.from_pretrained(base_model)
    model.to(device)

    enc = tokenizer(corpus, truncation=True, padding="max_length",
                    max_length=args.max_length, return_tensors="pt")

    class MLMDS(Dataset):
        def __len__(self): return enc["input_ids"].shape[0]
        def __getitem__(self, i): return {k: v[i] for k, v in enc.items()}

    # MLM 动态掩码
    collator = DataCollatorForLanguageModeling(
        tokenizer=tokenizer, mlm=True, mlm_probability=0.15)
    loader = DataLoader(MLMDS(), batch_size=args.batch_size, shuffle=True,
                        collate_fn=collator)

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    total_steps = len(loader) * args.epochs
    scheduler = get_linear_schedule_with_warmup(
        optimizer, int(total_steps * 0.1), total_steps)

    model.train()
    step = 0
    for ep in range(args.epochs):
        total_loss, nb = 0.0, 0
        for batch in loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            out = model(**batch)
            loss = out.loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()
            total_loss += loss.item(); nb += 1; step += 1
            if step % 20 == 0:
                print(f"  epoch {ep+1} step {step}/{total_steps} loss {total_loss/nb:.4f}", end="\r")
        print(f"  epoch {ep+1}/{args.epochs} 平均 loss {total_loss/max(nb,1):.4f}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out)
    tokenizer.save_pretrained(out)
    print(f"\n已保存领域预训练模型 -> {out}")
    print("下一步：python -m llm_shield.m2_detect.pretrain.finetune_ner")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
