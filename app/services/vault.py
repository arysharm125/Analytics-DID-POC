from datetime import datetime, timedelta
import hvac
import threading, time
import logging
import hvac.exceptions
from typing import List


from dotenv import load_dotenv
load_dotenv()

from app.constants import (
    VAULT_ADDR,
    VAULT_TOKEN,
    VAULT_MOUNT,
)

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

def get_vault_config():
    """Fetches Vault address, token, and mount path."""
    return VAULT_ADDR, VAULT_TOKEN, VAULT_MOUNT

def init_vault_client():
    """Initialize and return an authenticated hvac Vault client."""
    VAULT_ADDR, VAULT_TOKEN, _ = get_vault_config()
    try:
        client = hvac.Client(url=VAULT_ADDR, token=VAULT_TOKEN)
        if client.is_authenticated():
            logging.info(f"[INFO] Vault connected: {VAULT_ADDR}")
        else:
            logging.warning(f"[WARN] Vault authentication failed: {VAULT_ADDR}")
        return client
    except Exception as e:
        logging.error(f"[ERROR] Vault client initialization failed: {e}")
        return None

vault_client = init_vault_client()

# ==========================
# KV detection & vault wrappers
# ==========================
def _detect_kv_version(mount_point: str = VAULT_MOUNT) -> int:
    if vault_client is None:
        raise RuntimeError("vault_client not initialized")

    try:
        mounts = vault_client.sys.list_mounted_secrets_engines()["data"]
        for mount, cfg in mounts.items():
            if mount.rstrip("/") == mount_point:
                options = cfg.get("options") or {}
                if cfg.get("type") == "kv" and options.get("version") == "2":
                    return 2
                if cfg.get("type") == "kv" and options.get("version") is None:
                    try:
                        vault_client.secrets.kv.v2.read_secret_version(mount_point=mount_point, path="__detect__")
                        return 2
                    except Exception:
                        return 1
        try:
            vault_client.secrets.kv.v2.read_secret_version(mount_point=mount_point, path="__detect__")
            return 2
        except hvac.exceptions.InvalidPath:
            return 2
        except Exception:
            return 1
    except Exception:
        return 2

KV_VERSION = _detect_kv_version(VAULT_MOUNT)
logger.info("Detected Vault KV version for mount '%s': v%s", VAULT_MOUNT, KV_VERSION)

#def vault_write(mount_point: str, path: str, secret: dict):
#    if KV_VERSION == 2:
#        vault_client.secrets.kv.v2.create_or_update_secret(mount_point=mount_point, path=path, secret=secret)
#    else:
#        vault_client.secrets.kv.v1.create_or_update_secret(mount_point=mount_point, path=path, secret=secret)
def vault_write(mount_point: str, path: str, secret):
    """
    Safe Vault KV writer:
    - Ensures KV v2 always receives a dict
    - Auto-wraps lists/strings into {"value": ...}
    - Prevents 'expected a map, got string' errors
    """
    if vault_client is None:
        raise RuntimeError("vault_client not initialized")

    # ✅ Always wrap non-dicts
    if not isinstance(secret, dict):
        secret = {"value": secret}

    if KV_VERSION == 2:
        vault_client.secrets.kv.v2.create_or_update_secret(
            mount_point=mount_point,
            path=path,
            secret=secret
        )
    else:
        vault_client.secrets.kv.v1.create_or_update_secret(
            mount_point=mount_point,
            path=path,
            secret=secret
        )

def vault_read(mount_point: str, path: str):
    """
    Always returns clean value:
    - If stored as {"chain": [...] } → returns [...]
    - If missing → returns []
    """
    if vault_client is None:
            raise RuntimeError("vault_client not initialized")
    try:
        if KV_VERSION == 2:
            res = vault_client.secrets.kv.v2.read_secret_version(
                mount_point=mount_point,
                path=path
            )
            data = res.get("data", {}).get("data", {})

        else:
            res = vault_client.secrets.kv.v1.read_secret(
                mount_point=mount_point,
                path=path
            )
            data = res.get("data", {})

        # ✅ Normalize chain
        if isinstance(data, dict) and "chain" in data:
            return data["chain"]

        # ✅ If already a list
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
    if vault_client is None:
            raise RuntimeError("vault_client not initialized")

    try:
        if KV_VERSION == 2:
            res = vault_client.secrets.kv.v2.read_secret_version(
                mount_point=mount_point,
                path=path
            )
            data = res.get("data", {}).get("data", {})

        else:
            res = vault_client.secrets.kv.v1.read_secret(
                mount_point=mount_point,
                path=path
            )

        return data or dict()
    except (hvac.exceptions.InvalidPath):
        raise InvalidPathException(path=path, mount_point=mount_point)
    except Exception:
        raise



def vault_read_dict(mount_point: str, path: str) -> dict:
    """
    Reads a secret dict, then returns res.data.data. This returns an empty dict
    if the data does not exist.
    """
    if vault_client is None:
            raise RuntimeError("vault_client not initialized")
    try:
        return vault_read_dict_or_raise(mount_point=mount_point, path=path)
    except Exception as ex:
        logger.warning(f"Unable to read secret ${mount_point}/${path}: ${ex}")
        return {}

def vault_list(mount_point: str, path: str) -> List[str]:
    if vault_client is None:
            raise RuntimeError("vault_client not initialized")

    if KV_VERSION == 2:
        res = vault_client.secrets.kv.v2.list_secrets(mount_point=mount_point, path=path)
        return res["data"].get("keys", [])
    else:
        res = vault_client.secrets.kv.v1.list_secrets(path=path, mount_point=mount_point)
        return res["data"].get("keys", [])

# ==========================
# Vault secret helpers (used earlier)
# ==========================
def vault_store_secret(path: str, data: dict, lifespan_minutes: int = 10):
    if vault_client is None:
            raise RuntimeError("vault_client not initialized")

    expires_at = (datetime.utcnow() + timedelta(minutes=lifespan_minutes)).isoformat()
    vault_client.secrets.kv.v2.create_or_update_secret(
        path=path, secret={**data, "expires_at": expires_at}, mount_point=VAULT_MOUNT
    )
    def delayed_delete():
        time.sleep(lifespan_minutes * 60)
        try:
            if vault_client is None:
                raise RuntimeError("vault_client not initialized")
            vault_client.secrets.kv.v2.delete_metadata_and_all_versions(path=path, mount_point=VAULT_MOUNT)
        except Exception as e:
            logger.exception("Auto-delete failed for %s: %s", path, e)
    threading.Thread(target=delayed_delete, daemon=True).start()
    return expires_at

def vault_fetch_secret(path: str) -> dict:
    if vault_client is None:
            raise RuntimeError("vault_client not initialized")
    try:
        result = vault_client.secrets.kv.v2.read_secret_version(path=path, mount_point=VAULT_MOUNT)
        return result["data"]["data"]
    except Exception:
        return {}


def vault_delete_metadata_and_all_versions(mount_point: str, path: str) :
    if vault_client is None:
            raise RuntimeError("vault_client not initialized")
    vault_client.secrets.kv.v2.delete_metadata_and_all_versions(
        path=path,
        mount_point=VAULT_MOUNT
    )

def vault_is_authenticated() -> bool:
    """Returns true if the vault client is initialized and authenticated."""
    return vault_client != None and vault_client.is_authenticated()