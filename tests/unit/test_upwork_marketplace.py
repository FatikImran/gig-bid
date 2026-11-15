from unittest.mock import AsyncMock

import pytest

from agent.upwork_marketplace import UpworkMarketplaceError, UpworkMCPAdapter


@pytest.mark.asyncio
async def test_job_detail_accepts_nested_posting_without_a_repeated_id(monkeypatch):
    adapter = UpworkMCPAdapter(client=None)
    operation = AsyncMock(
        return_value={
            "connects_cost": 10,
            "applied": False,
            "data": {
                "marketplaceJobPosting": {
                    "id": "1234",
                    "url": "https://www.upwork.com/jobs/sample",
                    "content": {"title": "Sample posting", "description": "Sample scope"},
                }
            },
        }
    )
    monkeypatch.setattr(adapter, "_operation", operation)

    detail = await adapter.get_job("1234")

    operation.assert_awaited_once_with("find_jobs", "get", {"id": "1234"})
    assert detail["job_id"] == "1234"
    assert detail["title"] == "Sample posting"
    assert detail["description"] == "Sample scope"
    assert detail["connects_cost"] == 10
    assert detail["upwork_url"] == "https://www.upwork.com/jobs/sample"


@pytest.mark.asyncio
async def test_invalid_detail_diagnostic_excludes_values(monkeypatch):
    adapter = UpworkMCPAdapter(client=None)
    monkeypatch.setattr(
        adapter,
        "_operation",
        AsyncMock(
            return_value={
                "data": {
                    "marketplaceJobPosting": {"content": {"description": "private example text"}}
                },
                "client": {"title": "private client title"},
            }
        ),
    )

    with pytest.raises(
        UpworkMarketplaceError, match=r"data\.marketplaceJobPosting\.content: description"
    ) as error:
        await adapter.get_job("1234")
    assert "private" not in str(error.value)
