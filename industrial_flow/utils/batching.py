from __future__ import annotations

from collections.abc import Iterable, Iterator
from itertools import islice
from typing import TypeVar

T = TypeVar("T")


def chunked(items: list[T], size: int) -> Iterator[list[T]]:
    if size <= 0:
        raise ValueError("size must be greater than zero")
    for i in range(0, len(items), size):
        yield items[i : i + size]


def batched_iterable(items: Iterable[T], size: int) -> Iterator[list[T]]:
    iterator = iter(items)
    while batch := list(islice(iterator, size)):
        yield batch
