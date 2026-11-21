"""★ 弱监督标签生产：种子词 → 语义相近词查找 → 弱标签 → 自训练 → 人工复核子集。

路线参考 CCFBDCI2020 / LOTClass：
  1) 人工（法学/经管）定义各模板下的关键词种子           -> m9_data/seeds.py
  2) 用领域预训练模型在未标注校园文本中查找语义相近词      -> expand_seeds()
  3) 用扩充后的词表在未标注语料上生成弱标签               -> generate_weak_labels()
  4) 自训练迭代，筛选高置信样本加入训练                   -> self_train_rounds()
  5) 人工复核子集单独划分，不参与训练                     -> split_review_set()

本模块在「无领域模型」时自动退化为 char n-gram TF-IDF 余弦相似度查词，
保证流程可跑通；有 RoBERTa-campus 时可用其词向量替换（见 build_similarity_fn）。
"""
from __future__ import annotations

import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from ..config import DATA_DIR
from .seeds import NEGATIVE_SEEDS, seeds_for

GENERATED_DIR = DATA_DIR / "generated"


# ---------------------------------------------------------------- 语料


def default_corpus() -> List[str]:
    """默认语料：校内公开风格文本（合成，不含真实个人信息）。

    实际使用时请把校园公开文本放到 data/campus_corpus/ 下（每行一段），
    本函数会自动优先读取。
    """
    corpus_file = DATA_DIR / "campus_corpus" / "campus.txt"
    if corpus_file.exists():
        return [ln.strip() for ln in
                corpus_file.read_text(encoding="utf-8").splitlines() if ln.strip()]

    # 内置兜底语料（合成）
    return [
        "本次志愿服务活动报名人数为46人，活动名称为春季校园志愿服务月。",
        "请各位同学填写手机号与邮箱，便于后续联络。",
        "负责人李晓华需在3月22日前提交招新推文终稿。",
        "活动地点设在中心操场，参与同学请提前十分钟到场。",
        "本项目经费预算为四万元，具体支出明细另行报送。",
        "会议纪要中应保留事项、负责人与期限的对应关系。",
        "学号与身份证号属于个人标识，未经授权不得对外提供。",
        "对外介绍只包含已获准公开的事实，不涉及内部预算。",
        "各学院参与人次统计表已汇总完成，共152人次。",
        "项目负责人的联系方式仅限内部使用，不得写入对外文档。",
        "请统计各班级参加人数，并于本周五前汇总提交。",
        "会议室借用申请已提交，等待后勤处审批。",
        "学生活动中心305会议室可容纳三十人。",
        "本次活动实到人数42人，缺席4人。",
        "请填写所在学院与学号，用于学分认定。",
        "经费使用情况将在期末向全体成员公示。",
        "对接人王芳负责赞助商联络，截止日期为3月25日。",
        "平台开发涉及密钥配置，禁止提交至公开仓库。",
        "志愿者培训手册由赵磊整理，下周三前完成初稿。",
        "身份证号码属高敏感字段，须加密存储。",
        "成绩与绩点信息仅本人可见，不得在群内公布。",
        "活动总结需包含参与人数、活动类别与主要成效。",
        "宿舍号与家庭住址属于隐私信息，不得公开。",
        "项目简介可对外发布，包含项目名称与建设目标。",
        "请各组长确认本组成员名单，并核对联系方式。",
        "本次招新共收到报名表128份，较去年增长两成。",
        "预算金额属于内部信息，未经审批不得披露。",
        "会议决定由陈静负责报名人数汇总，本周内提交。",
        "微信号与QQ号不得出现在对外宣传物料中。",
        "公开信息清单已由指导老师审核通过。",
    ]


# ---------------------------------------------------------------- 语义相近词查找


def _char_ngrams(word: str, n: int = 2) -> set:
    if len(word) < n:
        return {word}
    return {word[i:i + n] for i in range(len(word) - n + 1)}


def _jaccard(a: str, b: str, n: int = 2) -> float:
    sa, sb = _char_ngrams(a, n), _char_ngrams(b, n)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def build_similarity_fn(corpus: List[str]) -> Callable[[str, str], float]:
    """构建词相似度函数。

    有领域模型时可在此替换为 RoBERTa-campus 的词向量余弦相似度；
    当前实现用「字符 n-gram 相似度 + 语料共现分布相似度」的加权组合。
    """
    # 统计每个词在哪些句子中出现（共现分布）
    doc_freq: Dict[str, set] = defaultdict(set)
    vocab: Counter = Counter()
    for i, sent in enumerate(corpus):
        for w in set(_tokenize_cn(sent)):
            doc_freq[w].add(i)
            vocab[w] += 1

    def sim(a: str, b: str) -> float:
        surface = _jaccard(a, b)
        da, db = doc_freq.get(a, set()), doc_freq.get(b, set())
        if da and db:
            dist = len(da & db) / len(da | db)
        else:
            dist = 0.0
        return 0.65 * surface + 0.35 * dist

    return sim


def _tokenize_cn(text: str) -> List[str]:
    """极简中文切词：按标点切句后取 2~4 字滑窗词（够用于相似度查词）。"""
    import re
    sents = re.split(r"[，。；、,;。！？\s]+", text)
    out: List[str] = []
    for s in sents:
        s = s.strip()
        if not s:
            continue
        for n in (2, 3, 4):
            for i in range(len(s) - n + 1):
                out.append(s[i:i + n])
    return out


