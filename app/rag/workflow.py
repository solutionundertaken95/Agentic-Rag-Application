import logging
from typing import Literal
from langchain_groq import ChatGroq
from langchain_tavily import TavilySearch
from langgraph.graph import StateGraph, START, END
from app.core.config import get_settings
from app.rag.state import AgentState, RouteDecision, EvidenceGrade, InternalTopicDecision, ConfidenceScore
from app.rag.vectorstore import get_retriever

logger = logging.getLogger(__name__)
settings = get_settings()

_llm = None
_web_search = None

def llm():
    global _llm
    if _llm is None:
        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is missing")
        _llm = ChatGroq(
            model=settings.groq_model,
            temperature=0,
            api_key=settings.groq_api_key,
        )
    return _llm

def web_search_tool():
    global _web_search
    if _web_search is None:
        if not settings.tavily_api_key:
            raise RuntimeError("TAVILY_API_KEY is missing")
        _web_search = TavilySearch(
            tavily_api_key=settings.tavily_api_key,
            max_results=5,
            topic="general",
            include_answer=True,
            include_raw_content=False,
        )
    return _web_search

def add_trace(state: AgentState, message: str):
    return [*state.get("trace", []), message]

def route_question(state: AgentState):
    router = llm().with_structured_output(RouteDecision, method="json_mode")
    decision = router.invoke(f"""
You route messages for an enterprise IT support assistant that has access to a private
company knowledge base containing uploaded documents on any topic (policies, procedures,
product info, HR, IT, or anything else the company has indexed).

Use "kb" for ANY question that could plausibly be answered using company documents or
knowledge — this includes IT topics, policies, procedures, product/service questions,
or anything specific/informational. When in doubt, choose "kb".

Use "direct" ONLY for greetings, thanks, small talk, or questions with no possible
connection to company knowledge (e.g. "hello", "thank you", "how are you").

Question: {state['question']}
Return valid JSON like {{"route":"kb"}}.
""")
    return {"source_used": decision.route, "trace": add_trace(state, f"Router → {decision.route.upper()}")}

def route_after_router(state: AgentState) -> Literal["retrieve_kb", "direct_answer"]:
    return "retrieve_kb" if state["source_used"] == "kb" else "direct_answer"

def retrieve_kb(state: AgentState):
    """Authorization-aware retrieval: Pinecone metadata filter restricts chunks to the
    departments the requesting user's roles allow. Re-applied identically on retry loops
    so rewrites can never widen access."""
    allowed = state.get("allowed_departments") or []
    retriever = get_retriever(allowed_departments=allowed)
    docs = retriever.invoke(state["current_query"])
    scope = ",".join(sorted(set(allowed) | {"GENERAL"})) if allowed else "UNRESTRICTED"
    accessed = sorted({d.metadata.get("source", "unknown") for d in docs})
    return {
        "kb_docs": docs,
        # Empty retrieval inside the user's scope is the trigger for the
        # authorization-aware fallback: the info may exist but be restricted.
        "kb_empty_in_scope": len(docs) == 0,
        "trace": add_trace(
            state,
            f"Private KB retrieval (role-filter: {scope}) → {len(docs)} chunks "
            f"from {len(accessed)} document(s)",
        ),
        "retrieved_sources": accessed,
    }

def grade_kb(state: AgentState):
    grader = llm().with_structured_output(EvidenceGrade, method="json_mode")
    context = "\n\n".join(f"Source: {d.metadata.get('source','unknown')}\n{d.page_content}" for d in state["kb_docs"])
    grade = grader.invoke(f"""
You grade evidence for an enterprise IT support assistant.
Question: {state['question']}
Private company KB evidence:\n{context}
Return good only if the evidence is sufficient to answer confidently and specifically.
Otherwise return weak. JSON: {{"grade":"good"}} or {{"grade":"weak"}}.
""")
    return {"kb_grade": grade.grade, "trace": add_trace(state, f"KB evidence grade → {grade.grade.upper()}")}

