"""Ingest the sample KB, tagging each document with its department for RBAC retrieval."""
from pathlib import Path
from app.core.config import get_settings
from app.services.ingestion import load_file, chunk_documents
from app.rag.vectorstore import add_documents

settings = get_settings()

# file name -> department tag stored in Pinecone metadata (enforced by retrieval filters)
DEPARTMENT_MAP = {
    "company_it_handbook.md": "IT",
    "service_desk_runbook.md": "IT",
    "hr_policy_benefits.md": "HR",
    "finance_expense_policy.md": "FINANCE",
    "finance_payroll_confidential.md": "FINANCE",
    "security_incident_runbook.md": "SECURITY",
}

folder = Path(settings.sample_kb_dir)
files = [p for p in folder.iterdir() if p.is_file()]

for path in files:
    dept = DEPARTMENT_MAP.get(path.name, "GENERAL")
    docs = load_file(path)
    chunks = chunk_documents(docs)
    ids = add_documents(chunks, department=dept)
    print(f"Indexed {path.name} [{dept}] -> {len(chunks)} chunks")

print(f"Done: {len(files)} files indexed with department security tags.")
