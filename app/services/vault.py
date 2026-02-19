from contextlib import contextmanager
from datetime import datetime, timedelta
import gc
import hvac
import secrets
import threading
import time
import logging
import hvac.exceptions
from typing import Any, Generator, List, Optional

from nacl.signing import SigningKey

from app.config import get_config

class InvalidPathException(Exception):
    """Raised when trying to read a path that does not exist."""
    path: str
    mount_point : str

    def __init__(self, path : str, mount_point : str) -> None:
        super().__init__(f"Unable to read ${mount_point}/${path}")
        self.path = path
        self.mount_point = mount_point

# ==========================
# Vault Client Init
# ==========================
logger = logging.getLogger("did_vault_api_sut")

# Lazy-initialized vault client
_vault_client: Optional[hvac.Client] = None
_vault_client_initialized: bool = False


def get_vault_config() -> tuple[str, str, str]:
    """Fetches Vault address, token, and mount path from lazy-loaded config."""
    config = get_config()
    return config.vault.addr, config.vault.token, config.vault.mount


def _init_vault_client() -> Any:
    """Initialize and return an authenticated hvac Vault client (or mock if local_mock_path is set).

    Returns:
        Either an hvac.Client or MockVaultClient, or None if initialization fails.
    """
    config = get_config()

    # Check if we should use the local mock instead of real Vault
    if config.vault.local_mock_path:
        from app.services.vault_mock import MockVaultClient

        logging.info(f"[INFO] Using local mock Vault at: {config.vault.local_mock_path}")
        return MockVaultClient(
            root_dir=config.vault.local_mock_path, default_mount=config.vault.mount
        )

    try:
        client = hvac.Client(url=config.vault.addr, token=config.vault.token)
        if client.is_authenticated():
            logging.info(f"[INFO] Vault connected: {config.vault.addr}")
        else:
            logging.warning(f"[WARN] Vault authentication failed: {config.vault.addr}")
        return client
    except Exception as e:
        logging.error(f"[ERROR] Vault client initialization failed: {e}")
        return None


def get_vault_client() -> Any:
    """Get the vault client, initializing it lazily if needed.

    Returns:
        Either an hvac.Client or MockVaultClient, or None if initialization fails.
    """
    global _vault_client, _vault_client_initialized
    if not _vault_client_initialized:
        _vault_client = _init_vault_client()
        _vault_client_initialized = True
    return _vault_client


def reset_vault_client() -> None:
    """Reset the vault client (for testing)."""
    global _vault_client, _vault_client_initialized
    _vault_client = None
    _vault_client_initialized = False

# ==========================
# KV detection & vault wrappers
# ==========================

# Lazy-initialized KV version
_kv_version: Optional[int] = None


def _detect_kv_version(mount_point: str) -> int:
    """Detect the KV version for a given mount point."""
    client = get_vault_client()
    if client is None:
        raise RuntimeError("vault_client not initialized")

    try:
        mounts = client.sys.list_mounted_secrets_engines()["data"]
        for mount, cfg in mounts.items():
            if mount.rstrip("/") == mount_point:
                options = cfg.get("options") or {}
                if cfg.get("type") == "kv" and options.get("version") == "2":
                    return 2
                if cfg.get("type") == "kv" and options.get("version") is None:
                    try:
                        client.secrets.kv.v2.read_secret_version(
                            mount_point=mount_point, path="__detect__"
                        )
                        return 2
                    except Exception:
                        return 1
        try:
            client.secrets.kv.v2.read_secret_version(
                mount_point=mount_point, path="__detect__"
            )
            return 2
        except hvac.exceptions.InvalidPath:
            return 2
        except Exception:
            return 1
    except Exception:
        return 2


def get_kv_version() -> int:
    """Get the KV version, detecting it lazily if needed."""
    global _kv_version
    if _kv_version is None:
        config = get_config()
        _kv_version = _detect_kv_version(config.vault.mount)
        logger.info(
            "Detected Vault KV version for mount '%s': v%s",
            config.vault.mount,
            _kv_version,
        )
    return _kv_version


def reset_kv_version() -> None:
    """Reset the KV version cache (for testing)."""
    global _kv_version
    _kv_version = None

