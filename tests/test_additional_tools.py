import unittest
from unittest.mock import Mock, patch
from agent.tools.agent_tools import (
    KiwixQueryTool, WebSearchTool, UrlFetchTool, RagSearchTool,
    TerminalTool, SystemdTool, PackageTool, SkillTool,
    GitHubSearchTool, GitHubFetchTool
)
from agent.models import Source, SourceType


class TestWebTools(unittest.TestCase):
    """Test web-related tools"""

    @patch('agent.tools.agent_tools.ddgs')
    def test_web_search_tool_success(self, mock_ddgs):
        """Test WebSearchTool executes successfully"""
        mock_ddgs.DDGS.return_value = Mock(
            __enter__=Mock(return_value=Mock(
                text=iter([
                    {"href": "http://test.com", "title": "Test", "body": "Test content"}
                ])
            ))
        )

        tool = WebSearchTool()
        result = tool.execute(query="test query", max_results=5)

        self.assertTrue(result.ok)
        self.assertIsInstance(result.data, list)
        self.assertEqual(len(result.sources), 1)
        self.assertEqual(result.sources[0].source_type, SourceType.WEB)

    @patch('trafilatura.fetch_url')
    @patch('trafilatura.extract')
    def test_url_fetch_tool_success(self, mock_extract, mock_fetch):
        """Test UrlFetchTool fetches content successfully"""
        mock_fetch.return_value = "fetched content"
        mock_extract.return_value = "extracted content"

        tool = UrlFetchTool()
        result = tool.execute(url="http://example.com", max_length=2000)

        self.assertTrue(result.ok)
        self.assertEqual(result.data, "extracted content")
        self.assertEqual(len(result.sources), 1)
        self.assertEqual(result.sources[0].source_type, SourceType.WEB)

    @patch('trafilatura.fetch_url')
    def test_url_fetch_tool_invalid_scheme(self, mock_fetch):
        """Test UrlFetchTool rejects non-HTTP URLs"""
        tool = UrlFetchTool()
        result = tool.execute(url="ftp://example.com")

        self.assertFalse(result.ok)
        self.assertIn("Invalid URL scheme", result.error)

    @patch('agent.rag.search')
    @patch('agent.manifest.load_manifest')
    def test_rag_search_tool_success(self, mock_manifest, mock_search):
        """Test RagSearchTool searches local index"""
        mock_manifest.return_value = Mock()
        mock_search.return_value = [
            Mock(source="file1.py", ref="ref1", text="content1", chunk_id="chunk1")
        ]

        tool = RagSearchTool()
        result = tool.execute(query="test query", max_results=3)

        self.assertTrue(result.ok)
        self.assertIsInstance(result.data, list)


class TestSystemTools(unittest.TestCase):
    """Test system management tools"""

    @patch('subprocess.run')
    def test_terminal_tool_success(self, mock_run):
        """Test TerminalTool executes commands successfully"""
        mock_run.return_value = Mock(stdout="output", stderr="", returncode=0)

        tool = TerminalTool()
        result = tool.execute(command="ls", timeout=30)

        self.assertTrue(result.ok)
        self.assertEqual(result.data["stdout"], "output")
        self.assertEqual(result.data["returncode"], 0)

    @patch('subprocess.run')
    def test_terminal_tool_blocked_command(self, mock_run):
        """Test TerminalTool blocks dangerous commands"""
        tool = TerminalTool()
        result = tool.execute(command="rm -rf /")

        self.assertFalse(result.ok)
        self.assertIn("blocked operation", result.error)

    @patch('subprocess.run')
    def test_terminal_tool_success_basic(self, mock_run):
        """Test TerminalTool executes basic command successfully"""
        mock_run.return_value = Mock(stdout="output", stderr="", returncode=0)

        tool = TerminalTool()
        result = tool.execute(command="ls", timeout=30)

        self.assertTrue(result.ok)
        self.assertEqual(result.data["stdout"], "output")

    @patch('subprocess.run')
    def test_systemd_tool_status(self, mock_run):
        """Test SystemdTool gets service status"""
        mock_run.return_value = Mock(stdout="● service.service - running", stderr="", returncode=0)

        tool = SystemdTool()
        result = tool.execute(action="status", service="my-service")

        self.assertTrue(result.ok)
        self.assertIn("service.service", result.data["stdout"])

    @patch('subprocess.run')
    def test_systemd_tool_invalid_action(self, mock_run):
        """Test SystemdTool rejects invalid actions"""
        tool = SystemdTool()
        result = tool.execute(action="destroy", service="my-service")

        self.assertFalse(result.ok)
        self.assertIn("Invalid action", result.error)

    @patch('shutil.which')
    @patch('subprocess.run')
    def test_package_tool_apt(self, mock_run, mock_which):
        """Test PackageTool with apt package manager"""
        mock_which.return_value = "/usr/bin/apt"
        mock_run.return_value = Mock(stdout="Package installed", stderr="", returncode=0)

        tool = PackageTool()
        result = tool.execute(action="install", package="test-package")

        self.assertTrue(result.ok)
        self.assertIn("installed", result.data["stdout"])


