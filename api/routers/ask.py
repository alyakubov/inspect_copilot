"""Ask view endpoint: semantic Q&A with cited sources (RAG)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from inspect_copilot import query
from inspect_copilot.store import Store

from ..auth import require_auth
from ..deps import get_store

router = APIRouter(prefix="/api", tags=["ask"], dependencies=[Depends(require_auth)])


class AskIn(BaseModel):
    question: str


@router.post("/ask")
def ask(body: AskIn, store: Store = Depends(get_store)) -> dict:
    # answer_semantic already resolves "report N" references and returns
    # {answer, sources, scope}.
    return query.answer_semantic(store, body.question)
