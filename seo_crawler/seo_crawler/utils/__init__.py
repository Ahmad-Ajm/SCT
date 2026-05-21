"""
Shared utilities package.

Keep this package initializer intentionally light. Importing ``utils.logger``
should not pull URL parsing dependencies such as ``tldextract`` just to show
CLI help or configure logging.
"""

__all__ = [
    "get_logger",
    "normalize_url",
    "is_internal_url",
    "safe_filename",
    "pixel_width_estimate",
    "compute_text_hash",
    "format_bytes",
    "StateManager",
]


def __getattr__(name: str):
    if name == "get_logger":
        from utils.logger import get_logger

        return get_logger

    if name == "StateManager":
        from utils.state_manager import StateManager

        return StateManager

    if name in {
        "normalize_url",
        "is_internal_url",
        "safe_filename",
        "pixel_width_estimate",
        "compute_text_hash",
        "format_bytes",
    }:
        from utils import helpers

        return getattr(helpers, name)

    raise AttributeError(f"module 'utils' has no attribute {name!r}")
