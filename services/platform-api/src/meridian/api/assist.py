from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..context import request_id_var
from ..db import get_session
from ..schemas import AssistRequest
from ..security import Principal, require
from ..services.assistant import ask as ask_assistant
from ..services.assistant import search_chunks
from .deps import accessible_dataset_ids, client_ip

router = APIRouter(prefix="/assist", tags=["assist"])


@router.post("/ask")
def ask(
    body: AssistRequest,
    request: Request,
    principal: Principal = Depends(require("assist:use")),
    db: Session = Depends(get_session),
) -> dict:
    allowed = accessible_dataset_ids(db, principal.tenant_id, principal)
    if body.dataset_ids:
        selected = [dataset_id for dataset_id in body.dataset_ids if dataset_id in allowed]
        if len(selected) != len(body.dataset_ids):
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="One or more datasets are outside your data access.")
    else:
        selected = allowed
    result = ask_assistant(
        db,
        principal.tenant_id,
        body.question,
        selected,
        body.top_k,
        allowed_dataset_ids=allowed,
    )
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="assistant.queried",
        resource_type="assistant",
        resource_id="rag",
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={
            "question": body.question[:1000],
            "mode": result["mode"],
            "citations": len(result["citations"]),
            "datasets": selected[:20],
        },
    )
    db.commit()
    return {**result, "request_id": request_id_var.get()}


@router.post("/search")
def search(
    body: AssistRequest,
    principal: Principal = Depends(require("assist:use")),
    db: Session = Depends(get_session),
) -> dict:
    allowed = accessible_dataset_ids(db, principal.tenant_id, principal)
    selected = [item for item in body.dataset_ids if item in allowed] if body.dataset_ids else allowed
    results = search_chunks(
        db,
        principal.tenant_id,
        body.question,
        selected,
        body.top_k,
        allowed_dataset_ids=allowed,
    )
    return {
        "query": body.question,
        "results": [
            {
                "chunk_id": item["chunk_id"],
                "dataset_id": item["dataset_id"],
                "filename": item["filename"],
                "page": item["page"],
                "source_uri": item["source_uri"],
                "text": item["text"],
                "score": item["score"],
                "classification": item["classification"],
            }
            for item in results
        ],
        "request_id": request_id_var.get(),
    }
