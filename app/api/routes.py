from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
from fastapi import Depends
from app.auth.rbac import DEPARTMENTS, PUBLIC_DEPARTMENT, User
from app.auth.routes import get_current_user, require_admin
from app.core.config import get_settings
from app.rag.workflow import ask
from app.rag.vectorstore import add_documents
from app.services.ingestion import load_file, chunk_documents, SUPPORTED
from app.services import audit

router = APIRouter(prefix="/api")
settings = get_settings()

class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=3000)


@router.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name}


@router.post("/chat")
def chat(payload: ChatRequest, user: User = Depends(get_current_user)):
    """Authorization-aware chat: retrieval is filtered by the user's role-based departments."""
    try:
        result = ask(
            payload.question,
            username=user.username,
            allowed_departments=list(user.allowed_departments),
        )
        trace = result.get("trace", [])
        doc_departments = sorted({
            d.metadata.get("department", PUBLIC_DEPARTMENT) for d in result.get("kb_docs", [])
        })

        audit.write_audit(
            payload.question,
            result["source_used"],
            trace,
            username=user.username,
            roles=user.roles,
            doc_departments=doc_departments,
        )
        # Document-level access audit: one row per distinct document retrieved
        accessed = []
        seen = set()
        for d in result.get("kb_docs", []):
            key = (d.metadata.get("source", "unknown"), d.metadata.get("department", PUBLIC_DEPARTMENT))
            if key not in seen:
                seen.add(key)
                accessed.append({"document": key[0], "department": key[1]})
        audit.write_document_access(user.username, user.roles, payload.question, accessed)

        # Authorization-aware fallback: log withheld web fallbacks as explicit denials
        if result.get("source_used") == "denied_access":
            audit.write_document_access(user.username, user.roles, payload.question,
                                        [{"document": "(restricted - not retrieved)",
                                          "department": "DENIED"}])

        return {
            "answer": result["answer"],
            "source_used": result["source_used"],
            "trace": trace,
            "citations": result.get("citations", []),
            "rewritten_query": result.get("current_query", payload.question),
            "access_scope": {
                "username": user.username,
                "roles": user.roles,
                "allowed_departments": list(user.allowed_departments),
                "document_departments_seen": doc_departments,
            },
            "confidence": result.get("confidence"),
            "escalation_ref": result.get("escalation_ref") or None,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/ingest")
async def ingest(
    file: UploadFile = File(...),
    department: str = Form(default=PUBLIC_DEPARTMENT),
    user: User = Depends(get_current_user),
):
    """Ingest a document, tagging all chunks with a department for RBAC-filtered retrieval.

    Security Admin may tag any department; other users may only tag their own departments.
    """
    dept = department.upper().strip()
    if dept not in DEPARTMENTS and dept != PUBLIC_DEPARTMENT:
        raise HTTPException(status_code=400, detail=f"department must be one of: {', '.join(DEPARTMENTS)} or {PUBLIC_DEPARTMENT}")
    if not user.is_admin and dept not in user.allowed_departments:
        raise HTTPException(status_code=403, detail=f"Your roles cannot tag documents as {dept}.")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED:
        raise HTTPException(status_code=400, detail=f"Supported: {', '.join(sorted(SUPPORTED))}")
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / Path(file.filename).name
    dest.write_bytes(await file.read())
    docs = load_file(dest)
    chunks = chunk_documents(docs)
    ids = add_documents(chunks, department=dept)
    audit.write_document_access(user.username, user.roles, f"[ingest] {dest.name}",
                                [{"document": dest.name, "department": dept}])
    return {"message": "Document indexed", "file": dest.name, "department": dept,
            "chunks": len(chunks), "ids_created": len(ids)}


@router.get("/admin/audit")
def admin_audit(user: User = Depends(require_admin)):
    """Security Admin only: query audit, document-access log and summary."""
    return {
        "summary": audit.audit_summary(),
        "query_audit": audit.read_query_audit(),
        "document_access": audit.read_document_access(),
    }
