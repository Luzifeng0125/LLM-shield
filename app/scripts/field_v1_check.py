# -*- coding: utf-8 -*-
"""field_v1 完整性校验 + 与各训练语料的独立性证明（scripts/field_v1_check.py）。

校验项：
  1. 偏移自洽：text[start:end] == entity.text
  2. 取值多样性：与旧人工 gold 对比
  3. 格式真实性：身份证过 GB 11643、银行卡过 Luhn、手机号真实号段、邮箱真实域名
  4. 独立性：与三类训练语料分别计算字符 n-gram 重合率
     (a) 人工 gold 训练集   (b) 旧模板训练集   (c) 自举增强集
  5. 类别与场景分布
报告写入 .workbuddy/tmp/field_v1_report.txt
"""
import json
import pathlib
import collections
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIELD = ROOT / "data" / "field_v1" / "field_v1.jsonl"
REPORT = ROOT / "data" / "field_v1" / "integrity_report.md"

OLD_GOLD = [ROOT / "data" / "gold_v3" / "gold" / f"{s}_gold.jsonl"
            for s in ("train", "validation", "test")]
CORPORA = {
    "(a) 人工 gold 训练集": [ROOT / "data" / "gold_v3" / "gold" / f"{s}_gold.jsonl"
                             for s in ("train", "validation")],
    "(b) 旧模板训练集": [ROOT / "data" / "ner_v3" / f"{s}.jsonl"
                         for s in ("train", "validation")],
    "(c) 自举增强集": [ROOT / "data" / "ner_v3b" / "train_aug300.jsonl"],
}

_buf = []


def w(line=""):
    _buf.append(line)


def rows(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def ents(r):
    if not r.get("text"):
        return []
    return r.get("annotation", {}).get("entities", r.get("entities", []))


def valid_id_card(v):
    if not re.fullmatch(r"\d{17}[\dXx]", v):
        return False
    wt = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    return "10X98765432"[sum(int(v[i]) * wt[i] for i in range(17)) % 11] == v[17].upper()


def valid_luhn(v):
    if not v.isdigit():
        return False
    tot, alt = 0, False
    for ch in reversed(v):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        tot += d
        alt = not alt
    return tot % 10 == 0


def ngrams(text, n):
    t = re.sub(r"\s+", "", text)
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))}


