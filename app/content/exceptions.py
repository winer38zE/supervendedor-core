"""Excepciones del módulo Content & Outliers."""

from __future__ import annotations


class ContentError(Exception):
    """Base del módulo content."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class ContentPaymentRequiredError(ContentError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=402)


class ContentNotFoundError(ContentError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=404)


class ContentValidationError(ContentError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=422)


class ContentConflictError(ContentError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=409)


class ContentLLMError(ContentError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=502)
