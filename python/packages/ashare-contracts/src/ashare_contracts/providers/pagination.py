"""Cursor-based pagination models.

Providers page through large result sets with an opaque cursor. An empty page
(items == [] and next_cursor is None) signals the end of the result set; a
non-empty page may still return ``next_cursor=None`` to mean it was the last
page.
"""

from __future__ import annotations

from pydantic import BaseModel

# Opaque pagination token returned by a provider and passed back verbatim.
Cursor = str


class Page[T](BaseModel):
    """One page of results plus the cursor for the next page (None at the end)."""

    items: list[T]
    next_cursor: Cursor | None = None
