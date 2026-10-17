"""Local service readiness without exposing keys or model file paths."""
from __future__ import annotations

from . import config as C
from .m2_detect.pipeline import DetectionError, build_detectors
from .m4_necessity.model import get_model


def readiness() -> dict:
    action_ready = get_model().available
    try:
        detector_names = [detector.name for detector in build_detectors()]
        recognizer_ready = True
    except DetectionError:
        detector_names = []
        recognizer_ready = False
    llm = C.llm_settings()
    real_configured = bool(llm["api_key"] and llm["base_url"] and llm["model"])
    ready_local = action_ready and recognizer_ready
    return {
        "ready_local": ready_local,
        "ready_to_chat": ready_local and (llm["mode"] != "real" or real_configured),
        "action_model_ready": action_ready,
        "recognizer_ready": recognizer_ready,
        "detectors": detector_names,
        "gliner_enabled": C.use_gliner(),
        "llm_mode": llm["mode"],
        "real_api_configured": real_configured,
        "ready_for_real": ready_local and real_configured,
        "single_process_sessions": True,
        "max_parallel_analyses": C.max_parallel_analyses(),
    }
