---
language:
  - zh
license: apache-2.0
task_categories:
  - token-classification
tags:
  - pii
  - privacy
  - de-identification
  - chinese
  - ner
  - benchmark
  - synthetic
pretty_name: "PII Bench ZH - Chinese PII Detection Benchmark"
size_categories:
  - 1K<n<10K
---

# PII Bench ZH

Chinese PII (Personally Identifiable Information) detection benchmark dataset. Two subsets covering formal and informal Chinese text, with character-level span annotations.

**This is the first open Chinese PII benchmark that covers locale-specific formats (phone, national ID, bank card, license plate, address) with precise offsets.**

> **Disclaimer / 免责声明**
>
> This dataset is **100% synthetic** and intended **solely for research and evaluation purposes**. It does not contain any real personal information. All names, ID numbers, phone numbers, bank card numbers, addresses, and other data are randomly generated and do not correspond to any real individuals or entities. The ID numbers and bank card numbers use valid checksum algorithms with real area code / BIN prefixes for realism, but the complete numbers are fictitious.
>
> 本数据集为 **100% 合成数据**，**仅供研究和评估使用**。数据集不包含任何真实个人信息。所有姓名、身份证号、手机号、银行卡号、地址等均为随机生成，不对应任何真实个人或实体。身份证号和银行卡号使用了真实的区号前缀 / BIN 码以增加真实感，但完整号码均为虚构。
>
> The authors assume no liability for any misuse of this dataset. Users are responsible for ensuring compliance with applicable laws and regulations in their jurisdiction.
>
> 作者不对本数据集的任何滥用行为承担责任。用户有责任确保其使用符合所在司法管辖区的相关法律法规。

## Subsets

| Subset | File | Samples | Description |
|--------|------|---------|-------------|
| **formal** | `data/pii_bench_zh.jsonl` | 5,000 | Formal text: registration forms, medical records, delivery orders, contracts |
| **chat** | `data/pii_bench_zh_chat.jsonl` | 3,000 | Noisy chat/IM: emoji, informal tone, voice-to-text, mixed zh/en, non-standard formatting |

Total: 8,000 samples, 23,206 PII entities.

The **chat** subset is designed to stress-test PII detection under realistic noise conditions:
- Phone numbers with spaces/dashes (`138 1234 5678`)
- Emoji interleaved with PII (`加个微信吧 张三 13812345678 😂`)
- Filler words and casual tone (`嗯，那个人叫张三 身份证号...`)
- Chinese-English code-switching (`pls contact 张三 phone:13812345678`)
- No formal context markers (no "客户"/"患者" prefixes)

## How This Dataset Was Created

This dataset was generated programmatically using template-based synthesis — **no real data was collected, scraped, or anonymized**.

The generation process:

1. **Templates** — 11 formal scenario templates + 13 chat scenario templates covering IM conversations, group chats, voice-to-text, WeChat-style messages, etc.
2. **Fake PII generators** — each PII type has a dedicated generator:
   - **ID numbers**: real area code prefixes + random birth date + valid MOD 11-2 checksum
   - **Bank cards**: real BIN prefixes + random digits + valid Luhn checksum
   - **Phone numbers**: valid Chinese mobile prefixes (1[3-9]) + 9 random digits
   - **Addresses**: real province/city/district names + random street + random number
   - **License plates**: real province abbreviations + random alphanumeric
   - **Names**: random combination from 50 common surnames × 50 common given names
   - **Passports**: E/G prefix + 8 random digits
   - **Emails**: random pinyin-like local parts + common Chinese email domains
3. **Noise injection** (chat subset only): emoji insertion, filler words, phone number reformatting (spaces/dashes), casual punctuation
4. **Offset verification** — every sample is validated: `text[start:end] == entity.text`
5. **Deterministic** — seed=42, fully reproducible

## Entity Types

| Type | Formal | Chat | Example | Validation |
|------|--------|------|---------|------------|
| person | 5,310 | 3,010 | 张三 | Chinese name (surname + given) |
| phone | 4,400 | 2,261 | 13812345678 | 1[3-9] + 9 digits |
| id_number | 1,812 | 522 | 110101199003071234 | 18 digits, MOD 11-2 checksum |
| address | 1,429 | 255 | 北京市朝阳区建国路100号 | Province + city + district + street |
| email | 931 | 493 | zhangsan@qq.com | Standard email format |
| bank_card | 862 | 504 | 6217001234567890 | 16 digits, Luhn checksum |
| passport | 463 | 260 | E12345678 | E/G + 8 digits |
| license_plate | 455 | 239 | 京A12345 | Province + letter + 5 alphanumeric |

## Format

JSONL with one sample per line:

```json
{
  "id": "zh_chat_000001",
  "text": "你存一下 张三 138 1234 5678 😂",
  "lang": "zh",
  "entities": [
    {"text": "张三", "type": "person", "start": 5, "end": 7},
    {"text": "138 1234 5678", "type": "phone", "start": 8, "end": 21}
  ]
}
```

## Usage

```python
from datasets import load_dataset

# Load formal subset
formal = load_dataset("wan9yu/pii-bench-zh", data_files="data/pii_bench_zh.jsonl", split="train")

# Load chat subset
chat = load_dataset("wan9yu/pii-bench-zh", data_files="data/pii_bench_zh_chat.jsonl", split="train")
```

### With argus-redact benchmark framework

```bash
pip install argus-redact datasets
python -m tests.benchmark pii_bench_zh --mode fast --limit 1000       # formal
python -m tests.benchmark pii_bench_zh_chat --mode fast --limit 1000  # chat
```

Generator source code:
- Formal: [`tests/benchmark/generators/zh.py`](https://github.com/wan9yu/argus-redact/blob/main/tests/benchmark/generators/zh.py)
- Chat: [`tests/benchmark/generators/zh_chat.py`](https://github.com/wan9yu/argus-redact/blob/main/tests/benchmark/generators/zh_chat.py)

Reproduce:
```bash
git clone https://github.com/wan9yu/argus-redact.git
cd argus-redact
python -m tests.benchmark.generators.zh --count 5000 --seed 42 --output pii_bench_zh.jsonl
python -m tests.benchmark.generators.zh_chat --count 3000 --seed 42 --output pii_bench_zh_chat.jsonl
```

## License

Apache 2.0

## Citation

```bibtex
@dataset{pii_bench_zh_2026,
  title={PII Bench ZH: Chinese PII Detection Benchmark},
  author={wan9yu},
  year={2026},
  url={https://huggingface.co/datasets/wan9yu/pii-bench-zh},
  publisher={Hugging Face}
}
```

## Related

- [argus-redact](https://github.com/wan9yu/argus-redact) — Reversible PII encryption for LLM pipelines
- [ai4privacy/pii-masking-400k](https://huggingface.co/datasets/ai4privacy/pii-masking-400k) — Multilingual PII (Western languages)
- [nvidia/Nemotron-PII](https://huggingface.co/datasets/nvidia/Nemotron-PII) — English PII with 55+ types
