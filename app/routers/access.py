# access_gateway.py
import os
import time
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
import jwt  # PyJWT

from app.services.vault import init_vault_client, vault_read

logger = logging.getLogger("access_gateway")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Access Gateway (JWT minting)")

# ───────────────────────────────────────────────
# CONFIG
# ───────────────────────────────────────────────
ISSUER = os.getenv("ACCESS_GATEWAY_ISS", "https://access.example.local")
DEFAULT_TTL_SECONDS = int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", "300"))
KEY_ID = os.getenv("ACCESS_GATEWAY_KEY_ID", "key-1")
VAULT_MOUNT = os.getenv("VAULT_KV_MOUNT", "secret")
VAULT_KEY_PATH = os.getenv("ACCESS_GATEWAY_VAULT_KEY_PATH", "access_gateway/keys")
ALLOWED_CLIENTS = os.getenv("ACCESS_GATEWAY_CLIENTS", "")  # "client1:secret1,client2:pass"
security = HTTPBasic()

vault_client = init_vault_client()

# ───────────────────────────────────────────────
# SIGNING KEY MANAGEMENT
# ───────────────────────────────────────────────
SIGNING_KEYS = None  # lazy loaded


def load_signing_key() -> Dict[str, str]:
    """
    Load RS256 signing keys from Vault KV v2
    """
    try:
        secret = vault_client.secrets.kv.v2.read_secret_version(
            mount_point=VAULT_MOUNT,
            path=VAULT_KEY_PATH
        )

        data = secret.get("data", {}).get("data", {})

        if "private_pem" not in data:
            raise RuntimeError(f"private_pem missing in Vault data at {VAULT_MOUNT}/{VAULT_KEY_PATH}")

        logger.info(f"✅ Loaded signing key from Vault: {VAULT_MOUNT}/{VAULT_KEY_PATH}")

        return {
            "kid": data.get("kid", KEY_ID),
            "private_pem": data["private_pem"],
            "public_pem": data.get("public_pem"),
        }

    except Exception as e:
        logger.error(f"❌ Failed loading signing key: {e}")
        raise RuntimeError("Signing private key not configured (Vault or env)")


def get_signing_keys() -> Dict[str, str]:
    global SIGNING_KEYS
    if SIGNING_KEYS is None:
        SIGNING_KEYS = load_signing_key()
    return SIGNING_KEYS


def get_private_key() -> str:
    return get_signing_keys()["private_pem"]


def get_public_key() -> str:
    return get_signing_keys().get("public_pem")


def get_kid() -> str:
    return get_signing_keys().get("kid", KEY_ID)


# ───────────────────────────────────────────────
# JWKS GENERATOR
# ───────────────────────────────────────────────
def build_jwks() -> Dict[str, Any]:
    pub = get_public_key()
    kid = get_kid()

    if not pub:
        return {"keys": []}

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.asymmetric import rsa
    import base64

    key = serialization.load_pem_public_key(pub.encode(), backend=default_backend())

    if not isinstance(key, rsa.RSAPublicKey):
        return {"keys": []}

    public_numbers = key.public_numbers()
    n = public_numbers.n
    e = public_numbers.e

    def _b64u(n_bytes):
        return base64.urlsafe_b64encode(n_bytes).rstrip(b"=").decode("ascii")

    return {
        "keys": [{
            "kty": "RSA",
            "kid": kid,
            "use": "sig",
            "alg": "RS256",
            "n": _b64u(n.to_bytes((n.bit_length() + 7) // 8, "big")),
            "e": _b64u(e.to_bytes((e.bit_length() + 7) // 8, "big")),
        }]
    }


# ───────────────────────────────────────────────
# AUTH & MODELS
# ───────────────────────────────────────────────
class TokenRequest(BaseModel):
    ttl: Optional[int] = None
    scope: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


def validate_client_basic(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    allowed = {}

    if ALLOWED_CLIENTS:
        for entry in ALLOWED_CLIENTS.split(","):
            entry = entry.strip()
            if ":" in entry:
                cid, sec = entry.split(":", 1)
                allowed[cid] = sec

    if credentials.username in allowed and allowed[credentials.username] == credentials.password:
        return credentials.username

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid client credentials"
    )


# ───────────────────────────────────────────────
# ENDPOINTS
# ───────────────────────────────────────────────
@app.post("/token", response_model=TokenResponse)
def token_endpoint(req: TokenRequest, client_id: str = Depends(validate_client_basic)):
    ttl = req.ttl or DEFAULT_TTL_SECONDS

    if ttl <= 0 or ttl > 3600:
        raise HTTPException(400, "ttl must be between 1 and 3600 seconds")

    now = int(time.time())
    exp = now + ttl

    payload = {
        "iss": ISSUER,
        "sub": client_id,
        "iat": now,
        "nbf": now,
        "exp": exp,
        "scope": req.scope or "",
    }

    token = jwt.encode(
        payload,
        get_private_key(),
        algorithm="RS256",
        headers={"kid": get_kid()}
    )

    return TokenResponse(access_token=token, expires_in=ttl)


@app.get("/jwks")
def jwks():
    return build_jwks()


@app.post("/introspect")
def introspect(token: str):
    try:
        decoded = jwt.decode(
            token,
            get_public_key(),
            algorithms=["RS256"],
            options={"verify_aud": False}
        )
        return {"active": True, "claims": decoded}
    except jwt.ExpiredSignatureError:
        return {"active": False, "reason": "expired"}
    except Exception:
        return {"active": False, "reason": "invalid"}



