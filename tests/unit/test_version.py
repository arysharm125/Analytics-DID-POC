"""Unit tests for app/version.py.

These tests verify the version string generation and git SHA extraction
without requiring actual git or metadata files.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.version import VERSION, full_version, get_git_sha


class TestGetGitSha:
    """Test get_git_sha() function."""

    def test_returns_short_sha_by_default(self):
        """Should return 6-character short SHA by default."""
        expected_sha = "abc123"
        mock_output = b"abc123\n"

        with patch('app.version.subprocess.check_output', return_value=mock_output) as mock_subprocess:
            result = get_git_sha()

            # Verify correct command was executed
            mock_subprocess.assert_called_once()
            cmd = mock_subprocess.call_args[0][0]
            assert cmd == ["git", "rev-parse", "--short=6", "HEAD"]

            # Verify result is stripped and decoded
            assert result == expected_sha

    def test_returns_short_sha_when_short_is_true(self):
        """Should return short SHA when explicitly set to True."""
        expected_sha = "def456"
        mock_output = b"def456\n"

        with patch('app.version.subprocess.check_output', return_value=mock_output) as mock_subprocess:
            result = get_git_sha(short=True)

            # Verify correct command was executed
            cmd = mock_subprocess.call_args[0][0]
            assert cmd == ["git", "rev-parse", "--short=6", "HEAD"]
            assert result == expected_sha

    def test_returns_full_sha_when_short_is_false(self):
        """Should return full SHA when short=False."""
        expected_sha = "abc123def456789012345678901234567890abcd"
        mock_output = b"abc123def456789012345678901234567890abcd\n"

        with patch('app.version.subprocess.check_output', return_value=mock_output) as mock_subprocess:
            result = get_git_sha(short=False)

            # Verify correct command was executed (no --short=6 flag)
            cmd = mock_subprocess.call_args[0][0]
            assert cmd == ["git", "rev-parse", "HEAD"]
            assert result == expected_sha

    def test_returns_empty_string_on_exception(self):
        """Should return empty string when git command fails."""
        with patch('app.version.subprocess.check_output', side_effect=Exception("Git not found")):
            result = get_git_sha()
            assert result == ""

    def test_returns_empty_string_on_subprocess_error(self):
        """Should return empty string on subprocess.CalledProcessError."""
        import subprocess

        with patch('app.version.subprocess.check_output',
                   side_effect=subprocess.CalledProcessError(128, "git")):
            result = get_git_sha()
            assert result == ""

    def test_uses_correct_working_directory(self):
        """Should execute git command in parent directory of version.py."""
        mock_output = b"abc123\n"

        with patch('app.version.subprocess.check_output', return_value=mock_output) as mock_subprocess:
            get_git_sha()

            # Verify cwd parameter is set to parent directory
            call_kwargs = mock_subprocess.call_args[1]
            assert 'cwd' in call_kwargs
            # cwd should be parent of app/version.py (i.e., project root)
            assert call_kwargs['cwd'] == Path(__file__).parent.parent.parent


class TestFullVersion:
    """Test full_version() function."""

    def test_without_metadata_file_with_git(self):
        """Should return version with 'local' tag and git SHA when no metadata file exists."""
        expected_sha = "abc123"

        # Mock metadata file as non-existent
        mock_path = MagicMock()
        mock_path.exists.return_value = False

        with patch('app.version.Path', return_value=mock_path), \
             patch('app.version.get_git_sha', return_value=expected_sha):

            result = full_version()

            assert result == f"{VERSION}-local+{expected_sha}"

    def test_without_metadata_file_without_git(self):
        """Should return version with 'local' tag only when git is unavailable."""
        # Mock metadata file as non-existent
        mock_path = MagicMock()
        mock_path.exists.return_value = False

        with patch('app.version.Path', return_value=mock_path), \
             patch('app.version.get_git_sha', return_value=""):

            result = full_version()

            assert result == f"{VERSION}-local"

    def test_with_metadata_file_containing_tag_and_sha(self):
        """Should load VERSION_TAG and GIT_SHA from metadata file."""
        expected_tag = "production"
        expected_sha = "def456"

        # Create a mock metadata module
        mock_metadata = MagicMock()
        mock_metadata.VERSION_TAG = expected_tag
        mock_metadata.GIT_SHA = expected_sha

        # Mock Path to indicate metadata file exists
        mock_path = MagicMock()
        mock_path.exists.return_value = True

        # Mock the import machinery
        mock_spec = MagicMock()
        mock_spec.loader = MagicMock()

        with patch('app.version.Path', return_value=mock_path), \
             patch('importlib.util.spec_from_file_location', return_value=mock_spec), \
             patch('importlib.util.module_from_spec', return_value=mock_metadata), \
             patch('app.version.get_git_sha', return_value=""):

            result = full_version()

            assert result == f"{VERSION}-{expected_tag}+{expected_sha}"

    def test_with_metadata_file_containing_only_tag(self):
        """Should use tag from metadata but git SHA when GIT_SHA is missing."""
        expected_tag = "staging"
        git_sha = "abc789"

        # Create a mock metadata module with only VERSION_TAG
        mock_metadata = MagicMock()
        mock_metadata.VERSION_TAG = expected_tag
        # Simulate missing GIT_SHA attribute
        del mock_metadata.GIT_SHA

        mock_path = MagicMock()
        mock_path.exists.return_value = True

        mock_spec = MagicMock()
        mock_spec.loader = MagicMock()

        with patch('app.version.Path', return_value=mock_path), \
             patch('importlib.util.spec_from_file_location', return_value=mock_spec), \
             patch('importlib.util.module_from_spec', return_value=mock_metadata), \
             patch('app.version.get_git_sha', return_value=git_sha):

            result = full_version()

            assert result == f"{VERSION}-{expected_tag}+{git_sha}"

    def test_git_sha_overrides_metadata_sha(self):
        """Git SHA should take precedence over metadata SHA when both exist."""
        metadata_sha = "old123"
        git_sha = "new456"

        # Create a mock metadata module
        mock_metadata = MagicMock()
        mock_metadata.VERSION_TAG = "production"
        mock_metadata.GIT_SHA = metadata_sha

        mock_path = MagicMock()
        mock_path.exists.return_value = True

        mock_spec = MagicMock()
        mock_spec.loader = MagicMock()

        with patch('app.version.Path', return_value=mock_path), \
             patch('importlib.util.spec_from_file_location', return_value=mock_spec), \
             patch('importlib.util.module_from_spec', return_value=mock_metadata), \
             patch('app.version.get_git_sha', return_value=git_sha):

            result = full_version()

            # Should use git SHA, not metadata SHA
            assert result == f"{VERSION}-production+{git_sha}"
            assert metadata_sha not in result

    def test_metadata_file_load_exception_gracefully_handled(self):
        """Should fall back to defaults if metadata file loading raises exception."""
        git_sha = "abc123"

        mock_path = MagicMock()
        mock_path.exists.return_value = True

        # Mock spec_from_file_location to raise an exception
        with patch('app.version.Path', return_value=mock_path), \
             patch('importlib.util.spec_from_file_location',
                   side_effect=Exception("Import error")), \
             patch('app.version.get_git_sha', return_value=git_sha):

            result = full_version()

            # Should fall back to default 'local' tag
            assert result == f"{VERSION}-local+{git_sha}"

    def test_empty_tag_not_included_in_version(self):
        """Empty tag should not add hyphen to version string."""
        git_sha = "abc123"

        # Create a mock metadata module with empty tag
        mock_metadata = MagicMock()
        mock_metadata.VERSION_TAG = ""
        mock_metadata.GIT_SHA = ""

        mock_path = MagicMock()
        mock_path.exists.return_value = True

        mock_spec = MagicMock()
        mock_spec.loader = MagicMock()

        with patch('app.version.Path', return_value=mock_path), \
             patch('importlib.util.spec_from_file_location', return_value=mock_spec), \
             patch('importlib.util.module_from_spec', return_value=mock_metadata), \
             patch('app.version.get_git_sha', return_value=git_sha):

            result = full_version()

            # Should not have tag prefix, but should have git SHA
            assert result == f"{VERSION}+{git_sha}"
            assert "-" not in result

    def test_version_constant_is_used(self):
        """Should use the VERSION constant from the module."""
        git_sha = "abc123"

        mock_path = MagicMock()
        mock_path.exists.return_value = False

        with patch('app.version.Path', return_value=mock_path), \
             patch('app.version.get_git_sha', return_value=git_sha):

            result = full_version()

            # Verify VERSION constant is in the result
            assert result.startswith(VERSION)