def main():
    field = rows(FIELD)
    old = [r for p in OLD_GOLD for r in rows(p)]

    w("=" * 72)
    w("field_v1 独立手写评测集 — 数据完整性校验报告")
    w("=" * 72)
    w()

    # ---- 1 偏移
    w("【1】偏移自洽")
    bad = [(r["id"], e) for r in field for e in ents(r)
           if r["text"][e["start"]:e["end"]] != e["text"]]
    w("    text[start:end] 与实体文本一致：%s（%d 处异常）"
      % ("通过" if not bad else "失败", len(bad)))
    for rid, e in bad[:5]:
        w("      异常 %s %r" % (rid, e))
    w()

    # ---- 2 多样性
    w("【2】取值多样性对照（旧 gold 的实体取值几乎不重复 → 说明它出自固定词表）")
    def vstats(rs, tag):
        vals = collections.defaultdict(list)
        for r in rs:
            for e in ents(r):
                vals[e["category"]].append(e.get("text") or "")
        w("   %s（%d 条）" % (tag, len(rs)))
        for c in sorted(vals):
            v = vals[c]
            w("     %-16s n=%-4d distinct=%-4d 取值复用率=%.2f"
              % (c, len(v), len(set(v)), 1 - len(set(v)) / len(v)))
        return vals
    fv = vstats(field, "field_v1 本集")
    vstats(old, "gold_v3 旧人工集")
    w()

    # ---- 3 格式真实性
    w("【3】格式真实性")
    id_ok = id_bad = bank_ok = bank_bad = 0
    pf = collections.Counter()
    for r in field:
        for e in ents(r):
            if e["category"] == "ID_CARD":
                id_ok += valid_id_card(e["text"])
                id_bad += not valid_id_card(e["text"])
            elif e["category"] == "BANK_CARD":
                bank_ok += valid_luhn(e["text"])
                bank_bad += not valid_luhn(e["text"])
            elif e["category"] == "PHONE":
                m = re.match(r"1(\d)", e["text"].replace(" ", ""))
                if m:
                    pf[m.group(1)] += 1
    w("   身份证通过 GB 11643 校验位 .... %d 通过 / %d 失败" % (id_ok, id_bad))
    w("   银行卡通过 Luhn 校验 .......... %d 通过 / %d 失败" % (bank_ok, bank_bad))
    w("   手机号号段（第二位）.......... %s" % dict(pf))

    def oldvals(cat):
        return sorted({e["text"] for r in old for e in ents(r) if e["category"] == cat})

    w("   对照 —— 旧人工集的表面特征（模型只需记住这些即可拿满分）：")
    w("     身份证前 6 位地区码取值 .... %s" % sorted({v[:6] for v in oldvals("ID_CARD")}))
    w("     银行卡前 6 位 BIN 取值 ..... %s" % sorted({v[:6] for v in oldvals("BANK_CARD")}))
    w("     手机号前 3 位号段 .......... %s"
      % sorted({v.replace(' ', '')[:3] for v in oldvals("PHONE")}))
    w("     邮箱域名取值 ............... %s" % sorted({v.split("@")[-1] for v in oldvals("EMAIL")}))
    w("     密钥前缀取值 ............... %s" % sorted({v[:12] for v in oldvals("API_KEY")}))
    w("     微信号前缀取值 ............. %s" % sorted({v[:9] for v in oldvals("WECHAT")}))
    w("     身份证取值去重后条数 ....... %d / %d"
      % (len(set(oldvals("ID_CARD"))), len(oldvals("ID_CARD"))))
    w()

    # ---- 4 独立性
    w("【4】独立性：与各类训练语料的字符 n-gram 重合率")
    w("     口径：把训练语料的 n-gram 建成集合，统计 field_v1 有多少条记录命中过集合。")
    w("     越低说明本集越不是同源生成；高重合代表模型可以靠背模板而非理解上下文得分。")
    w()
    field_texts = [r["text"] for r in field]
    old_test = rows(ROOT / "data" / "gold_v3" / "gold" / "test_gold.jsonl")
    old_test_texts = [r["text"] for r in old_test if r.get("text")]

    for tag, paths in CORPORA.items():
        texts = [r["text"] for p in paths for r in rows(p) if r.get("text")]
        w("   %s —— 语料 %d 条" % (tag, len(texts)))
        for n in (6, 8, 10, 12):
            tr = set()
            for t in texts:
                tr |= ngrams(t, n)
            hit = sum(1 for t in field_texts if ngrams(t, n) & tr)
            w("      field_v1 : %2d-gram 命中 %2d/%d 条 (%5.1f%%)"
              % (n, hit, len(field_texts), 100.0 * hit / len(field_texts)))
        n = 8
        tr = set()
        for t in texts:
            tr |= ngrams(t, n)
        hit = sum(1 for t in old_test_texts if ngrams(t, n) & tr)
        w("      [对照] 旧人工 test 集 %d 条中 %d 条命中 (%5.1f%%)"
          % (len(old_test_texts), hit, 100.0 * hit / len(old_test_texts)))
        w()

    # 残留重合的 8-gram 全部列出，供人工判断是否为通用表述
    all_train = set()
    for paths in CORPORA.values():
        for p in paths:
            for r in rows(p):
                if r.get("text"):
                    all_train |= ngrams(r["text"], 8)
    shared = collections.Counter()
    for t in field_texts:
        for g in ngrams(t, 8) & all_train:
            shared[g] += 1
    w("   残留重合的 8-gram 全量（共 %d 个）：" % len(shared))
    for g, c in shared.most_common():
        w("      %-24s x%d" % (g, c))
    w()

    # ---- 5 分布
    w("【5】分布")
    cnt = collections.Counter(e["category"] for r in field for e in ents(r))
    w("   实体 %d 个 / %d 类" % (sum(cnt.values()), len(cnt)))
    for c, v in sorted(cnt.items()):
        w("     %-16s %d" % (c, v))
    neg = sum(1 for r in field if not ents(r))
    w("   纯负例（无任何敏感实体）%d / %d 条 = %.0f%%"
      % (neg, len(field), 100.0 * neg / len(field)))
    w("   场景数 %d" % len({r["scenario"] for r in field}))
    w()

    REPORT.write_text("\n".join(_buf) + "\n", encoding="utf-8")
    sys.stdout.write("report -> %s\n" % REPORT)


if __name__ == "__main__":
    main()
