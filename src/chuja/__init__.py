"""chuja — separate a song into stems from a local file or (opt-in) a URL.

    >>> import chuja
    >>> result = chuja.separate("song.mp3", out_dir="stems", fmt="mp3")
    >>> result.stems
    {'drums': PosixPath('stems/song/drums.mp3'), ...}
"""

from .errors import (
    ExportError,
    FetchError,
    MissingDependencyError,
    SeparationError,
    SourceError,
    ChujaError,
)
from .pipeline import Result, separate
from .separator import MODELS

__version__ = "0.1.0"

__all__ = [
    "separate",
    "Result",
    "MODELS",
    "__version__",
    "ChujaError",
    "SourceError",
    "FetchError",
    "MissingDependencyError",
    "SeparationError",
    "ExportError",
]
