# Minimal sqlglot shim for local debug only
from .parser import parse_one
from . import expressions

__all__ = ["parse_one", "expressions"]
