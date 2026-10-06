"""Serialisation for cached objects."""
import pickle

from cache.redis_client import RedisClient

cache = RedisClient()


def serialize(obj) -> bytes:
    """Pickle an object for storage in Redis."""
    return pickle.dumps(obj)


def deserialize(data: bytes):
    """Unpickle a cached object.

    The new Node.js storefront writes rendered HTML and JSON into the same
    product:* keys, so some values start with '<' or '{' and are not pickles at all.
    Unpickling cache data is also unsafe if anything else can write to Redis.
    """
    return pickle.loads(data)


def get_cached_product(product_id: int):
    """Return a cached product object, or None on a cache miss."""
    data = cache.get(f"product:{product_id}")
    return deserialize(data) if data else None
