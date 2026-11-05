from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_container
from app.container import Container
from app.insights.tracker import TrackedActionItem, collect_action_items

router = APIRouter(prefix="/api", tags=["insights"])
ContainerDep = Annotated[Container, Depends(get_container)]


@router.get("/action-items")
def action_items(
    c: ContainerDep, meeting_ids: Annotated[list[str] | None, Query()] = None
) -> list[TrackedActionItem]:
    """Every action item across meetings (or the given ones), owners resolved to participants."""
    return collect_action_items(c.store, meeting_ids)
