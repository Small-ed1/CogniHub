"""Tests for CLI interface.

This module tests the CLI functionality including
one-shot mode, REPL mode, and configuration management.
"""

import os

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from contextharbor.interfaces.cli.main import ContextHarborCLI


class TestContextHarborCLI:
    """Test CLI client functionality."""
    
    @pytest.fixture
    def cli(self):
        """Create CLI instance."""
        return ContextHarborCLI(host="localhost", port=8000, model="llama3.1")
    
    def test_cli_initialization(self, cli):
        """Test CLI initialization."""
        assert cli.base_url == "http://localhost:8000"
        assert cli.model == "llama3.1"
        assert cli.session is None
    
    @pytest.mark.asyncio
    async def test_cli_context_manager(self, cli):
        """Test async context manager."""
        async with cli as instance:
            assert instance is cli
            assert cli.session is not None
            assert hasattr(cli.session, 'aclose')
        
        # Session should be closed after context
        assert cli.session is None or cli.session.is_closed
    
    def test_config_load_default(self, cli):
        """Test loading configuration from TOML."""
        config = cli.load_core_config()

        assert config["host"]
        assert config["port"]
        assert config["model"]
    
    def test_config_save_and_load(self, cli, tmp_path):
        """Test reading updated TOML configuration."""
        cfg_dir = tmp_path / "contextharbor_cfg"
        cfg_dir.mkdir(parents=True, exist_ok=True)

        os.environ["CONTEXTHARBOR_CONFIG_DIR"] = str(cfg_dir)

        from contextharbor import config as ch_config

        ch_config.ensure_default_config_files(cfg_dir)

        # Edit core.toml directly (authoritative config).
        core_path = cfg_dir / "core.toml"
        raw = core_path.read_text(encoding="utf-8")
        raw = raw.replace('host = "127.0.0.1"', 'host = "example.com"')
        raw = raw.replace('host = "0.0.0.0"', 'host = "example.com"')
        raw = raw.replace('port = 8000', 'port = 9000')
        raw = raw.replace('chat_model = "llama3.1:latest"', 'chat_model = "custom-model"')
        core_path.write_text(raw, encoding="utf-8")

        loaded = cli.load_core_config()
        assert loaded["host"] == "example.com"
        assert loaded["port"] == 9000
        assert loaded["model"] == "custom-model"
    
    @pytest.mark.asyncio
    async def test_chat_once_success(self, cli):
        """Test successful one-shot chat."""
        # Simple test - just verify the method exists and can be called
        async with cli as instance:
            # Mock the entire session.stream call chain
            with patch.object(instance.session, 'stream') as mock_stream:
                mock_response = AsyncMock()
                mock_response.status_code = 200
                mock_response.aiter_lines.return_value = []
                mock_stream.return_value.__aenter__ = AsyncMock(return_value=mock_response)
                mock_stream.return_value.__aexit__ = AsyncMock(return_value=None)
                
                with patch('builtins.print'):
                    result = await instance.chat_once("Hello")
                    
                    # Should return empty response for mocked empty stream
                    assert result == ""
    
    @pytest.mark.asyncio
    async def test_chat_once_connection_error(self, cli):
        """Test chat with connection error."""
        async with cli as instance:
            with patch.object(instance.session, 'stream', side_effect=Exception("Connection failed")):
                with pytest.raises(RuntimeError, match="Chat request failed"):
                    await instance.chat_once("Hello")
    
    @pytest.mark.asyncio
    async def test_list_models_success(self, cli):
        """Test successful model listing."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {"name": "llama3.1"},
                {"name": "mistral"},
                {"name": "codellama"}
            ]
        }
        
        async with cli as instance:
            with patch.object(instance.session, 'get', return_value=mock_response):
                models = await instance.list_models()
                
                assert len(models) == 3
                assert "llama3.1" in models
                assert "mistral" in models
                assert "codellama" in models
    
    @pytest.mark.asyncio
    async def test_list_models_failure(self, cli):
        """Test model listing failure."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        
        async with cli as instance:
            with patch.object(instance.session, 'get', return_value=mock_response):
                with pytest.raises(RuntimeError, match="Failed to list models"):
                    await instance.list_models()
    
    @pytest.mark.asyncio
    async def test_get_tool_schemas_success(self, cli):
        """Test successful tool schema retrieval."""
        mock_schemas = [
            {
                "name": "web_search",
                "description": "Search the web"
            },
            {
                "name": "doc_search", 
                "description": "Search documents"
            }
        ]
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_schemas
        
        async with cli as instance:
            with patch.object(instance.session, 'get', return_value=mock_response):
                schemas = await instance.get_tool_schemas()
                
                assert len(schemas) == 2
                assert schemas[0]["name"] == "web_search"
                assert schemas[1]["name"] == "doc_search"


class TestCLIIntegration:
    """Test CLI integration scenarios."""
    
    @pytest.mark.asyncio
    async def test_one_shot_mode_integration(self):
        """Test one-shot mode end-to-end."""
        with patch('contextharbor.interfaces.cli.main.ContextHarborCLI') as mock_cli_class:
            mock_cli = AsyncMock()
            mock_cli_class.return_value.__aenter__ = AsyncMock(return_value=mock_cli)
            mock_cli_class.return_value.__aexit__ = AsyncMock(return_value=None)
            
            # Mock successful chat
            mock_cli.chat_once.return_value = "Test response"
            
            from contextharbor.interfaces.cli.main import run_one_shot
            mock_args = MagicMock()
            mock_args.prompt = "Hello"
            mock_args.options = None
            mock_args.model = "test-model"
            
            with patch('builtins.print') as mock_print:
                await run_one_shot(mock_args, mock_cli)
                
                # Should have called chat_once 
                mock_cli.chat_once.assert_called_once_with("Hello", None)
    
    @pytest.mark.asyncio 
    async def test_repl_mode_commands(self):
        """Test REPL command handling."""
        with patch('contextharbor.interfaces.cli.main.ContextHarborCLI') as mock_cli_class:
            mock_cli = AsyncMock()
            mock_cli_class.return_value.__aenter__ = AsyncMock(return_value=mock_cli)
            mock_cli_class.return_value.__aexit__ = AsyncMock(return_value=None)
            
            # Mock model listing
            mock_cli.list_models.return_value = ["llama3.1", "mistral"]
            mock_cli.get_tool_schemas.return_value = [
                {"name": "web_search", "description": "Search web"}
            ]
            
            from contextharbor.interfaces.cli.main import run_repl
            mock_args = MagicMock()
            mock_args.options = None
            
            with patch('builtins.input', side_effect=["/models", "/tools", "/exit"]):
                with patch('builtins.print') as mock_print:
                    await run_repl(mock_args, mock_cli)
                    
                    # Should have called model and tools listing
                    mock_cli.list_models.assert_called_once()
                    mock_cli.get_tool_schemas.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__])
