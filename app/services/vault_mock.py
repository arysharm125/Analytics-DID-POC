"""
Mock Vault Client for local development without a real HashiCorp Vault server.

This module provides a file-system-based mock implementation of the hvac client,
storing secrets as JSON files on disk. It simulates KV v2 behavior.

Usage:
    Set VAULT_LOCAL_MOCK environment variable to a directory path where
    secrets will be stored. The init_vault_client() function in vault.py
    will automatically use this mock when the variable is set.
"""

import json
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import hvac.exceptions

logger = logging.getLogger("vault_mock")


class MockKVv2:
    """Mock implementation of hvac KV v2 secrets engine."""

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir)

    def _get_secret_path(self, mount_point: str, path: str) -> Path:
        """Get the filesystem path for a secret."""
        # Normalize path separators and remove leading/trailing slashes
        clean_path = path.strip("/").replace("/", os.sep)
        return self.root_dir / mount_point / clean_path / "secret.json"

    def _get_secret_dir(self, mount_point: str, path: str) -> Path:
        """Get the directory path for listing secrets."""
        clean_path = path.strip("/").replace("/", os.sep) if path else ""
        if clean_path:
            return self.root_dir / mount_point / clean_path
        return self.root_dir / mount_point

    def read_secret_version(
        self,
        path: str,
        mount_point: str = "secret",
        version: Optional[int] = None,
        raise_on_deleted_version: bool = True,
    ) -> Dict[str, Any]:
        """
        Read a secret from disk.

        Returns the same structure as hvac KV v2:
        {
            "data": {
                "data": {"key": "value", ...},
                "metadata": {"version": 1, "created_time": "...", ...}
            }
        }

        Raises hvac.exceptions.InvalidPath if the secret doesn't exist.
        """
        secret_path = self._get_secret_path(mount_point, path)

        if not secret_path.exists():
            logger.debug(f"Secret not found: {secret_path}")
            raise hvac.exceptions.InvalidPath(f"No secret at {mount_point}/{path}")

        try:
            with open(secret_path, "r") as f:
                stored = json.load(f)
            return stored
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in secret file {secret_path}: {e}")
            raise hvac.exceptions.InvalidPath(f"Corrupted secret at {mount_point}/{path}")

    def create_or_update_secret(
        self,
        path: str,
        secret: Dict[str, Any],
        mount_point: str = "secret",
        cas: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Create or update a secret on disk.

        Stores the secret in the same structure as hvac KV v2 would return.
        """
        secret_path = self._get_secret_path(mount_point, path)

        # Read existing version if present
        version = 1
        if secret_path.exists():
            try:
                with open(secret_path, "r") as f:
                    existing = json.load(f)
                version = existing.get("data", {}).get("metadata", {}).get("version", 0) + 1
            except (json.JSONDecodeError, KeyError):
                version = 1

        # Create directory structure
        secret_path.parent.mkdir(parents=True, exist_ok=True)

        # Build the response structure
        now = datetime.utcnow().isoformat() + "Z"
        stored = {
            "data": {
                "data": secret,
                "metadata": {
                    "version": version,
                    "created_time": now,
                    "deletion_time": "",
                    "destroyed": False,
                    "custom_metadata": None,
                },
            },
            "lease_duration": 0,
            "lease_id": "",
            "renewable": False,
            "request_id": f"mock-{datetime.utcnow().timestamp()}",
            "wrap_info": None,
            "warnings": None,
            "auth": None,
        }

        with open(secret_path, "w") as f:
            json.dump(stored, f, indent=2)

        logger.debug(f"Wrote secret to {secret_path} (version {version})")
        return stored

    def list_secrets(
        self, path: str = "", mount_point: str = "secret"
    ) -> Dict[str, Any]:
        """
        List secrets at a given path.

        Returns structure matching hvac:
        {"data": {"keys": ["key1", "key2/", ...]}}

        Keys ending with "/" are subdirectories.
        """
        list_dir = self._get_secret_dir(mount_point, path)

        if not list_dir.exists():
            raise hvac.exceptions.InvalidPath(f"No secrets at {mount_point}/{path}")

        keys: List[str] = []
        try:
            for entry in list_dir.iterdir():
                if entry.is_dir():
                    # Check if this is a secret directory (contains secret.json)
                    # or a path component (contains subdirectories)
                    if (entry / "secret.json").exists():
                        keys.append(entry.name)
                    else:
                        # It's a path prefix, append with trailing slash
                        keys.append(entry.name + "/")
        except PermissionError as e:
            logger.error(f"Permission denied listing {list_dir}: {e}")
            raise hvac.exceptions.InvalidPath(f"Cannot list {mount_point}/{path}")

        return {
            "data": {"keys": sorted(keys)},
            "lease_duration": 0,
            "lease_id": "",
            "renewable": False,
            "request_id": f"mock-{datetime.utcnow().timestamp()}",
            "wrap_info": None,
            "warnings": None,
            "auth": None,
        }

    def delete_metadata_and_all_versions(
        self, path: str, mount_point: str = "secret"
    ) -> None:
        """
        Delete a secret and all its versions (and metadata).

        In the mock, this removes the secret.json file and its parent
        directory if empty.
        """
        secret_path = self._get_secret_path(mount_point, path)
        secret_dir = secret_path.parent

        if secret_path.exists():
            secret_path.unlink()
            logger.debug(f"Deleted secret: {secret_path}")

        # Clean up empty parent directories
        try:
            if secret_dir.exists() and not any(secret_dir.iterdir()):
                secret_dir.rmdir()
                logger.debug(f"Removed empty directory: {secret_dir}")
        except OSError:
            pass  # Directory not empty or other issue, ignore


class MockKVv1:
    """
    Mock implementation of hvac KV v1 secrets engine.

    Since we always behave as v2, this is a thin wrapper that delegates to v2.
    """

    def __init__(self, kv_v2: MockKVv2):
        self._v2 = kv_v2

    def read_secret(
        self, path: str, mount_point: str = "secret"
    ) -> Dict[str, Any]:
        """Read a secret (v1 style response)."""
        result = self._v2.read_secret_version(path=path, mount_point=mount_point)
        # v1 returns data directly under "data", not nested
        return {"data": result.get("data", {}).get("data", {})}

    def create_or_update_secret(
        self, path: str, secret: Dict[str, Any], mount_point: str = "secret"
    ) -> Dict[str, Any]:
        """Create or update a secret."""
        return self._v2.create_or_update_secret(
            path=path, secret=secret, mount_point=mount_point
        )

    def list_secrets(
        self, path: str = "", mount_point: str = "secret"
    ) -> Dict[str, Any]:
        """List secrets at a path."""
        return self._v2.list_secrets(path=path, mount_point=mount_point)


class MockKV:
    """Mock KV secrets engine container."""

    def __init__(self, root_dir: str):
        self.v2 = MockKVv2(root_dir)
        self.v1 = MockKVv1(self.v2)


class MockSecrets:
    """Mock secrets engines container."""

    def __init__(self, root_dir: str):
        self.kv = MockKV(root_dir)


class MockSys:
    """Mock system backend."""

    def __init__(self, root_dir: str, default_mount: str = "secret"):
        self.root_dir = Path(root_dir)
        self.default_mount = default_mount

    def list_mounted_secrets_engines(self) -> Dict[str, Any]:
        """
        Return mock mounted secrets engines.

        Always returns the default mount as KV v2.
        """
        return {
            "data": {
                f"{self.default_mount}/": {
                    "type": "kv",
                    "description": "Mock KV secrets engine",
                    "options": {"version": "2"},
                    "accessor": "mock_accessor",
                    "config": {
                        "default_lease_ttl": 0,
                        "force_no_cache": False,
                        "max_lease_ttl": 0,
                    },
                    "local": False,
                    "seal_wrap": False,
                    "external_entropy_access": False,
                }
            }
        }


class MockVaultClient:
    """
    Mock hvac Vault client for local development.

    This class mimics the structure of hvac.Client, storing secrets
    as JSON files on the local filesystem.

    Usage:
        client = MockVaultClient(root_dir="/tmp/vault_mock")
        client.secrets.kv.v2.create_or_update_secret(
            mount_point="secret",
            path="my/secret",
            secret={"key": "value"}
        )
    """

    def __init__(self, root_dir: str, default_mount: str = "secret"):
        """
        Initialize the mock Vault client.

        Args:
            root_dir: Directory where secrets will be stored on disk.
            default_mount: Default mount point name for KV engine.
        """
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

        self.sys = MockSys(root_dir, default_mount)
        self.secrets = MockSecrets(root_dir)

        logger.info(f"MockVaultClient initialized with root: {self.root_dir}")

    def is_authenticated(self) -> bool:
        """Always returns True for the mock client."""
        return True
