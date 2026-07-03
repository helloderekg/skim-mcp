"""Edge cases for skim fidelity testing - tricky constructs that could be missed or misrepresented."""
from __future__ import annotations
import sys
from functools import wraps
from typing import overload, TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator   # hidden import (inside if)

API_VERSION = "2.1"
_RETRIES = 3
make_id = lambda n: f"id-{n}"              # lambda assigned to a name


def deco(prefix):
    def wrap(fn):                          # nested function (hidden in body)
        @wraps(fn)
        def inner(*a, **k):
            return fn(*a, **k)
        return inner
    return wrap


@deco("x")
def decorated(
    a: int,
    b: str = "z",
    *args,
    **kwargs,
) -> bool:
    """Multi-line signature + decorator."""
    return bool(a)


async def fetch(url: str) -> bytes:
    """Async function."""
    return await _read(url)


class Widget:
    """A widget."""
    KIND = "w"

    def __init__(self, n: int):
        self.n = n
        def helper():                      # nested function inside __init__ (hidden)
            return n * 2
        self._h = helper

    @property
    def doubled(self) -> int:
        return self.n * 2

    @overload
    def get(self, k: int) -> int: ...
    @overload
    def get(self, k: str) -> str: ...
    def get(self, k):
        return k


if sys.platform == "win32":
    def platform_path(p):                  # conditionally-defined top-level fn (HIDDEN in if-block)
        return p.replace("/", "\\")
else:
    def platform_path(p):
        return p


try:
    import ujson as _json                  # hidden in try
except ImportError:
    import json as _json


def use_walrus(items):
    """Walrus inside a comprehension."""
    return [y for x in items if (y := x * 2) > 3]


for _i in range(3):                        # module-level loop
    API_VERSION = API_VERSION


if __name__ == "__main__":
    print(API_VERSION)
