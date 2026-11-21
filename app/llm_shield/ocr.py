"""Extract a local review draft from an image or scanned PDF."""
from __future__ import annotations

import io
import time
from functools import lru_cache
from pathlib import Path
from threading import Lock

MAX_BYTES = 5 * 1024 * 1024
MAX_PAGES = 20
MAX_PIXELS = 16_000_000
MAX_TEXT = 24_000
_OCR_LOCK = Lock()


class OcrError(ValueError):
    pass


@lru_cache(maxsize=1)
def _engine():
    try:
        import rapidocr
    except ImportError:
        raise OcrError("请先安装 requirements-ocr.txt 中的本机 OCR 依赖") from None
    models = Path(rapidocr.__file__).parent / "models"
    weights = {"Det": "PP-OCRv6_det_small.onnx", "Rec": "PP-OCRv6_rec_small.onnx"}
    if any(not (models / name).is_file() for name in weights.values()):
        raise OcrError("本机 OCR 权重不完整，请重新安装 OCR 依赖")
    params = {f"{stage}.model_path": str(models / name) for stage, name in weights.items()}
    params.update({"Global.use_cls": False, "Global.text_score": 0.0,
                   "EngineConfig.onnxruntime.intra_op_num_threads": 3,
                   "EngineConfig.onnxruntime.inter_op_num_threads": 1})
    return rapidocr.RapidOCR(params=params)


def _image(data: bytes):
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(data), formats=("PNG", "JPEG")) as image:
        if image.width * image.height > MAX_PIXELS:
            raise OcrError("图片像素超过 1600 万，请缩小后重试")
        return ImageOps.exif_transpose(image).convert("RGB")


def _recognize(engine, image, number: int) -> dict:
    result = engine(image)
    lines = []
    for text, confidence, box in zip(result.txts or (), result.scores or (),
                                     () if result.boxes is None else result.boxes):
        if not text.strip():
            continue
        lines.append({"text": text, "confidence": round(float(confidence), 3),
                      "box": [[round(float(x)), round(float(y))] for x, y in box]})
    return {"page": number, "width": image.width, "height": image.height, "lines": lines,
            "low_confidence": sum(line["confidence"] < 0.85 for line in lines)}


def _pdf_pages(engine, data: bytes) -> list[dict]:
    import pypdfium2 as pdfium
    results = []
    started = time.monotonic()
    with pdfium.PdfDocument(data) as document:
        if not 1 <= len(document) <= MAX_PAGES:
            raise OcrError("扫描 PDF 一次支持 1 至 20 页，请拆分后重试")
        for index in range(len(document)):
            if time.monotonic() - started > 90:
                raise OcrError("扫描件处理超过 90 秒，请拆分后重试")
            page = document[index]
            try:
                w, h = page.get_size()
                if not (w > 0 and h > 0):
                    raise OcrError("PDF 页面尺寸无效")
                scale = min(2.5, 3200 / max(w, h))
                bitmap = page.render(scale=scale)
                try:
                    image = bitmap.to_pil().convert("RGB")
                    results.append(_recognize(engine, image, index + 1))
                finally:
                    bitmap.close()
            finally:
                page.close()
    return results


def read_ocr(data: bytes, filename: str) -> dict:
    if not 0 < len(data) <= MAX_BYTES:
        raise OcrError("文件为空或超过 5 MB")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg"}:
        raise OcrError("本机 OCR 支持 PDF、PNG 和 JPEG")
    if not _OCR_LOCK.acquire(blocking=False):
        raise OcrError("当前正在处理另一份扫描件，请稍后重试")
    try:
        engine = _engine()
        if suffix == ".pdf":
            pages = _pdf_pages(engine, data)
        else:
            pages = [_recognize(engine, _image(data), 1)]
    except OcrError:
        raise
    except Exception:
        raise OcrError("本机 OCR 无法读取此文件，请检查格式、权限或依赖安装") from None
    finally:
        _OCR_LOCK.release()

    if not any(page["lines"] for page in pages):
        raise OcrError("未识别到可核对的文本")
    text = "\n\n".join(f"【第 {p['page']} 页】\n" + "\n".join(line["text"] for line in p["lines"])
                       for p in pages)
    if len(text) > MAX_TEXT:
        raise OcrError("识别文本超过 24000 字符，请拆分文件后重试")
    return {"text": text, "pages": pages, "requires_review": True}
