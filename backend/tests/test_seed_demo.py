from httpx import AsyncClient

from app.core.db import SessionFactory
from app.scripts.seed_demo import DEMO_PASSWORD, seed


async def test_demo_data_shows_off_every_feature(client: AsyncClient) -> None:
    async with SessionFactory() as session:
        await seed(session)

    login = await client.post(
        "/api/auth/login", json={"username": "alice", "password": DEMO_PASSWORD}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    chats = {
        c["title"] or c["type"]: c for c in (await client.get("/api/chats", headers=headers)).json()
    }

    assert chats["Учёба"]["muted"] is True
    assert chats["Учёба"]["unread_count"] == 2
    assert chats["Команда проекта"]["unread_count"] == 0
    archive = chats["Архив курса"]
    assert archive["unread_count"] == 0
    page = (await client.get(f"/api/chats/{archive['id']}/messages", headers=headers)).json()
    assert page["has_more"] is True

    team = chats["Команда проекта"]
    history = (await client.get(f"/api/chats/{team['id']}/messages", headers=headers)).json()[
        "items"
    ]
    assert any(m["reply_to"] for m in history)
    assert any(m["reactions"] for m in history)
    assert any(m["edited_at"] for m in history)
    assert any(m["deleted"] for m in history)
    assert any(m["mention_user_ids"] for m in history)
    images = [a for m in history for a in m["attachments"] if a["is_image"]]
    assert images
    image = await client.get(images[0]["url"])
    assert image.status_code == 200
    assert image.content.startswith(b"\x89PNG")
