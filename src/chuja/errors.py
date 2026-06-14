"""Exception types raised across chuja. Kept dependency-free so callers can
catch them without importing the heavy ML stack."""


class ChujaError(Exception):
    """Base class for all expected, user-facing failures."""


class SourceError(ChujaError):
    """The input could not be resolved to a usable audio file."""


class FetchError(SourceError):
    """A URL could not be downloaded (network, unsupported site, blocked, etc.)."""


class MissingDependencyError(ChujaError):
    """An optional dependency required for this operation is not installed."""


class SeparationError(ChujaError):
    """The separation engine (Demucs) failed to produce stems."""


class ExportError(ChujaError):
    """A separated stem could not be written to disk in the requested format."""
