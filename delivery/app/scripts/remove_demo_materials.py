#!/usr/bin/env python
"""移除内置的虚构演示材料（data/fixtures/）。

用途：如果你只想用自己的材料跑，不希望内置演示材料出现在列表里。

两种用法：
  1) 前端勾选框「显示内置虚构演示材料」—— 临时隐藏，随时可恢复（推荐）
  2) 本脚本 —— 从磁盘上真正删除，不可恢复

安全约定：
  - 默认 dry-run，只列出将被删除的文件，不实际删除；
  - 必须显式加 --yes 才执行删除；
  - 删除前自动备份到 data/fixtures_backup/，可用 --restore 还原。

运行：
    python scripts/remove_demo_materials.py              # 预览
    python scripts/remove_demo_materials.py --yes        # 真正删除（会自动备份）
    python scripts/remove_demo_materials.py --restore    # 从备份还原
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "data" / "fixtures"
BACKUP_DIR = ROOT / "data" / "fixtures_backup"


def list_fixtures() -> list[Path]:
    if not FIXTURE_DIR.exists():
        return []
    return sorted(FIXTURE_DIR.glob("*.json"))


def do_restore() -> int:
    if not BACKUP_DIR.exists() or not any(BACKUP_DIR.glob("*.json")):
        print(f"没有可还原的备份（{BACKUP_DIR} 为空或不存在）")
        return 1
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in sorted(BACKUP_DIR.glob("*.json")):
        shutil.copy2(p, FIXTURE_DIR / p.name)
        print(f"  还原 {p.name}")
        n += 1
    print(f"\n已还原 {n} 份材料 -> {FIXTURE_DIR}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="移除内置虚构演示材料")
    ap.add_argument("--yes", action="store_true",
                    help="真正执行删除（默认只预览）")
    ap.add_argument("--restore", action="store_true",
                    help="从备份还原内置材料")
    args = ap.parse_args()

    if args.restore:
        return do_restore()

    files = list_fixtures()
    if not files:
        print(f"内置材料目录为空或不存在：{FIXTURE_DIR}")
        return 0

    print(f"发现 {len(files)} 份内置虚构演示材料：")
    for p in files:
        print(f"  {p.name}  ({p.stat().st_size} bytes)")

    if not args.yes:
        print("\n[dry-run] 以上文件未被删除。真正删除请加 --yes")
        print("提示：若只是想临时隐藏，用网页上的勾选框即可，无需删除。")
        return 0

    # 删除前先备份，保证可还原
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for p in files:
        shutil.copy2(p, BACKUP_DIR / p.name)
    print(f"\n已备份到 {BACKUP_DIR}")

    for p in files:
        p.unlink()
        print(f"  已删除 {p.name}")
    print(f"\n完成。共删除 {len(files)} 份。")
    print(f"如需恢复：python scripts/remove_demo_materials.py --restore")
    return 0


if __name__ == "__main__":
    sys.exit(main())