def vault_write(mount_point: str, path: str, secret):
    """
    Safe Vault KV writer:
    - Ensures KV v2 always receives a dict
    - Auto-wraps lists/strings into {"value": ...}
    - Prevents 'expected a map, got string' errors
    """
    client = get_vault_client()
    if client is None:
        raise RuntimeError("vault_client not initialized")

    # Always wrap non-dicts
    if not isinstance(secret, dict):
        secret = {"value": secret}

    if get_kv_version() == 2:
        client.secrets.kv.v2.create_or_update_secret(
            mount_point=mount_point, path=path, secret=secret
        )
    else:
        client.secrets.kv.v1.create_or_update_secret(
            mount_point=mount_point, path=path, secret=secret
        )

def vault_read(mount_point: str, path: str):
    """
    Always returns clean value:
    - If stored as {"chain": [...] } → returns [...]
    - If missing → returns []
    """
    client = get_vault_client()
    if client is None:
        raise RuntimeError("vault_client not initialized")
    try:
        if get_kv_version() == 2:
            res = client.secrets.kv.v2.read_secret_version(
                mount_point=mount_point, path=path
            )
            data = res.get("data", {}).get("data", {})

        else:
            res = client.secrets.kv.v1.read_secret(mount_point=mount_point, path=path)
            data = res.get("data", {})

        # Normalize chain
        if isinstance(data, dict) and "chain" in data:
            return data["chain"]

        # If already a list
        if isinstance(data, list):
            return data

        return []
    except Exception:
        return []

def vault_read_dict_or_raise(mount_point: str, path: str) -> dict:
    """
    Reads a secret dict and returns its res.data.data. This raises an exception
    if the secret data does not exist.
    """
    client = get_vault_client()
    if client is None:
        raise RuntimeError("vault_client not initialized")

    try:
        if get_kv_version() == 2:
            res = client.secrets.kv.v2.read_secret_version(
                mount_point=mount_point, path=path
            )
            data = res.get("data", {}).get("data", {})

        else:
            res = client.secrets.kv.v1.read_secret(mount_point=mount_point, path=path)
            data = res.get("data", {})

        return data or dict()
    except hvac.exceptions.InvalidPath:
        raise InvalidPathException(path=path, mount_point=mount_point)
    except Exception:
        raise



def vault_read_dict(mount_point: str, path: str) -> dict:
    """
    Reads a secret dict, then returns res.data.data. This returns an empty dict
    if the data does not exist.
    """
    client = get_vault_client()
    if client is None:
        raise RuntimeError("vault_client not initialized")
    try:
        return vault_read_dict_or_raise(mount_point=mount_point, path=path)
    except Exception as ex:
        logger.warning(f"Unable to read secret ${mount_point}/${path}: ${ex}")
        return {}

def vault_list(mount_point: str, path: str) -> List[str]:
    """List secrets at a given path."""
    client = get_vault_client()
    if client is None:
        raise RuntimeError("vault_client not initialized")

    if get_kv_version() == 2:
        res = client.secrets.kv.v2.list_secrets(mount_point=mount_point, path=path)
        return res["data"].get("keys", [])
    else:
        res = client.secrets.kv.v1.list_secrets(path=path, mount_point=mount_point)
        return res["data"].get("keys", [])

# ==========================
# Vault secret helpers (used earlier)
# ==========================
def vault_store_secret(path: str, data: dict, lifespan_minutes: int = 10):
    """Store a secret with automatic expiration."""
    client = get_vault_client()
    config = get_config()
    if client is None:
        raise RuntimeError("vault_client not initialized")

    expires_at = (datetime.utcnow() + timedelta(minutes=lifespan_minutes)).isoformat()
    client.secrets.kv.v2.create_or_update_secret(
        path=path, secret={**data, "expires_at": expires_at}, mount_point=config.vault.mount
    )

    def delayed_delete():
        time.sleep(lifespan_minutes * 60)
        try:
            del_client = get_vault_client()
            del_config = get_config()
            if del_client is None:
                raise RuntimeError("vault_client not initialized")
            del_client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=path, mount_point=del_config.vault.mount
            )
        except Exception as e:
            logger.exception("Auto-delete failed for %s: %s", path, e)

    threading.Thread(target=delayed_delete, daemon=True).start()
    return expires_at


def vault_fetch_secret(path: str) -> dict:
    """Fetch a secret from the default mount point."""
    client = get_vault_client()
    config = get_config()
    if client is None:
        raise RuntimeError("vault_client not initialized")
    try:
        result = client.secrets.kv.v2.read_secret_version(
            path=path, mount_point=config.vault.mount
        )
        return result["data"]["data"]
    except Exception:
        return {}


