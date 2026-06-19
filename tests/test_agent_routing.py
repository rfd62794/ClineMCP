"""Tests for agent_type routing — 5 tests from Phase 5 directive."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clinemcp.clinerules import ensure_clinerules, resolve_model


class TestAgentRouting:
    """Tests for agent_type routing config and model resolution."""

    def test_agent_type_routes_to_correct_model(self, tmp_path):
        """code_transformation maps to groq model string."""
        routing_yaml = tmp_path / "agent_routing.yaml"
        routing_yaml.write_text(
            "code_transformation:\n"
            "  model: groq/llama-3.1-70b-versatile\n"
            "  clinerules_template: templates/code_transformation.md\n"
            "default:\n"
            "  model: anthropic/claude-haiku-4-5-20251001\n"
            "  clinerules_template: null\n",
            encoding="utf-8",
        )

        with patch("clinemcp.clinerules.ROUTING_CONFIG_PATH", routing_yaml):
            model = resolve_model(agent_type="code_transformation")

        assert model == "groq/llama-3.1-70b-versatile"

    def test_unknown_agent_type_uses_default(self, tmp_path):
        """Unknown type falls back silently to default."""
        routing_yaml = tmp_path / "agent_routing.yaml"
        routing_yaml.write_text(
            "code_transformation:\n"
            "  model: groq/llama-3.1-70b-versatile\n"
            "default:\n"
            "  model: anthropic/claude-haiku-4-5-20251001\n"
            "  clinerules_template: null\n",
            encoding="utf-8",
        )

        with patch("clinemcp.clinerules.ROUTING_CONFIG_PATH", routing_yaml):
            model = resolve_model(agent_type="totally_unknown_type")

        assert model == "anthropic/claude-haiku-4-5-20251001"

    def test_explicit_model_overrides_agent_type(self, tmp_path):
        """model param takes priority over agent_type."""
        routing_yaml = tmp_path / "agent_routing.yaml"
        routing_yaml.write_text(
            "code_transformation:\n"
            "  model: groq/llama-3.1-70b-versatile\n"
            "default:\n"
            "  model: anthropic/claude-haiku-4-5-20251001\n"
            "  clinerules_template: null\n",
            encoding="utf-8",
        )

        with patch("clinemcp.clinerules.ROUTING_CONFIG_PATH", routing_yaml):
            model = resolve_model(model="my-custom-model", agent_type="code_transformation")

        assert model == "my-custom-model"

    def test_clinerules_template_prepends_to_repo_rules(self, tmp_path):
        """Template first, repo rules below separator."""
        # Create a fake routing config pointing to a template
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        template_file = template_dir / "code_transformation.md"
        template_file.write_text("# Template Rules\nRule A\nRule B\n", encoding="utf-8")

        routing_yaml = tmp_path / "agent_routing.yaml"
        routing_yaml.write_text(
            "code_transformation:\n"
            "  model: groq/llama-3.1-70b-versatile\n"
            "  clinerules_template: templates/code_transformation.md\n"
            "default:\n"
            "  model: anthropic/claude-haiku-4-5-20251001\n"
            "  clinerules_template: null\n",
            encoding="utf-8",
        )

        # Create a fake repo with existing .clinerules
        repo = tmp_path / "myrepo"
        repo.mkdir()
        existing_rules = repo / ".clinerules"
        existing_rules.write_text("# Repo Rules\nRepo specific rule\n", encoding="utf-8")

        # Patch both the routing config path and the template base path
        with (
            patch("clinemcp.clinerules.ROUTING_CONFIG_PATH", routing_yaml),
            patch("clinemcp.clinerules.get_clinerules_template_path", return_value=template_file),
        ):
            result = ensure_clinerules(str(repo), agent_type="code_transformation")

        assert result["error"] is None
        content = result["content"]
        # Template comes first
        assert content.startswith("# Template Rules")
        # Separator present
        assert "\n---\n" in content
        # Repo rules come after separator
        separator_idx = content.index("---")
        repo_section = content[separator_idx:]
        assert "Repo specific rule" in repo_section

    def test_null_template_leaves_repo_clinerules_unchanged(self, tmp_path):
        """No template = no modification to existing file."""
        routing_yaml = tmp_path / "agent_routing.yaml"
        routing_yaml.write_text(
            "default:\n"
            "  model: anthropic/claude-haiku-4-5-20251001\n"
            "  clinerules_template: null\n",
            encoding="utf-8",
        )

        # Create a fake repo with existing .clinerules
        repo = tmp_path / "myrepo"
        repo.mkdir()
        original_content = "# Existing Repo Rules\nDo not change me\n"
        existing_rules = repo / ".clinerules"
        existing_rules.write_text(original_content, encoding="utf-8")

        with patch("clinemcp.clinerules.ROUTING_CONFIG_PATH", routing_yaml):
            result = ensure_clinerules(str(repo), agent_type="default")

        assert result["error"] is None
        assert result["existed"] is True
        # Content unchanged
        assert result["content"] == original_content
        # File on disk unchanged
        assert existing_rules.read_text(encoding="utf-8") == original_content
