"""Tests for auth.py — 5 tests."""

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from clinemcp.mcp.auth import get_auth_token, verify_token


class TestTokenLoading:
    """test_token_loaded_from_env"""

    @patch.dict(os.environ, {"CLINEMCP_AUTH_TOKEN": "test-token-123"}, clear=True)
    def test_token_loaded_from_env(self):
        token = get_auth_token()
        assert token == "test-token-123"


class TestValidToken:
    """test_valid_token_passes"""

    @patch.dict(os.environ, {"CLINEMCP_AUTH_TOKEN": "valid-token"}, clear=True)
    def test_valid_token_passes(self):
        request = MagicMock(spec=Request)
        request.headers = {"Authorization": "Bearer valid-token"}
        assert verify_token(request) is True


class TestInvalidToken:
    """test_invalid_token_returns_401"""

    @patch.dict(os.environ, {"CLINEMCP_AUTH_TOKEN": "valid-token"}, clear=True)
    def test_invalid_token_returns_false(self):
        request = MagicMock(spec=Request)
        request.headers = {"Authorization": "Bearer wrong-token"}
        assert verify_token(request) is False


class TestMissingToken:
    """test_missing_token_returns_401"""

    @patch.dict(os.environ, {"CLINEMCP_AUTH_TOKEN": "valid-token"}, clear=True)
    def test_missing_token_returns_false(self):
        request = MagicMock(spec=Request)
        request.headers = {}
        assert verify_token(request) is False

    @patch.dict(os.environ, {"CLINEMCP_AUTH_TOKEN": "valid-token"}, clear=True)
    def test_no_bearer_prefix_returns_false(self):
        request = MagicMock(spec=Request)
        request.headers = {"Authorization": "valid-token"}  # No "Bearer " prefix
        assert verify_token(request) is False


class TestNoTokenConfigured:
    """When no token is configured, allow all."""

    @patch.dict(os.environ, {}, clear=True)
    def test_no_token_configured_allows_all(self):
        request = MagicMock(spec=Request)
        request.headers = {}
        assert verify_token(request) is True