def after_kb(state: AgentState) -> Literal["generate_from_kb", "check_access_scope", "search_web"]:
    """Authorization-aware fallback routing.

    - good evidence → answer from KB
    - weak evidence → classify the question first: if it is about internal company
      matters, the real answer may sit in restricted documents the user cannot see
      (whether retrieval returned nothing, or irrelevant in-scope chunks). Web fallback
      is only allowed for genuinely external topics.
    """
    if state["kb_grade"] == "good":
        return "generate_from_kb"
    return "check_access_scope"


def check_access_scope(state: AgentState):
    """Classify whether the question is about internal company matters that would
    normally live in the private KB (policy, benefits, payroll, procedures, runbooks).
    If so, web search must NOT answer it — the user may simply lack access to the
    document that contains the answer."""
    classifier = llm().with_structured_output(InternalTopicDecision, method="json_mode")
    decision = classifier.invoke(f"""
You decide whether a question is about INTERNAL company matters for an enterprise
knowledge assistant. Internal matters include: company policies (leave, benefits,
expenses, reimbursement), payroll/compensation, internal procedures and runbooks,
incident handling, HR/Finance/IT/Security processes, internal systems and vendors,
or any question whose answer would plausibly exist in a private company document.

External matters include: general tech knowledge, product/vendor documentation,
public news, outages, how-tos unrelated to this company's internals.

Question: {state['question']}
Return valid JSON like {{"internal": true}}.
""")
    verdict = "INTERNAL" if decision.internal else "EXTERNAL"
    return {
        "is_internal_topic": decision.internal,
        "trace": add_trace(state, f"Access-scope check → topic classified {verdict}"),
    }


def after_access_scope(state: AgentState) -> Literal["denied_access", "search_web"]:
    return "denied_access" if state["is_internal_topic"] else "search_web"


def denied_access(state: AgentState):
    """The user's question likely has an answer in restricted company documents they
    are not authorized to see. Do not leak existence of such documents, and do NOT
    answer internal-policy questions from the public web — redirect instead."""
    return {
        "answer": (
            "I couldn't find this in the knowledge bases you're authorized to access. "
            "This may be covered by internal company documentation outside your role's "
            "access scope — please contact your department owner (IT, HR, Finance, or "
            "Security) or raise a ticket for the relevant team."
        ),
        "source_used": "denied_access",
        "citations": [],
        "trace": add_trace(state, "Stopped → no authorized internal evidence; web fallback withheld"),
    }

def search_web(state: AgentState):
    result = web_search_tool().invoke({"query": state["current_query"]})
    lines, citations = [], []
    if isinstance(result, dict):
        if result.get("answer"):
            lines.append("Search answer: " + result["answer"])
        for item in result.get("results", []):
            title, url, content = item.get("title", ""), item.get("url", ""), item.get("content", "")
            lines.append(f"Title: {title}\nURL: {url}\nContent: {content}")
            citations.append({"title": title or url, "url": url, "type": "web"})
    else:
        lines.append(str(result))
    return {
        "web_results": "\n\n".join(lines),
        "citations": citations,
        "source_used": "web",
        "trace": add_trace(state, "Web fallback → Tavily search"),
    }

def grade_web(state: AgentState):
    grader = llm().with_structured_output(EvidenceGrade, method="json_mode")
    grade = grader.invoke(f"""
Question: {state['question']}
Web evidence:\n{state['web_results']}
Return good if the evidence is sufficient and directly relevant; otherwise weak.
Return valid JSON like {{"grade":"good"}}.
""")
    return {"web_grade": grade.grade, "trace": add_trace(state, f"Web evidence grade → {grade.grade.upper()}")}

def after_web(state: AgentState) -> Literal["generate_from_web", "rewrite_query", "insufficient"]:
    if state["web_grade"] == "good":
        return "generate_from_web"
    if state["retry_count"] < settings.max_retries:
        return "rewrite_query"
    return "insufficient"

def rewrite_query(state: AgentState):
    rewritten = llm().invoke(f"""
Rewrite this IT support question for better private knowledge retrieval and vendor web search.
Preserve intent, add useful technical keywords, do not answer, return only the query.
Question: {state['question']}
""").content.strip()
    return {
        "current_query": rewritten,
        "retry_count": state["retry_count"] + 1,
        "trace": add_trace(state, f"Query rewrite → {rewritten}"),
    }

