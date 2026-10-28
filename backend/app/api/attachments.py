from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser
from app.core.db import SessionDep
from app.core.security import verify_attachment_signature
from app.models import Attachment
from app.schemas.message import AttachmentRead
from app.services import attachments as attachments_service
from app.services import storage

router = APIRouter(tags=["attachments"])


@router.post(
    "/chats/{chat_id}/attachments",
    response_model=AttachmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    chat_id: int, file: UploadFile, session: SessionDep, user: CurrentUser
) -> Attachment:
    """Upload first, then send a message with the returned id in attachment_ids."""
    return await attachments_service.upload(session, chat_id, user.id, file)


@router.get("/attachments/{attachment_id}/{filename}")
async def download_attachment(
    attachment_id: int,
    filename: str,
    session: SessionDep,
    expires: Annotated[int, Query()],
    signature: Annotated[str, Query(max_length=64)],
) -> FileResponse:
    """Authorized by the signed link from the message (so <img src> works without headers)."""
    if not verify_attachment_signature(attachment_id, expires, signature):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid or expired link")
    attachment = await attachments_service.get(session, attachment_id)
    path = storage.path_for(attachment.storage_key)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")

    is_image = AttachmentRead.model_validate(attachment).is_image
    return FileResponse(
        path,
        media_type=attachment.content_type if is_image else "application/octet-stream",
        filename=attachment.filename,
        content_disposition_type="inline" if is_image else "attachment",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=86400",
        },
    )
