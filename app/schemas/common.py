"""Shared response envelope + pagination used across every module for a consistent API shape."""
from typing import Generic, List, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PageMeta(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class Page(BaseModel, Generic[T]):
    items: List[T]
    meta: PageMeta


class MessageResponse(BaseModel):
    message: str
