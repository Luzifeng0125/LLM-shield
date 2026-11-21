"""Token-complete target-aware inputs for the offline BERT action experiment.

Only the user's request, prior context, document, and selected target enter the
encoder. Each chunk repeats the prefix; body coverage includes target markers.
This module performs no downloads and does not import a neural runtime.
"""
from __future__ import annotations

import re

ABLATIONS = {'full', 'no_prior', 'no_context', 'target_only'}


def _positions(text, target, supplied):
    if not isinstance(target, str) or not target:
        raise ValueError('判断目标必须是非空文本')
    positions = ([m.start() for m in re.finditer(re.escape(target), text)]
                 if supplied is None else list(supplied))
    if (not positions or any(type(p) is not int or p < 0
                             or text[p:p + len(target)] != target for p in positions)
            or len(positions) != len(set(positions))):
        raise ValueError('目标位置缺失、重复或与正文不匹配')
    positions.sort()
    if any(b < a + len(target) for a, b in zip(positions, positions[1:])):
        raise ValueError('同一决策中的目标位置不能重叠')
    return positions


def _body_tokens(text, target, positions, tokenizer):
    # Insert reserved token IDs directly. Encoding the literal string
    # "[unused1]" alone can instead split it into punctuation and wordpieces.
    marker_ids = [tokenizer.convert_tokens_to_ids(t) for t in ('[unused1]', '[unused2]')]
    if (any(type(t) is not int or t < 0 or t == getattr(tokenizer, 'unk_token_id', None)
            for t in marker_ids) or marker_ids[0] == marker_ids[1]):
        raise ValueError('tokenizer缺少可用的目标标记token')
    tokens, cursor = [], 0
    for start in positions:
        tokens.extend(tokenizer.encode(text[cursor:start], add_special_tokens=False))
        tokens.append(marker_ids[0])
        tokens.extend(tokenizer.encode(target, add_special_tokens=False))
        tokens.append(marker_ids[1])
        cursor = start + len(target)
    tokens.extend(tokenizer.encode(text[cursor:], add_special_tokens=False))
    return tokens


def build_chunks(case, tokenizer, ablation='full', max_length=512, overlap=32):
    """Return complete body chunks and auditable token-coverage statistics.

    ``target_occurrences`` contains selected zero-based character starts. When
    absent, every non-overlapping exact occurrence is selected. Existing source
    offsets are validated before ablation; target-only bodies select offset 0.
    A prefix that leaves fewer than 128 body tokens is rejected, not truncated.
    """
    if ablation not in ABLATIONS:
        raise ValueError('未知输入消融方式')
    if type(max_length) is not int or max_length <= 0:
        raise ValueError('max_length必须为正整数')
    if type(overlap) is not int or overlap < 0:
        raise ValueError('overlap必须为非负整数')
    for key in ('task_description', 'context', 'text', 'target'):
        if not isinstance(case.get(key), str):
            raise ValueError(f'输入字段{key}必须是文本')
    target, body = case['target'], case['text']
    positions = _positions(body, target, case.get('target_occurrences'))
    original_positions = positions[:]
    request, prior = case['task_description'], case['context']
    if ablation in {'no_prior', 'no_context', 'target_only'}:
        prior = ''
    if ablation in {'no_context', 'target_only'}:
        body, positions = target, [0]
    if ablation == 'target_only':
        request = ''
    prefix_text = f'用户请求：{request}\n前序：{prior}\n当前判断目标：{target}'
    prefix = tokenizer.encode(prefix_text, add_special_tokens=False)
    pair_overhead = len(tokenizer.build_inputs_with_special_tokens(prefix, []))
    body_budget = max_length - pair_overhead
    if body_budget < 128:
        raise ValueError(f'前缀过长：正文预算{body_budget}小于128，不能静默截断前序')
    if overlap >= body_budget:
        raise ValueError('overlap必须小于正文分块预算')
    tokens = _body_tokens(body, target, positions, tokenizer)
    chunks, spans = [], []
    start = 0
    while start < len(tokens):
        end = min(start + body_budget, len(tokens))
        token_slice = tokens[start:end]
        ids = list(tokenizer.build_inputs_with_special_tokens(prefix, token_slice))
        types = list(tokenizer.create_token_type_ids_from_sequences(prefix, token_slice))
        if len(ids) > max_length or len(ids) != len(types):
            raise ValueError('tokenizer构造的分块长度或segment长度不一致')
        chunks.append({'input_ids': ids, 'attention_mask': [1] * len(ids), 'token_type_ids': types})
        spans.append([start, end])
        if end == len(tokens):
            break
        start = end - overlap
    covered, previous_end = 0, 0
    contiguous = bool(spans) and spans[0][0] == 0
    for start, end in spans:
        contiguous = contiguous and start <= previous_end
        covered += max(0, end - max(start, previous_end))
        previous_end = max(previous_end, end)
    stats = {'prefix_tokens': len(prefix), 'body_tokens': len(tokens), 'chunks': len(chunks),
             'body_tokens_covered': covered, 'all_body_tokens_covered': contiguous and covered == len(tokens),
             'body_chunk_spans': spans, 'body_budget': body_budget, 'overlap': overlap,
             'max_chunk_tokens': max((len(c['input_ids']) for c in chunks), default=0),
             'selected_target_occurrences': original_positions,
             'encoded_target_occurrences': positions, 'ablation': ablation}
    if not stats['all_body_tokens_covered']:
        raise ValueError('正文token覆盖不完整')
    return chunks, stats
