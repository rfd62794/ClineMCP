"""Tests for telegram.py — 5 tests from SDD §11."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from clinemcp.telegram import send_message, TELEGRAM_API_URL


class TestSendMessage:
    """Tests for send_message."""

    @pytest.mark.asyncio
    async def test_send_message_returns_true_on_200(self):
        """Verify True returned on 200 response."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client), patch.dict(
            os.environ, {"TELEGRAM_BOT_TOKEN": "test_token", "TELEGRAM_CHAT_ID": "123456"}
        ):
            # Need to reimport to pick up env vars
            import importlib
            import clinemcp.telegram as telegram_module

            importlib.reload(telegram_module)

            result = await telegram_module.send_message("Test message")
            assert result is True

    @pytest.mark.asyncio
    async def test_send_message_returns_false_when_token_missing(self):
        """Verify False when TELEGRAM_BOT_TOKEN not set."""
        with patch.dict(os.environ, {}, clear=True):
            import importlib
            import clinemcp.telegram as telegram_module

            importlib.reload(telegram_module)

            result = await telegram_module.send_message("Test message")
            assert result is False

    @pytest.mark.asyncio
    async def test_send_message_returns_false_on_http_error(self):
        """Verify False on HTTP error."""
        mock_response = MagicMock()
        mock_response.status_code = 403

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client), patch.dict(
            os.environ, {"TELEGRAM_BOT_TOKEN": "test_token", "TELEGRAM_CHAT_ID": "123456"}
        ):
            import importlib
            import clinemcp.telegram as telegram_module

            importlib.reload(telegram_module)

            result = await telegram_module.send_message("Test message")
            assert result is False

    @pytest.mark.asyncio
    async def test_send_message_retries_without_parse_mode(self):
        """Verify retry without parse_mode on 400 error."""
        mock_response_400 = MagicMock()
        mock_response_400.status_code = 400

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        # First call returns 400, second returns 200
        mock_client.post = AsyncMock(side_effect=[mock_response_400, mock_response_200])

        with patch("httpx.AsyncClient", return_value=mock_client), patch.dict(
            os.environ, {"TELEGRAM_BOT_TOKEN": "test_token", "TELEGRAM_CHAT_ID": "123456"}
        ):
            import importlib
            import clinemcp.telegram as telegram_module

            importlib.reload(telegram_module)

            result = await telegram_module.send_message("Test <b>message</b>")
            assert result is True
            # Verify two POST calls were made
            assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_send_message_never_raises(self):
        """Verify no exception raised even on failure."""
        with patch("httpx.AsyncClient", side_effect=Exception("Network error")), patch.dict(
            os.environ, {"TELEGRAM_BOT_TOKEN": "test_token", "TELEGRAM_CHAT_ID": "123456"}
        ):
            import importlib
            import clinemcp.telegram as telegram_module

            importlib.reload(telegram_module)

            # Should not raise
            result = await telegram_module.send_message("Test message")
            assert result is False
