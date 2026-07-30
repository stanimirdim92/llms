"""Custom API exceptions. Subclassing `HTTPException` (rather than a plain
`Exception`) means FastAPI's own default exception handler already converts these into
a correct `{"detail": ...}` JSON response at the given status code with zero extra
wiring -- the `PortfolioError` handler in `api/main.py` only adds structured logging on
top of that, it doesn't replace it.
"""

from fastapi import HTTPException


class PortfolioError(HTTPException):
    """Base class for this app's own API exceptions, as opposed to a bare
    `HTTPException` raised by FastAPI/Starlette/library code -- lets `api/main.py`'s
    exception handler log our own errors distinctly from those.
    """


class APIError(PortfolioError):
    def __init__(self, message: str, code: int = 400, headers: dict[str, str] | None = None) -> None:
        """`headers` exists for responses whose status code is only half the information --
        a 429 without `Retry-After` tells a client to back off but not for how long, so it
        either guesses or hammers.
        """
        super().__init__(status_code=code, detail=message, headers=headers)