class TestGitHubTools(unittest.TestCase):
    """Test GitHub integration tools"""

    @patch('httpx.Client.get')
    def test_github_search_repos(self, mock_get):
        """Test GitHubSearchTool searches repositories"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "items": [
                {"full_name": "test/repo1", "html_url": "http://github.com/test/repo1", "description": "Test repo 1", "stargazers_count": 100},
                {"full_name": "test/repo2", "html_url": "http://github.com/test/repo2", "description": "Test repo 2", "stargazers_count": 50}
            ]
        }
        mock_get.return_value = mock_response

        tool = GitHubSearchTool()
        result = tool.execute(query="test query", search_type="repositories", max_results=5)

        self.assertTrue(result.ok)
        self.assertEqual(len(result.data), 2)
        self.assertEqual(len(result.sources), 2)
        self.assertEqual(result.sources[0].source_type, SourceType.WEB)

    @patch('httpx.Client.get')
    def test_github_fetch_file(self, mock_get):
        """Test GitHubFetchTool fetches file content"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "encoding": "base64",
            "content": "SGVsbG8gV29ybGQ=",
            "sha": "abc123"
        }
        mock_get.return_value = mock_response

        tool = GitHubFetchTool()
        result = tool.execute(repo="test/repo", path="README.md", ref="main")

        self.assertTrue(result.ok)
        self.assertIn("content", result.data)
        self.assertEqual(result.data["content"], "Hello World")
        self.assertEqual(len(result.sources), 1)

    @patch('httpx.Client.get')
    def test_github_fetch_directory(self, mock_get):
        """Test GitHubFetchTool lists directory"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"name": "file1.txt", "type": "file", "path": "file1.txt"},
            {"name": "dir1", "type": "dir", "path": "dir1"}
        ]
        mock_get.return_value = mock_response

        tool = GitHubFetchTool()
        result = tool.execute(repo="test/repo", path="src/", ref="main")

        self.assertTrue(result.ok)
        self.assertIn("contents", result.data)
        self.assertEqual(result.data["type"], "directory")


class TestSkillTool(unittest.TestCase):
    """Test SkillTool for loading skill files"""

    @patch('pathlib.Path.read_text')
    @patch('pathlib.Path.exists')
    def test_skill_tool_success(self, mock_exists, mock_read):
        """Test SkillTool loads skill file successfully"""
        mock_exists.return_value = True
        mock_read.return_value = "# Skill content\n\nThis is a test skill."

        tool = SkillTool()
        result = tool.execute(name="test_skill")

        self.assertTrue(result.ok)
        self.assertIn("Skill content", result.data)

    def test_skill_tool_path_traversal_blocked(self):
        """Test SkillTool blocks path traversal"""
        tool = SkillTool()
        result = tool.execute(name="../../../etc/passwd")

        self.assertFalse(result.ok)
        self.assertIn("path traversal", result.error)

    @patch('pathlib.Path.exists')
    def test_skill_tool_not_found(self, mock_exists):
        """Test SkillTool handles missing skill files"""
        mock_exists.return_value = False

        tool = SkillTool()
        result = tool.execute(name="nonexistent_skill")

        self.assertFalse(result.ok)
        self.assertIn("not found", result.error)


if __name__ == "__main__":
    unittest.main()
