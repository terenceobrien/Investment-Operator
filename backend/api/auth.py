import json
import logging
import os
import time
from typing import Any, Dict, Optional

import httpx
import jwt
from jwt import InvalidTokenError, PyJWT
from jwt.algorithms import RSAAlgorithm
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()
logger = logging.getLogger("api.auth")

CLERK_JWKS_URL = os.getenv(
    "CLERK_JWKS_URL",
    "https://clerk.helixintel.io/.well-known/jwks.json",
)
CLERK_ISSUER = os.getenv("CLERK_ISSUER")
CLERK_JWT_AUDIENCE = os.getenv("CLERK_JWT_AUDIENCE")
JWKS_CACHE_TTL_SECONDS = int(os.getenv("CLERK_JWKS_CACHE_TTL_SECONDS", "300"))

_jwks_cache: Optional[Dict[str, Any]] = None
_jwks_cache_expires_at: float = 0.0


async def get_jwks(force_refresh: bool = False) -> Dict[str, Any]:
    global _jwks_cache, _jwks_cache_expires_at

    now = time.time()
    if not force_refresh and _jwks_cache and now < _jwks_cache_expires_at:
        return _jwks_cache

    async with httpx.AsyncClient() as client:
        resp = await client.get(CLERK_JWKS_URL, timeout=5.0)
        resp.raise_for_status()
        jwks = resp.json()

    if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
        raise ValueError("Clerk JWKS response did not contain a keys array")

    _jwks_cache = jwks
    _jwks_cache_expires_at = now + JWKS_CACHE_TTL_SECONDS
    return jwks


def _public_key_for_kid(jwks: Dict[str, Any], kid: str | None) -> Any:
    keys = jwks.get("keys") or []
    if not kid:
        raise InvalidTokenError("JWT header is missing kid")

    for key in keys:
        if key.get("kid") == kid:
            return RSAAlgorithm.from_jwk(json.dumps(key))

    available = [str(k.get("kid")) for k in keys if k.get("kid")]
    raise InvalidTokenError(f"No matching JWKS key for kid={kid}; available_kids={available}")


async def verify_clerk_token(
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> dict:
    token = credentials.credentials
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        jwks = await get_jwks()
        try:
            public_key = _public_key_for_kid(jwks, kid)
        except InvalidTokenError:
            # Clerk key rotation can make a cached JWKS stale. Refresh once
            # before rejecting the request.
            jwks = await get_jwks(force_refresh=True)
            public_key = _public_key_for_kid(jwks, kid)

        decode_kwargs: Dict[str, Any] = {
            "algorithms": ["RS256"],
            "options": {"verify_aud": bool(CLERK_JWT_AUDIENCE)},
        }
        if CLERK_JWT_AUDIENCE:
            decode_kwargs["audience"] = CLERK_JWT_AUDIENCE
        if CLERK_ISSUER:
            decode_kwargs["issuer"] = CLERK_ISSUER

        payload = PyJWT().decode(
            token,
            public_key,
            **decode_kwargs,
        )
        return payload
    except Exception as e:
        logger.warning(
            "Clerk token verification failed: %s: %s",
            type(e).__name__,
            str(e),
        )
        raise HTTPException(status_code=401, detail="Invalid or expired token")