def generate_from_kb(state: AgentState):
    context = "\n\n".join(f"[Source: {d.metadata.get('source','unknown')}]\n{d.page_content}" for d in state["kb_docs"])
    answer = llm().invoke(f"""
You are an enterprise IT support copilot. Answer ONLY from the private company KB below.
Be concise, actionable, and safe. If steps are present, present them clearly.
Do not invent policy details. Mention that the answer is based on the company's private knowledge base.
Question: {state['question']}\n\nPrivate KB:\n{context}
""").content
    citations = []
    seen = set()
    for d in state["kb_docs"]:
        src = d.metadata.get("source", "Private KB")
        if src not in seen:
            seen.add(src)
            citations.append({"title": src.split("/")[-1], "url": "", "type": "private_kb"})
    return {"answer": answer, "source_used": "private_kb", "citations": citations, "trace": add_trace(state, "Answer generation → PRIVATE KB")}

def generate_from_web(state: AgentState):
    answer = llm().invoke(f"""
You are an enterprise IT support copilot. The private company KB was insufficient.
Answer ONLY from the web evidence below. Clearly say this is external web information and may need IT validation before changing company-managed systems.
Question: {state['question']}\n\nWeb evidence:\n{state['web_results']}
""").content
    return {"answer": answer, "source_used": "web_search", "trace": add_trace(state, "Answer generation → WEB SEARCH")}

def score_confidence(state: AgentState):
    """LLM-as-judge: score how well the draft answer is supported by the actual evidence.
    Applied to private-KB answers (the high-stakes path). 0-100."""
    context = "\n\n".join(
        f"[Source: {d.metadata.get('source','unknown')}]\n{d.page_content}" for d in state["kb_docs"]
    )
    judge = llm().with_structured_output(ConfidenceScore, method="json_mode")
    verdict = judge.invoke(f"""
You are a strict quality judge for an enterprise assistant. Score how confident you are
that the DRAFT ANSWER is factually correct AND fully supported by the EVIDENCE.

- 90-100: every claim in the answer is directly supported by the evidence
- 70-89: mostly supported, minor gaps or extrapolation
- 40-69: partially supported; some claims lack evidence or the evidence is only loosely related
- 0-39: the evidence does not support the answer; likely hallucination or guess

Do not reward fluent writing — only evidence support.

QUESTION: {state['question']}

EVIDENCE:
{context}

DRAFT ANSWER:
{state['answer']}

Return JSON like {{"confidence": 85}}.
""")
    score = int(verdict.confidence)
    return {
        "confidence": score,
        "trace": add_trace(state, f"Confidence score → {score}/100 (threshold {settings.confidence_threshold})"),
    }


def after_confidence(state: AgentState) -> Literal["return_answer", "escalate_to_human"]:
    return "return_answer" if state["confidence"] >= settings.confidence_threshold else "escalate_to_human"


def return_answer(state: AgentState):
    """Pass-through: the draft answer met the confidence threshold."""
    return {"trace": add_trace(state, "Confidence check passed → answer released")}


def escalate_to_human(state: AgentState):
    """Human-in-the-loop: draft answer was below the confidence threshold.
    Create an escalation ticket with the question, draft answer and retrieved evidence
    attached, and hand it to the department reviewer instead of releasing the answer."""
    from app.services.audit import create_escalation

    # Which department owns this question? Use the departments of retrieved evidence;
    # fall back to the first allowed department of the user.
    depts = sorted({d.metadata.get("department", "GENERAL") for d in state.get("kb_docs", [])})
    depts = [d for d in depts if d != "GENERAL"] or ["GENERAL"]
    department = depts[0]

    evidence = [
        {
            "source": d.metadata.get("source", "unknown"),
            "department": d.metadata.get("department", "GENERAL"),
            "excerpt": d.page_content[:800],
        }
        for d in state.get("kb_docs", [])
    ]
    ref = create_escalation(
        username=state.get("username", "anonymous"),
        roles=[],
        question=state["question"],
        draft_answer=state["answer"],
        evidence=evidence,
        confidence=state["confidence"],
        department=department,
    )
    return {
        "escalation_ref": ref,
        "answer": (
            f"I'm not confident enough ({state['confidence']}/100) that this answer is accurate, "
            f"so I won't guess. I've escalated your question to a human reviewer — ticket {ref}. "
            f"You can ask 'check my ticket status' to see the review outcome."
        ),
        "source_used": "escalated",
        "citations": [],
        "trace": add_trace(state, f"Confidence check FAILED → escalated to human reviewer ({ref}, dept: {department})"),
    }

