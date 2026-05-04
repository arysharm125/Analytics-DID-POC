import subprocess
from pathlib import Path

VERSION = "1.1.0"

def get_git_sha(short: bool = True) -> str:
    """Get the current git commit SHA.

    Args:
        short: If True, return short SHA (6 chars), else full SHA

    Returns:
        Git SHA string, or an empty string if git is unavailable
    """
    try:
        cmd = ["git", "rev-parse"]
        if short:
            cmd.append("--short=6")
        cmd.append("HEAD")

        sha = subprocess.check_output(
            cmd,
            stderr=subprocess.DEVNULL,
            cwd=Path(__file__).parent.parent
        ).decode().strip()
        return sha
    except Exception:
        return ""

def full_version() -> str:
        """
        Returns the full version string (version + build metadata).
        """
        # Default values
        tag = "local"
        sha = ""

        # Try to load version_metadata.py (created during Docker builds)
        metadata_file = Path(__file__).parent / "version_metadata.py"
        if metadata_file.exists():
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location("version_metadata", metadata_file)
                if spec and spec.loader:
                    version_metadata = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(version_metadata)

                    # Extract VERSION_TAG if available
                    if hasattr(version_metadata, "VERSION_TAG"):
                        tag = version_metadata.VERSION_TAG

                    # Extract GIT_SHA if available
                    if hasattr(version_metadata, "GIT_SHA"):
                        sha = version_metadata.GIT_SHA
            except Exception:
                pass

        # If running directly off a git repo, extract the current commit hash
        # (this overrides metadata SHA if both are available)
        git_sha = get_git_sha()
        if git_sha:
            sha = git_sha

        tag = f"-{tag}" if tag else ""
        sha = f"+{sha}" if sha else ""
        return f"{VERSION}{tag}{sha}"
