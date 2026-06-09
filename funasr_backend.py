"""FunASR transcription backend with speaker diarization."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from wav2chat.errors import FunASREmptyResultError, FunASRLoadError
from wav2chat.models import Segment, Transcript

logger = logging.getLogger(__name__)

DEFAULT_ASR_MODEL = "paraformer-zh"
DEFAULT_VAD_MODEL = "fsmn-vad"
DEFAULT_PUNC_MODEL = "ct-punc"
DEFAULT_SPK_MODEL = "cam++"


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
    roles: dict[str, str] | None = None,
) -> list[Segment]:
    sentence_info = result.get("sentence_info")
    if not isinstance(sentence_info, list):
        return []

    role_map = roles or {}
    segments: list[Segment] = []

    for item in sentence_info:
        if not isinstance(item, dict):
            continue
        text = _extract_text(item)
        if not text:
            continue
        start, end = _extract_times(item)
        speaker = _extract_speaker(item)
        segments.append(
            Segment(
                start=start,
                end=end,
                speaker=speaker,
                role=role_map.get(speaker),
                text=text,
            )
        )

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
    ) -> None:
        self.min_speakers = min_speakers
        self.max_speakers = max_speakers
        self.asr_model = asr_model
        self.vad_model = vad_model
        self.punc_model = punc_model
        self.spk_model = spk_model
        self._model: Any | None = None

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

        kwargs: dict[str, Any] = {
            "model": self.asr_model,
            "vad_model": self.vad_model,
            "punc_model": self.punc_model,
            "spk_model": self.spk_model,
        }
        if self.min_speakers is not None:
            kwargs["spk_kwargs"] = {"min_speakers": self.min_speakers}
        if self.max_speakers is not None:
            spk_kwargs = kwargs.setdefault("spk_kwargs", {})
            spk_kwargs["max_speakers"] = self.max_speakers

        try:
            logger.debug("Loading FunASR models: %s", kwargs)
            self._model = AutoModel(**kwargs)
        except Exception as exc:
            raise FunASRLoadError(f"Failed to load FunASR models: {exc}") from exc

        return self._model

    def transcribe(
        self,
        wav_path: Path,
        source_name: str,
        roles: dict[str, str] | None = None,
    ) -> Transcript:
        model = self._load_model()
        wav_path = wav_path.resolve()

        try:
            res = model.generate(input=str(wav_path), batch_size_s=300)
        except Exception as exc:
            raise FunASREmptyResultError(f"FunASR transcription failed: {exc}") from exc

        result = _unwrap_generate_result(res)
        segments = _parse_sentence_info(result, roles=roles)

        if not segments:
            fallback_text = _extract_text(result)
            if fallback_text:
                segments = [
                    Segment(
                        start=0.0,
                        end=0.0,
                        speaker="spk0",
                        role=(roles or {}).get("spk0"),
                        text=fallback_text,
                    )
                ]
            else:
                raise FunASREmptyResultError(
                    "FunASR returned no sentence_info and no fallback text."
                )

        return Transcript(
            source=source_name,
            duration=_estimate_duration(segments),
            segments=segments,
        )