def direct_answer(state: AgentState):
    answer = llm().invoke(f"Respond briefly and naturally to: {state['question']}").content
    return {"answer": answer, "source_used": "direct", "trace": add_trace(state, "Direct response → no retrieval")}

def insufficient(state: AgentState):
    return {
        "answer": "I couldn't find enough reliable evidence in the company knowledge base or external search to answer confidently. Please contact the IT help desk or provide more details.",
        "source_used": "insufficient_evidence",
        "trace": add_trace(state, "Stopped → insufficient reliable evidence"),
    }

def build_graph():
    graph = StateGraph(AgentState)
    for name, fn in {
        "route_question": route_question,
        "retrieve_kb": retrieve_kb,
        "grade_kb": grade_kb,
        "check_access_scope": check_access_scope,
        "denied_access": denied_access,
        "search_web": search_web,
        "grade_web": grade_web,
        "rewrite_query": rewrite_query,
        "generate_from_kb": generate_from_kb,
        "generate_from_web": generate_from_web,
        "score_confidence": score_confidence,
        "escalate_to_human": escalate_to_human,
        "return_answer": return_answer,
        "direct_answer": direct_answer,
        "insufficient": insufficient,
    }.items():
        graph.add_node(name, fn)

    graph.add_edge(START, "route_question")
    graph.add_conditional_edges("route_question", route_after_router, {
        "retrieve_kb": "retrieve_kb", "direct_answer": "direct_answer"
    })
    graph.add_edge("retrieve_kb", "grade_kb")
    graph.add_conditional_edges("grade_kb", after_kb, {
        "generate_from_kb": "generate_from_kb", "check_access_scope": "check_access_scope",
        "search_web": "search_web"
    })
    graph.add_conditional_edges("check_access_scope", after_access_scope, {
        "denied_access": "denied_access", "search_web": "search_web"
    })
    graph.add_edge("search_web", "grade_web")
    graph.add_conditional_edges("grade_web", after_web, {
        "generate_from_web": "generate_from_web", "rewrite_query": "rewrite_query", "insufficient": "insufficient"
    })
    graph.add_edge("rewrite_query", "retrieve_kb")
    graph.add_edge("generate_from_kb", "score_confidence")
    graph.add_conditional_edges("score_confidence", after_confidence, {
        "return_answer": "return_answer", "escalate_to_human": "escalate_to_human"
    })
    graph.add_edge("return_answer", END)
    graph.add_edge("escalate_to_human", END)
    graph.add_edge("generate_from_web", END)
    graph.add_edge("denied_access", END)
    graph.add_edge("direct_answer", END)
    graph.add_edge("insufficient", END)
    return graph.compile()

agent_graph = build_graph()

def ask(question: str, username: str = "anonymous", allowed_departments: list[str] | None = None):
    initial: AgentState = {
        "question": question,
        "current_query": question,
        "kb_docs": [],
        "web_results": "",
        "kb_grade": "",
        "web_grade": "",
        "answer": "",
        "source_used": "",
        "retry_count": 0,
        "trace": [],
        "citations": [],
        "username": username,
        "allowed_departments": list(allowed_departments),
        "retrieved_sources": [],
        "kb_empty_in_scope": False,
        "is_internal_topic": False,
        "confidence": 0,
        "escalation_ref": "",
    }
    return agent_graph.invoke(initial)