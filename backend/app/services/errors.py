from fastapi import status


class ServiceError(Exception):
    """Business-rule violation; mapped to an HTTP (or WebSocket) error by the caller."""

    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFoundError(ServiceError):
    status_code = status.HTTP_404_NOT_FOUND


class ForbiddenError(ServiceError):
    status_code = status.HTTP_403_FORBIDDEN


class ConflictError(ServiceError):
    status_code = status.HTTP_409_CONFLICT
