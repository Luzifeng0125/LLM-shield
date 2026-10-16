#!/usr/bin/env python
"""命令行演示：调用本地服务跑一次完整流程。

用途：
  1) 不打开浏览器也能验证端到端链路；
  2) 演示「同一份材料 + 不同接收方」的对照效果；
  3) 可直接观察模型实际收到的文本与三边界判定。

运行（需先启动服务 python run.py）：
    python scripts/demo_api.py
    python scripts/demo_api.py --url http://127.0.0.1:8787 --task meeting_minutes
"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from typing import Any, Dict

DEFAULT_URL = "http://127.0.0.1:8787"


def post(url: str, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    req = urllib.request.Request(
        url + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get(url: str, path: str) -> Dict[str, Any]:
    with urllib.request.urlopen(url + path, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def line(title: str = "", ch: str = "=", n: int = 64) -> None:
    if title:
        print(f"\n{ch * 6} {title} {ch * max(0, n - len(title) - 8)}")
    else:
        print(ch * n)


def show_result(r: Dict[str, Any]) -> None:
    if not r.get("access_ok"):
        print(f"  [访问被拒] {r.get('access_reason')}")
        return

    line("识别结果（模块 ②）")
    cats: Dict[str, int] = {}
    for s in r.get("spans", []):
        cats[s["category"]] = cats.get(s["category"], 0) + 1
    print(f"  命中 {len(r.get('spans', []))} 处："
          + "、".join(f"{k}×{v}" for k, v in sorted(cats.items())))

    line("决策分布（模块 ③④）")
    acts: Dict[str, int] = {}
    for d in r.get("decisions", []):
        acts[d["action"]] = acts.get(d["action"], 0) + 1
    print("  " + "、".join(f"{k}×{v}" for k, v in sorted(acts.items())))

    line("边界1 模型实际收到的文本")
    print("  " + (r.get("sanitized_text") or "").replace("\n", "\n  ")[:1200])

    if r.get("model_output"):
        line("模型输出")
        print("  " + r["model_output"].replace("\n", "\n  ")[:1200])

    line("三边界观测（模块 ⑧）")
    for b in r.get("boundaries", []):
        status = "拦截" if b["blocked"] else (
            "泄露" if b.get("leaked_categories") else "通过")
        print(f"  {b['boundary']:<16} {b['recipient']:<22} {status}"
              f"  {b.get('blocked_reason') or ''}")

    if r.get("aggregates"):
        line("本地聚合（明细未上传）")
        print(f"  {r['aggregates'].get('summary_text')}")

    if r.get("mapping_table"):
        line("代号映射（仅内存）")
        print("  " + "、".join(f"{k}→{v}" for k, v in r["mapping_table"].items()))

    t = r.get("timings", {})
    line("耗时")
    print(f"  识别 {t.get('detect_ms', 0):.1f}ms | 决策 {t.get('decide_ms', 0):.1f}ms "
          f"| 转换 {t.get('transform_ms', 0):.1f}ms | 总计 {t.get('total_ms', 0):.0f}ms")

    if r.get("warnings"):
        line("提示")
        for w in r["warnings"]:
            print(f"  · {w}")


def main() -> int:
    ap = argparse.ArgumentParser(description="隐盾 API 命令行演示")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--task", default="meeting_minutes",
                    choices=["activity_stats", "meeting_minutes", "project_intro"])
    ap.add_argument("--identity", default="student_leader")
    ap.add_argument("--recipient", default="external_model")
    ap.add_argument("--doc", default="meeting_minutes")
    ap.add_argument("--no-model", action="store_true", help="不调用云端大模型")
    args = ap.parse_args()

    cfg = get(args.url, "/api/config")
    print(f"连接到 {args.url}")
    m = cfg.get("models", {})
    print(f"  必要性模型: {m.get('necessity_backend')} | "
          f"NER: {'RoBERTa-campus' if m.get('campus_ner', {}).get('available') else '规则底座'} | "
          f"大模型: {m.get('llm', {}).get('model')} (mode={m.get('llm', {}).get('mode')}, "
          f"has_key={m.get('llm', {}).get('has_key')})")

    payload = {
        "session_id": "cli-demo",
        "identity": args.identity,
        "task": args.task,
        "recipient": args.recipient,
        "doc_ids": [args.doc],
        "send_model": not args.no_model,
    }

    try:
        r = post(args.url, "/api/run", payload)
    except urllib.error.HTTPError as e:
        print(f"请求失败 {e.code}: {e.read().decode('utf-8', 'ignore')}")
        return 1

    line(f"任务={args.task} 身份={args.identity} 接收方={args.recipient}")
    show_result(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
