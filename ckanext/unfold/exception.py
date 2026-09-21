PASSWORD_REQUIRED = "password_required"  # noqa: S105
PASSWORD_INCORRECT = "password_incorrect"  # noqa: S105
TOO_LARGE = "too_large"
FETCH_FAILED = "fetch_failed"
UNSUPPORTED_FORMAT = "unsupported_format"
UNREADABLE = "unreadable"
GENERIC = "error"


class UnfoldError(Exception):
    """An archive cannot be listed; the message is safe to show to any user.

    ``code`` is one of the constants above, or ``"error"`` when there is
    nothing more specific to say.
    """

    def __init__(self, message: str = "", code: str = GENERIC) -> None:
        super().__init__(message)
        self.code = code
