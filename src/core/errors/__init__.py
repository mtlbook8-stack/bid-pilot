"""Error architecture (Rule 8): errors throw up, logs live at the top."""

from src.core.errors.app_error import AppError

__all__ = ["AppError"]
