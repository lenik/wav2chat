"""User-facing errors for wav2chat."""


class Wav2ChatError(Exception):
    """Base error for wav2chat."""


class InputNotFoundError(Wav2ChatError):
    """Raised when the input path does not exist."""


class UnsupportedInputError(Wav2ChatError):
    """Raised when the input type is not supported."""


class EmptyBatchDirectoryError(Wav2ChatError):
    """Raised when batch mode finds no supported audio files."""


class FFmpegNotFoundError(Wav2ChatError):
    """Raised when ffmpeg is not installed or not on PATH."""


class FFmpegConversionError(Wav2ChatError):
    """Raised when ffmpeg fails to convert audio."""


class FunASRLoadError(Wav2ChatError):
    """Raised when FunASR models fail to load."""


class FunASREmptyResultError(Wav2ChatError):
    """Raised when FunASR returns no usable transcript."""


class UnsupportedBackendError(Wav2ChatError):
    """Raised when an unsupported backend is requested."""
