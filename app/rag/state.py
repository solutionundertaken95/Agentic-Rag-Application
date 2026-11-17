from typing import List, Literal
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from langchain_core.documents import Document

class RouteDecision(BaseModel):
    route: Literal["kb", "direct"] = Field(description="kb for IT/support questions; direct for greetings/simple chat")

class ConfidenceScore(BaseModel):
    """LLM-as-judge confidence that a draft answer is correct and grounded."""
    confidence: int = Field(description="0-100 confidence that the answer is accurate and fully supported by evidence", ge=0, le=100)

class InternalTopicDecision(BaseModel):
    """Whether a question is about internal company matters (policy/payroll/procedures)
    whose answer would plausibly exist in the private company KB."""
    internal: bool = Field(description="true if the question is about internal company matters")

class EvidenceGrade(BaseModel):
    grade: Literal["good", "weak"] = Field(description="Whether evidence is sufficient to answer")

class AgentState(TypedDict):
    question: str
    current_query: str
    kb_docs: List[Document]
    web_results: str
    kb_grade: str
    web_grade: str
    answer: str
    source_used: str
    retry_count: int
    trace: List[str]
    citations: List[dict]
    # Authorization-aware RAG: user principal carried through the graph
    username: str
    allowed_departments: List[str]
    retrieved_sources: List[str]
    kb_empty_in_scope: bool
    is_internal_topic: bool
    # Human-in-the-loop escalation
    confidence: int
    escalation_ref: str