def expand_seeds(seed_words: List[str], corpus: List[str], topk: int = 8,
                 threshold: float = 0.35) -> Dict[str, List[Tuple[str, float]]]:
    """在未标注语料中查找与种子词语义相近的词。

    :return: {种子词: [(相近词, 相似度), ...]}
    """
    sim = build_similarity_fn(corpus)
    candidates = sorted({w for s in corpus for w in _tokenize_cn(s)})
    result: Dict[str, List[Tuple[str, float]]] = {}
    for seed in seed_words:
        scored = []
        for cand in candidates:
            if cand == seed or cand in NEGATIVE_SEEDS:
                continue
            s = sim(seed, cand)
            if s >= threshold:
                scored.append((cand, round(s, 3)))
        scored.sort(key=lambda x: -x[1])
        result[seed] = scored[:topk]
    return result


def expanded_vocab(task_key: str, corpus: List[str] = None,
                   topk: int = 8) -> Dict[str, List[str]]:
    """得到扩充后的「动作 → 词表」。"""
    corpus = corpus or default_corpus()
    seeds = seeds_for(task_key)
    out: Dict[str, List[str]] = {}
    for action, words in seeds.items():
        exp = expand_seeds(words, corpus, topk=topk)
        vocab = set(words)
        for seed, neighbors in exp.items():
            for w, _ in neighbors[:3]:
                vocab.add(w)
        out[action] = sorted(vocab)
    return out


# ---------------------------------------------------------------- 弱标签生成


def build_weak_feature(sentence: str, task_key: str, confidence: float = 0.8) -> str:
    """为弱监督/未标注文本构造与 m4 模型一致的特征串。

    弱监督样本只有原始句子，没有实体类别等结构信息，
    这里按同一格式补齐占位 token，保证 train 与 inference 的特征空间一致。
    """
    return (f"[CAT]WEAK [TASK]{task_key} [ROLE]EXTERNAL_MODEL [TRUST]low "
            f"[COL]NONE [N]1 [CONF]{confidence:.2f} [TEXT]{sentence}")


def generate_weak_labels(task_key: str, corpus: List[str] = None,
                         vocab: Dict[str, List[str]] = None
                         ) -> List[dict]:
    """用扩充词表在未标注语料上打弱标签。

    :return: [{"text": ..., "label": "DELETE", "confidence": 0.8, "hit_words": [...]}, ...]
    """
    corpus = corpus or default_corpus()
    vocab = vocab or expanded_vocab(task_key, corpus)
    samples: List[dict] = []
    for sent in corpus:
        scores: Dict[str, float] = {}
        hits: Dict[str, List[str]] = {}
        for action, words in vocab.items():
            hit = [w for w in words if w in sent]
            if hit:
                # 命中越多、词越长，置信度越高
                scores[action] = min(1.0, 0.45 + 0.15 * len(hit)
                                     + 0.05 * max(len(w) for w in hit))
                hits[action] = hit
        if not scores:
            continue
        # 只保留最高分且显著高于次高分的样本，降低噪声
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        best, best_score = ranked[0]
        if len(ranked) > 1 and best_score - ranked[1][1] < 0.08:
            continue
        samples.append({
            "text": sent,
            "feature": build_weak_feature(sent, task_key, best_score),
            "label": best,
            "confidence": round(best_score, 3),
            "hit_words": hits[best],
            "task": task_key,
            "source": "weak",
        })
    return samples


# ---------------------------------------------------------------- 自训练


def self_train_rounds(base_samples: List[dict], unlabeled: List[str],
                      model_factory: Callable, rounds: int = 2,
                      threshold: float = 0.75,
                      task_key: str = "activity_stats") -> Tuple[List[dict], List[dict]]:
    """自训练迭代：每轮把高置信样本加入训练集。

    :return: (最终训练样本, 每轮新增样本的记录)
    """
    train = list(base_samples)
    history: List[dict] = []

    for r in range(rounds):
        if not train:
            break
        model = model_factory()
        res = model.train(train)
        if not res.get("ok"):
            history.append({"round": r, "added": 0, "error": res.get("reason")})
            break

        added = 0
        for text in unlabeled:
            # 用与训练一致的特征格式打分，再筛高置信样本回流训练集
            try:
                feat = build_weak_feature(text, task_key)
                proba = model.pipeline.predict_proba([feat])[0]
                classes = list(model.pipeline.classes_)
                best_i = int(max(range(len(proba)), key=lambda i: proba[i]))
                if proba[best_i] >= threshold:
                    train.append({"text": text, "feature": feat,
                                  "label": classes[best_i],
                                  "confidence": float(proba[best_i]),
                                  "source": f"self_train_r{r}"})
                    added += 1
            except Exception:
                continue
        history.append({"round": r, "added": added, "test_acc": res.get("test_acc")})
        if added == 0:
            break
    return train, history


# ---------------------------------------------------------------- 人工复核子集


def split_review_set(samples: List[dict], review_ratio: float = 0.1,
                     seed: int = 42) -> Tuple[List[dict], List[dict]]:
    """抽出人工复核子集，单独验证弱监督质量，不参与训练。"""
    rng = random.Random(seed)
    idx = list(range(len(samples)))
    rng.shuffle(idx)
    n_review = max(1, int(len(samples) * review_ratio))
    review_idx = set(idx[:n_review])
    review = [samples[i] for i in idx[:n_review]]
    train = [samples[i] for i in idx[n_review:]]
    return train, review


def save_jsonl(items: Iterable[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    return path
