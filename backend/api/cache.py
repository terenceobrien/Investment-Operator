from __future__ import annotations
from cachetools import TTLCache
from functools import wraps
import hashlib, json

# TTL caches matching your old st.cache_data TTLs
_caches = {
    "market_state":  TTLCache(maxsize=20,  ttl=300),    # 5 min
    "macro":         TTLCache(maxsize=5,   ttl=14400),  # 4 hr
    "brief_moves":   TTLCache(maxsize=10,  ttl=900),    # 15 min
    "brief_summary": TTLCache(maxsize=5,   ttl=86400),  # 24 hr
    "prices":        TTLCache(maxsize=50,  ttl=300),    # 5 min
    "narrative":     TTLCache(maxsize=5,   ttl=900),    # 15 min
    "calendar":      TTLCache(maxsize=5,   ttl=3600),   # 1 hr
}

def cache(bucket: str):
    """Decorator that caches the return value of an async function."""
    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            key = hashlib.md5(
                json.dumps({"a": str(args), "k": str(kwargs)},
                           sort_keys=True).encode()
            ).hexdigest()
            store = _caches[bucket]
            if key in store:
                return store[key]
            result = await fn(*args, **kwargs)
            store[key] = result
            return result
        return wrapper
    return decorator