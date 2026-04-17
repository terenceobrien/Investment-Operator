from __future__ import annotations
from cachetools import TTLCache
from functools import wraps
import hashlib, json

_caches = {
    "market_state":  TTLCache(maxsize=20,  ttl=300),
    "dashboard":     TTLCache(maxsize=10,  ttl=300),
    "state_context": TTLCache(maxsize=10,  ttl=300),
    "macro":         TTLCache(maxsize=5,   ttl=14400),
    "brief_moves":   TTLCache(maxsize=10,  ttl=900),
    "brief_summary": TTLCache(maxsize=5,   ttl=86400),
    "prices":        TTLCache(maxsize=50,  ttl=300),
    "narrative":     TTLCache(maxsize=5,   ttl=900),
    "calendar":      TTLCache(maxsize=5,   ttl=3600),
    "regime_state":  TTLCache(maxsize=5,   ttl=3600 * 6),  # 6 hours
    "intraday_tape": TTLCache(maxsize=10,  ttl=300),        # 5 minutes
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
            if not (isinstance(result, dict) and result.get("stale") is True):
                store[key] = result
            return result
        return wrapper
    return decorator

def clear_regime_cache():
    """Call this after market close to force fresh computation."""
    cleared = 0
    for bucket in ["regime_state", "intraday_tape", "dashboard"]:
        if bucket in _caches:
            _caches[bucket].clear()
            cleared += 1
    return cleared