def vault_delete_metadata_and_all_versions(mount_point: str, path: str):
    """Delete a secret and all its versions."""
    client = get_vault_client()
    config = get_config()
    if client is None:
        raise RuntimeError("vault_client not initialized")
    client.secrets.kv.v2.delete_metadata_and_all_versions(
        path=path, mount_point=config.vault.mount
    )


def vault_is_authenticated() -> bool:
    """Returns true if the vault client is initialized and authenticated."""
    client = get_vault_client()
    return client is not None and client.is_authenticated()


# ==========================
# Division Signing Key Operations
# ==========================

class SigningKeyNotFoundError(Exception):
    """Raised when a signing key cannot be found in vault."""
    division: str
    fragment: str

    def __init__(self, division: str, fragment: str) -> None:
        super().__init__(f"Signing key '{fragment}' not found for division '{division}'")
        self.division = division
        self.fragment = fragment


class DivisionPublicKeysNotFoundError(Exception):
    """Raised when public keys cannot be found for a division."""
    division: str

    def __init__(self, division: str) -> None:
        super().__init__(f"Public keys not found for division '{division}'")
        self.division = division


def vault_get_division_public_keys(
    division: str,
    mount_point: str | None = None,
) -> list[dict]:
    """
    Get all public keys for a division (for DID document generation).

    Fetches from path: divisions/{division}/public_keys

    The stored document should have the structure:
    {
        "keys": [
            {"fragment": "key20260204", "public_key_multibase": "z6Mk..."},
            {"fragment": "key20260205", "public_key_multibase": "z6Mk..."}
        ]
    }

    Args:
        division: The division identifier
        mount_point: Vault mount point (defaults to config.vault.mount)

    Returns:
        List of dicts, each containing 'fragment' and 'public_key_multibase'

    Raises:
        DivisionPublicKeysNotFoundError: If no public keys are found for the division
    """
    if mount_point is None:
        mount_point = get_config().vault.mount
    path = f"divisions/{division}/public_keys"
    try:
        data = vault_read_dict_or_raise(mount_point, path)
        keys = data.get("keys", [])
        if not keys:
            raise DivisionPublicKeysNotFoundError(division)
        return keys
    except InvalidPathException:
        raise DivisionPublicKeysNotFoundError(division)


def vault_list_division_signing_key_fragments(
    division: str,
    mount_point: str | None = None,
) -> list[str]:
    """
    List available signing key fragments for a division.

    Lists keys at path: divisions/{division}/signing_keys/

    Args:
        division: The division identifier
        mount_point: Vault mount point (defaults to config.vault.mount)

    Returns:
        List of fragment identifiers (e.g., ["key20260204", "key20260205"])
    """
    if mount_point is None:
        mount_point = get_config().vault.mount
    path = f"divisions/{division}/signing_keys"
    try:
        return vault_list(mount_point, path)
    except Exception:
        return []


