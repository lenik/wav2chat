"""FunASR transcription backend with speaker diarization."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from wav2chat.errors import FunASREmptyResultError, FunASRLoadError
from wav2chat.jieba_cache import configure_jieba_cache
from wav2chat.models import Segment, Transcript, index_string_speaker_segments

logger = logging.getLogger(__name__)

DEFAULT_ASR_MODEL = "paraformer-zh"
DEFAULT_VAD_MODEL = "fsmn-vad"
DEFAULT_PUNC_MODEL = "ct-punc"
DEFAULT_SPK_MODEL = "cam++"


def _is_local_model_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    return any((path / marker).is_file() for marker in ("model.pt", "config.yaml", "configuration.json"))


@contextmanager
def _prefer_mmap_torch_load(enabled: bool = True) -> Iterator[None]:
    """Use PyTorch mmap when reading checkpoints (faster load from local cache)."""
    if not enabled:
        yield
        return

    import torch

    original_load = torch.load

    def patched_load(f, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("mmap", True)
        return original_load(f, *args, **kwargs)

    torch.load = patched_load  # type: ignore[assignment]
    try:
        yield
    finally:
        torch.load = original_load


def _resolve_modelscope_model(model: str, *, refresh: bool = False) -> str:
    """Prefer a local ModelScope cache directory over hub aliases."""
    if refresh:
        return model

    local = Path(model).expanduser()
    if _is_local_model_dir(local):
        return str(local.resolve())

    from funasr.download.name_maps_from_hub import name_maps_ms

    model_id = name_maps_ms.get(model, model)
    if "/" not in model_id and not model_id.startswith("iic"):
        return model

    try:
        from modelscope.utils.file_utils import get_model_cache_root
    except ImportError:
        return model

    cache_dir = Path(get_model_cache_root()) / model_id
    if _is_local_model_dir(cache_dir):
        logger.debug("Using cached ModelScope model: %s", cache_dir)
        return str(cache_dir.resolve())

    return model


@contextmanager
def _disable_progress_bars() -> Iterator[None]:
    """Suppress tqdm progress output from FunASR during GUI conversion."""
    old_tqdm = os.environ.get("TQDM_DISABLE")
    os.environ["TQDM_DISABLE"] = "1"
    try:
        yield
    finally:
        if old_tqdm is None:
            os.environ.pop("TQDM_DISABLE", None)
        else:
            os.environ["TQDM_DISABLE"] = old_tqdm


@contextmanager
def _null_context() -> Iterator[None]:
    yield


class _FunASRLoadTimingFilter(logging.Filter):
    """Append checkpoint load duration to FunASR log lines."""

    def __init__(self) -> None:
        super().__init__()
        self._starts: dict[str, float] = {}

    def _format_message(self, record: logging.LogRecord) -> str:
        msg = record.msg
        if isinstance(msg, str):
            if record.args:
                try:
                    return msg % record.args
                except Exception:
                    return msg
            return msg
        return record.getMessage()

    def filter(self, record: logging.LogRecord) -> bool:
        text = self._format_message(record)

        preload_prefix = "Loading pretrained params from "
        if text.startswith(preload_prefix):
            self._starts[text[len(preload_prefix) :]] = time.perf_counter()
            return True

        ckpt_prefix = "ckpt: "
        if text.startswith(ckpt_prefix):
            path = text[len(ckpt_prefix) :]
            self._starts.setdefault(path, time.perf_counter())
            return True

        loaded_prefix = "Loading ckpt: "
        if text.startswith(loaded_prefix) and ", status:" in text:
            rest = text[len(loaded_prefix) :]
            path, status_part = rest.split(", status:", 1)
            start = self._starts.pop(path, None)
            if start is not None:
                elapsed = time.perf_counter() - start
                record.msg = f"Loading ckpt: {path}, status:{status_part} ({elapsed:.1f}s)"
                record.args = ()
            return True

        return True


@contextmanager
def _funasr_load_timing_logs() -> Iterator[None]:
    timing = _FunASRLoadTimingFilter()
    root = logging.getLogger()
    root.addFilter(timing)
    try:
        yield
    finally:
        root.removeFilter(timing)


@contextmanager
def _tqdm_progress_hook(on_percent: Callable[[int], None]) -> Iterator[None]:
    """Forward FunASR tqdm updates to a GUI progress callback."""
    import tqdm as tqdm_module

    original = tqdm_module.tqdm
    peak = 0

    def report(sub_percent: int) -> None:
        nonlocal peak
        peak = max(peak, max(0, min(100, sub_percent)))
        on_percent(peak)

    class ReportingTqdm(original):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._report()

        def update(self, n: float = 1) -> bool | None:
            result = super().update(n)
            self._report()
            return result

        def _report(self) -> None:
            total = self.total
            if total and total > 0:
                report(int(100 * self.n / total))

    tqdm_module.tqdm = ReportingTqdm
    try:
        yield
    finally:
        tqdm_module.tqdm = original


def _normalize_time(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid timestamp value: {value!r}") from exc
    if number > 1000:
        return number / 1000.0
    return number


def _normalize_speaker(value: Any) -> str:
    if value is None:
        return "spk0"
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return "spk0"
        if stripped.startswith("spk"):
            return stripped
        if stripped.isdigit():
            return f"spk{stripped}"
        return stripped
    if isinstance(value, int):
        return f"spk{value}"
    return str(value)


def _extract_text(item: dict[str, Any]) -> str:
    for key in ("text", "sentence", "content", "punc_text"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_times(item: dict[str, Any]) -> tuple[float, float]:
    if "start" in item or "end" in item:
        return _normalize_time(item.get("start", 0.0)), _normalize_time(item.get("end", 0.0))

    timestamp = item.get("timestamp")
    if isinstance(timestamp, (list, tuple)) and len(timestamp) >= 2:
        return _normalize_time(timestamp[0]), _normalize_time(timestamp[1])

    if isinstance(timestamp, dict):
        return _normalize_time(timestamp.get("start", 0.0)), _normalize_time(timestamp.get("end", 0.0))

    return 0.0, 0.0


def _extract_speaker(item: dict[str, Any]) -> str:
    for key in ("spk", "speaker", "speaker_id", "spk_id"):
        if key in item:
            return _normalize_speaker(item[key])
    return "spk0"


def _parse_sentence_info(
    result: dict[str, Any],
) -> list[tuple[float, float, str, str]]:
    sentence_info = result.get("sentence_info")
    if not isinstance(sentence_info, list):
        return []

    segments: list[tuple[float, float, str, str]] = []

    for item in sentence_info:
        if not isinstance(item, dict):
            continue
        text = _extract_text(item)
        if not text:
            continue
        start, end = _extract_times(item)
        speaker = _extract_speaker(item)
        segments.append((start, end, speaker, text))

    return segments


def _unwrap_generate_result(res: Any) -> dict[str, Any]:
    if isinstance(res, list):
        if not res:
            raise FunASREmptyResultError("FunASR returned an empty result list.")
        first = res[0]
        if isinstance(first, dict):
            return first
        raise FunASREmptyResultError(
            f"Unexpected FunASR list item type: {type(first).__name__}"
        )
    if isinstance(res, dict):
        return res
    raise FunASREmptyResultError(
        f"Unexpected FunASR result type: {type(res).__name__}"
    )


def _estimate_duration(segments: list[Segment]) -> float | None:
    if not segments:
        return None
    return max(segment.end for segment in segments)


class FunASRBackend:
    """Transcribe normalized WAV audio with FunASR AutoModel."""

    def __init__(
        self,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
        asr_model: str = DEFAULT_ASR_MODEL,
        vad_model: str = DEFAULT_VAD_MODEL,
        punc_model: str = DEFAULT_PUNC_MODEL,
        spk_model: str = DEFAULT_SPK_MODEL,
        refresh_models: bool = False,
    ) -> None:
        self.min_speakers = min_speakers
        self.max_speakers = max_speakers
        self.asr_model = asr_model
        self.vad_model = vad_model
        self.punc_model = punc_model
        self.spk_model = spk_model
        self.refresh_models = refresh_models
        self._model: Any | None = None

    def unload(self) -> None:
        """Drop the loaded model so the next load starts fresh."""
        self._model = None

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model

        try:
            from funasr import AutoModel
        except ImportError as exc:
            raise FunASRLoadError(
                "Failed to import FunASR. Install/repair dependencies with: pip install -e .\n"
                f"Import error: {exc}"
            ) from exc

        configure_jieba_cache()

        spk_kwargs: dict[str, Any] = {"check_latest": self.refresh_models}
        if self.min_speakers is not None:
            spk_kwargs["min_speakers"] = self.min_speakers
        if self.max_speakers is not None:
            spk_kwargs["max_speakers"] = self.max_speakers

        resolve = lambda name: _resolve_modelscope_model(name, refresh=self.refresh_models)
        resolved = {
            "model": resolve(self.asr_model),
            "vad_model": resolve(self.vad_model),
            "punc_model": resolve(self.punc_model),
            "spk_model": resolve(self.spk_model),
        }

        kwargs: dict[str, Any] = {
            **resolved,
            "disable_update": not self.refresh_models,
            "check_latest": self.refresh_models,
            "log_level": "WARNING",
            "vad_kwargs": {"check_latest": self.refresh_models},
            "punc_kwargs": {"check_latest": self.refresh_models},
            "spk_kwargs": spk_kwargs,
        }

        try:
            if self.refresh_models:
                logger.info("Refreshing FunASR models from ModelScope hub")
            else:
                logger.info(
                    "Loading FunASR models from local cache (mmap): %s",
                    resolved,
                )
            logger.debug("Loading FunASR models: %s", kwargs)
            load_started = time.perf_counter()
            with _funasr_load_timing_logs():
                with _prefer_mmap_torch_load(enabled=not self.refresh_models):
                    self._model = AutoModel(**kwargs)
            logger.info(
                "FunASR models loaded in %.1fs",
                time.perf_counter() - load_started,
            )
        except Exception as exc:
            raise FunASRLoadError(f"Failed to load FunASR models: {exc}") from exc

        return self._model

    def load(self) -> None:
        """Load FunASR models eagerly (first transcribe otherwise loads lazily)."""
        self._load_model()

    def transcribe(
        self,
        wav_path: Path,
        source_name: str,
        roles: dict[str, str] | None = None,
        disable_progress: bool = False,
        progress_callback: Callable[[int], None] | None = None,
    ) -> Transcript:
        model = self._load_model()
        wav_path = wav_path.resolve()

        if progress_callback is not None:
            progress_ctx = _tqdm_progress_hook(progress_callback)
        elif disable_progress:
            progress_ctx = _disable_progress_bars()
        else:
            progress_ctx = _null_context()
        try:
            with progress_ctx:
                logger.info("Transcribing %s", source_name)
                res = model.generate(input=str(wav_path), batch_size_s=300)
        except Exception as exc:
            raise FunASREmptyResultError(f"FunASR transcription failed: {exc}") from exc

        result = _unwrap_generate_result(res)
        raw_segments = _parse_sentence_info(result)

        if not raw_segments:
            fallback_text = _extract_text(result)
            if fallback_text:
                raw_segments = [(0.0, 0.0, "spk0", fallback_text)]
            else:
                raise FunASREmptyResultError(
                    "FunASR returned no sentence_info and no fallback text."
                )

        speakers, segments = index_string_speaker_segments(raw_segments, roles=roles)
        return Transcript(
            source=source_name,
            duration=_estimate_duration(segments),
            speakers=speakers,
            segments=segments,
        )
