class APIError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        error_type: str = "invalid_request_error",
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.error_type = error_type
        self.headers = headers or {}


class UnknownModelError(Exception):
    pass


class ModelLoadError(Exception):
    pass
