import mimetypes

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Attachment
from app.services import storage
from app.services.chats import require_membership
from app.services.errors import NotFoundError, PayloadTooLargeError, ServiceError


async def upload(
    session: AsyncSession, chat_id: int, uploader_id: int, file: UploadFile
) -> Attachment:
    """Stores the file; it is attached to a message when that message is sent."""
    await require_membership(session, chat_id, uploader_id)
    if file.size is None or file.size == 0:
        raise ServiceError("Empty file")
    if file.size > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes // (1024 * 1024)
        raise PayloadTooLargeError(f"File is too large (max {limit_mb} MB)")

    filename = (file.filename or "file").replace("/", "_").replace("\\", "_")[-255:]
    content_type = (
        file.content_type
        if file.content_type and file.content_type != "application/octet-stream"
        else mimetypes.guess_type(filename)[0]
    ) or "application/octet-stream"

    key = storage.new_key()
    await storage.save(key, file.file)
    attachment = Attachment(
        chat_id=chat_id,
        uploader_id=uploader_id,
        storage_key=key,
        filename=filename,
        content_type=content_type[:127],
        size=file.size,
    )
    session.add(attachment)
    try:
        await session.commit()
    except Exception:
        storage.remove_files([key])
        raise
    return attachment


async def get(session: AsyncSession, attachment_id: int) -> Attachment:
    attachment = await session.get(Attachment, attachment_id)
    if attachment is None:
        raise NotFoundError("Attachment not found")
    return attachment
