"""JSON responses."""
import json


def to_dict(obj) -> dict:
    """Convert a model object to a dict, including its relationship attributes."""
    return {k: v for k, v in vars(obj).items() if not k.startswith("_")}


def serialize_response(obj) -> str:
    """Serialise an endpoint's result to JSON.

    An Order references its Customer, and Customer.orders points back at the same
    Order, so dumping the raw object graph contains a cycle.
    """
    if hasattr(obj, "__dict__"):
        obj = to_dict(obj)
    return json.dumps(obj)
