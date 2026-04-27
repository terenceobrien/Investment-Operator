import httpx
from jwt import PyJWT
from jwt.algorithms import RSAAlgorithm
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import json

security = HTTPBearer()

async def get_jwks():
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://api.clerk.com/v1/jwks")
        return resp.json()

async def verify_clerk_token(
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> dict:
    token = credentials.credentials
    try:
        jwks = await get_jwks()
        # Get the first key from the JWKS
        public_key = RSAAlgorithm.from_jwk(json.dumps(jwks["keys"][0]))
        payload = PyJWT().decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={"verify_aud": False}
        )
        return payload
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid or expired token")