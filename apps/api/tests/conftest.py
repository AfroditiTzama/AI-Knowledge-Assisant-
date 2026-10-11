import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-suite-signing-key-9f4b81c2d7e64350a2e8d6c1",
)

from knowledge_assistant.main import app  # noqa: E402


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield client
