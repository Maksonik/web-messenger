from fastapi import status


class ServiceError(Exception):
    """Business-rule violation; mapped to an HTTP (or WebSocket) error by the caller."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "bad_request"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFoundError(ServiceError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ForbiddenError(ServiceError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class ConflictError(ServiceError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class PayloadTooLargeError(ServiceError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = "too_large"


class RateLimitedError(ServiceError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"
