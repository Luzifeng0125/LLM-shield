"""Local service readiness without exposing keys or model file paths."""
from __future__ import annotations

from . import config as C
from .m2_detect.pipeline import DetectionError, build_detectors
from .m4_necessity.model import get_model
from .m7_egress.llm_client import configuration_status
from .m7_egress.policy import policy_mode


def readiness() -> dict:
    action_ready = get_model().available
    try:
        detector_names = [detector.name for detector in build_detectors()]
        recognizer_ready = True
    except DetectionError:
        detector_names = []
        recognizer_ready = False
    llm = C.llm_settings()
    status = configuration_status(llm)
    real_configured = llm["mode"] != "mock" and status == "configuration_only"
    ready_local = action_ready and recognizer_ready
    return {
        "ready_local": ready_local,
        "ready_to_chat": ready_local and (llm["mode"] == "mock" or real_configured),
        "action_model_ready": action_ready,
        "recognizer_ready": recognizer_ready,
        "detectors": detector_names,
        "gliner_enabled": C.use_gliner(),
        "llm_mode": llm["mode"],
        "generation_config_status": status,
        "egress_policy_mode": policy_mode(),
        "real_api_configured": real_configured,
        "ready_for_real": ready_local and real_configured,
        "single_process_sessions": True,
        "max_parallel_analyses": C.max_parallel_analyses(),
    }