@contextmanager
def vault_signing_key_context(
    division: str,
    fragment: str,
    mount_point: str | None = None,
) -> Generator[tuple[SigningKey, str], None, None]:
    """
    Context manager that fetches a signing key from vault with secure cleanup.

    This function:
    1. Fetches the key from vault at: divisions/{division}/signing_keys/{fragment}
    2. Converts the hex secret to a SigningKey
    3. Yields the SigningKey and fragment for use
    4. On exit, securely clears the key material using sodium_memzero

    The stored document should have the structure:
    {
        "secret_key_hex": "a2c4e6f8..."
    }

    Usage:
        with vault_signing_key_context("advisory", "key20260204") as (signing_key, frag):
            signature = sign_vc(vc, signing_key, f"did:example:{frag}")
        # Key material is securely cleared here

    Args:
        division: The division identifier
        fragment: The key fragment identifier
        mount_point: Vault mount point (defaults to config.vault.mount)

    Yields:
        Tuple of (SigningKey, fragment)

    Raises:
        SigningKeyNotFoundError: If the key cannot be found in vault
    """
    # Import here to avoid circular dependency
    from app.did_utils.eddsa import sodium_memzero, secure_clear_signing_key

    if mount_point is None:
        mount_point = get_config().vault.mount
    path = f"divisions/{division}/signing_keys/{fragment}"
    signing_key: SigningKey | None = None
    key_bytes: bytearray | None = None

    try:
        # Fetch the secret from vault
        try:
            data = vault_read_dict_or_raise(mount_point, path)
        except InvalidPathException:
            raise SigningKeyNotFoundError(division, fragment)

        secret_key_hex = data.get("secret_key_hex")
        if not secret_key_hex:
            raise SigningKeyNotFoundError(division, fragment)

        # Convert hex string to mutable bytearray immediately
        # This allows us to zero the memory after creating the SigningKey
        try:
            key_bytes = bytearray.fromhex(secret_key_hex)
        except ValueError:
            raise SigningKeyNotFoundError(division, fragment)

        # Clear our reference to the hex string
        # (GC will eventually collect the original string from vault response)
        del secret_key_hex
        del data

        # Validate key length (Ed25519 seed is 32 bytes)
        if len(key_bytes) != 32:
            raise SigningKeyNotFoundError(division, fragment)

        # Create signing key from bytes
        signing_key = SigningKey(bytes(key_bytes))

        # Zero the intermediate bytearray using sodium_memzero
        sodium_memzero(key_bytes)
        key_bytes = None # No need for this from this point on.

        yield signing_key, fragment

    finally:
        # Securely clear the signing key material. Skip triggering GC inside the
        # call because we'll trigger it here.
        if signing_key is not None:
            secure_clear_signing_key(signing_key, trigger_gc=False)

        # Ensure key_bytes is cleared (triggered on exception cases).
        if key_bytes is not None:
            try:
                sodium_memzero(key_bytes)
            except Exception:
                pass

        # Force garbage collection
        gc.collect()


def vault_ensure_division_signing_key(
    division: str,
    mount_point: str | None = None,
) -> str:
    """
    Ensures at least one signing key exists for a division.

    If no signing key exists, generates a new Ed25519 keypair and stores:
    - Private key at: divisions/{division}/signing_keys/{fragment}
    - Public key appended to: divisions/{division}/public_keys

    This function is idempotent - if keys already exist, it does nothing.

    Args:
        division: The division identifier
        mount_point: Vault mount point (defaults to config.vault.mount)

    Returns:
        The fragment identifier of an existing or newly created key

    Note:
        The newly generated private key is securely cleared from memory
        after being stored in vault.
    """
    # Import here to avoid circular dependency
    from app.did_utils.eddsa import get_public_key_multibase, sodium_memzero

    if mount_point is None:
        mount_point = get_config().vault.mount

    # Check if any signing keys already exist
    existing_fragments = vault_list_division_signing_key_fragments(division, mount_point)
    if existing_fragments:
        logger.info(f"Division '{division}' already has {len(existing_fragments)} signing key(s)")
        return sorted(existing_fragments)[-1]  # Return the latest fragment

    # Generate a new key fragment based on current date
    fragment = f"key{datetime.utcnow().strftime('%Y%m%d')}"

    # Generate a cryptographically secure random 32-byte seed
    seed_bytes = bytearray(secrets.token_bytes(32))
    secret_key_hex = seed_bytes.hex()

    try:
        # Create SigningKey to compute public key
        signing_key = SigningKey(bytes(seed_bytes))
        public_key_multibase = get_public_key_multibase(signing_key)

        # Store the private key in vault
        private_key_path = f"divisions/{division}/signing_keys/{fragment}"
        vault_write(mount_point, private_key_path, {"secret_key_hex": secret_key_hex})
        logger.info(f"Created signing key for division '{division}' at {private_key_path}")

        # Store/update the public keys list
        public_keys_path = f"divisions/{division}/public_keys"
        try:
            existing_public_keys = vault_read_dict_or_raise(mount_point, public_keys_path)
            keys_list = existing_public_keys.get("keys", [])
        except InvalidPathException:
            keys_list = []

        keys_list.append({
            "fragment": fragment,
            "public_key_multibase": public_key_multibase
        })

        vault_write(mount_point, public_keys_path, {"keys": keys_list})
        logger.info(f"Updated public keys for division '{division}' with fragment '{fragment}'")

        return fragment

    finally:
        # Securely clear the seed bytes from memory
        sodium_memzero(seed_bytes)
        # Clear the hex string reference (best effort - strings are immutable)
        del secret_key_hex
        gc.collect()
