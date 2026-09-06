class MondayApiError(Exception):
    """Base exception for Monday API errors."""


class MondayApiHttpError(MondayApiError):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class MondayGraphQLError(MondayApiError):
    def __init__(self, message: str, errors: list, data: dict | None = None):
        super().__init__(message)
        self.errors = errors
        self.data = data


class MondayRateLimitError(MondayApiError):
    def __init__(self, message: str, retry_in_seconds: int):
        super().__init__(message)
        self.retry_in_seconds = retry_in_seconds
