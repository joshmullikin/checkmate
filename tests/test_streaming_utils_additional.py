import pytest
from sqlalchemy.exc import SQLAlchemyError
from unittest.mock import AsyncMock, MagicMock, patch

from api.utils.streaming import streaming_context


@pytest.mark.asyncio
async def test_streaming_context_rolls_back_on_sqlalchemy_error():
    with patch("api.utils.streaming.Session") as mock_session_class, patch(
        "api.utils.streaming.PlaywrightExecutorClient"
    ) as mock_client_class, patch("api.utils.streaming.test_executor_connection") as mock_test_conn:
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        mock_test_conn.return_value = True

        with pytest.raises(SQLAlchemyError):
            async with streaming_context():
                raise SQLAlchemyError("db broke")

        mock_session.rollback.assert_called_once()
        mock_client.close.assert_awaited_once()
        mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_streaming_context_closes_resources_when_commit_fails():
    with patch("api.utils.streaming.Session") as mock_session_class, patch(
        "api.utils.streaming.PlaywrightExecutorClient"
    ) as mock_client_class, patch("api.utils.streaming.test_executor_connection") as mock_test_conn:
        mock_session = MagicMock()
        mock_session.commit.side_effect = RuntimeError("commit failed")
        mock_session_class.return_value = mock_session

        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        mock_test_conn.return_value = True

        with pytest.raises(RuntimeError, match="commit failed"):
            async with streaming_context():
                pass

        mock_session.rollback.assert_called_once()
        mock_client.close.assert_awaited_once()
        mock_session.close.assert_called_once()
