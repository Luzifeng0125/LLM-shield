"""Start the reviewed-gold NER candidate locally with simulated replies only."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[1]
DELIVERY = APP.parent
DEFAULT_ARTIFACT = (DELIVERY / "数据集" / "复核与训练执行包_20261014" / "outputs" /
                    "gold_run_20261016" / "ner_bert_v1")
sys.path.insert(0, str(APP))


def configure_local_candidate(artifact: Path, device: str, action_model: Path | None = None,
                              decoding: str = "greedy") -> None:
    """Process-only overrides take precedence over the app's .env settings."""
    os.environ.update({
        "LLM_MODE": "mock",
        "SHIELD_REVIEWED_NER_MODEL_DIR": str(artifact),
        "SHIELD_REVIEWED_NER_DEVICE": device,
        "SHIELD_REVIEWED_NER_DECODING": decoding,
        "SHIELD_USE_CAMPUS_NER": "false",
        "SHIELD_USE_GLINER": "false",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "TOKENIZERS_PARALLELISM": "false",
    })
    if action_model is not None:
        os.environ["SHIELD_ACTION_MODEL_PATH"] = str(action_model.expanduser().resolve())


def preflight(artifact: Path, device: str, action_model: Path | None = None, decoding: str = "greedy") -> dict:
    """Load the selected detector and score a software fixture entirely locally."""
    if not artifact.is_dir() or not (artifact / "artifact_manifest.json").is_file():
        raise ValueError("候选模型目录或 artifact_manifest.json 不存在")
    configure_local_candidate(artifact, device, action_model, decoding)
    from llm_shield.config import llm_settings
    from llm_shield.m2_detect.pipeline import build_detectors, detect_and_segment
    from llm_shield.m4_necessity.model import get_model

    if llm_settings()["mode"] != "mock":
        raise RuntimeError("候选版必须使用模拟回复模式")
    detectors = build_detectors(use_campus_ner=False)
    reviewed = [detector for detector in detectors if detector.name == "reviewed_ner"]
    if len(reviewed) != 1 or not reviewed[0].available:
        raise RuntimeError("人工 gold 候选识别模型未成功加载")
    # This is an execution fixture, not a human-reviewed quality measurement.
    text = "姓名：张三，学号：2026000123。请整理活动报名说明。"
    spans, segments = detect_and_segment(text, detectors=detectors)
    if not segments:
        raise RuntimeError("本地检测预检未生成处理片段")
    decision_model = get_model()
    scores = decision_model.score(segments[0], "meeting_minutes", "external_model")
    if (not scores or any(not math.isfinite(value) or not 0 <= value <= 1 for value in scores.values())
            or not math.isclose(sum(scores.values()), 1.0, abs_tol=1e-5)):
        raise RuntimeError("本地动作模型预检未返回有效概率")
    # Import the ASGI app now so missing serving/upload dependencies fail before
    # announcing a ready service. Import does not execute a model API request.
    from llm_shield.server import app
    import uvicorn

    if app is None or not callable(uvicorn.run):
        raise RuntimeError("本地服务依赖未就绪")
    return {
        "status": "ready", "mode": "人工 gold 候选版", "llm_mode": "mock",
        "external_model_called": False, "device": device, "artifact_dir": str(artifact),
        "detectors": [detector.name for detector in detectors],
        "fixture_detected_spans": len(spans), "action_model_backend": decision_model.backend,
        "action_model_path": str(decision_model.model_path),
        "ner_decoding": reviewed[0].decoding,
        "action_score_check": "passed",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="仅加载并验证本地模型，不启动网页服务")
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_ARTIFACT,
                        help="包含 artifact_manifest.json 和 model 子目录的候选产物目录")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--action-model", type=Path, help="本机动作候选权重；不会覆盖原权重")
    parser.add_argument("--ner-decoding", choices=("greedy", "bio_viterbi"), default="greedy")
    parser.add_argument("--port", type=int, default=8788)
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("--port 必须介于 1024 和 65535")
    print("=" * 64, flush=True)
    print("  人工 gold 候选版 / 模拟回复 / 实际未调用外部模型", flush=True)
    print("  此入口仅做本地候选验证，不调用外部模型。", flush=True)
    print("=" * 64, flush=True)
    artifact = args.model_dir.expanduser().resolve()
    # Set offline/mock constraints before optional model libraries are imported.
    configure_local_candidate(artifact, "cpu", args.action_model, args.ner_decoding)
    try:
        import torch
        torch.set_num_threads(4)
        device = args.device
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("指定了 CUDA，但本机 GPU 不可用；可改用 --device cpu")
        report = preflight(artifact, device, args.action_model, args.ner_decoding)
    except Exception as exc:
        print(f"候选版启动预检失败（{type(exc).__name__}）：{exc}", file=sys.stderr, flush=True)
        return 1
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if args.check_only:
        print("本地预检通过；未启动服务，实际未调用外部模型。", flush=True)
        return 0
    print(f"候选版地址：http://127.0.0.1:{args.port}/", flush=True)
    print("人工 gold 候选版 / 模拟回复 / 实际未调用外部模型", flush=True)
    print("请保持此窗口打开；按 Ctrl+C 停止。", flush=True)
    import uvicorn
    uvicorn.run("llm_shield.server:app", host="127.0.0.1", port=args.port,
                reload=False, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
