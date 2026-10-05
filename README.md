# 🤖 Enterprise IT Support Agentic RAG Copilot

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100.0%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agentic%20Workflow-orange.svg)](https://www.langchain.com/langgraph)
[![Pinecone](https://img.shields.io/badge/Pinecone-Vector%20DB-000000.svg)](https://www.pinecone.io/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)

An production-grade **Forward Deployed Engineering (FDE)** solution that transforms a static notebook RAG workflow into an interactive, self-correcting IT Support Copilot for enterprise environments.

---

## 📌 Problem Statement & Overview

Enterprise IT helpdesks face high volumes of repetitive support tickets regarding VPN access, password resets, MFA policies, and software configurations. Traditional static RAG implementations often fail when:
- Internal documentation is incomplete, missing, or outdated.
- Generic vector searches return irrelevant chunk context.
- Answers require real-time or public web information (e.g., live vendor outage reports).

### 💡 Solution

The **Agentic RAG Copilot** solves this by shifting from linear retrieval (*Retrieve $\rightarrow$ Generate*) to an **autonomous graph execution loop**:
1. **Prioritizes Private Knowledge:** Searches internal company policy documentation first via semantic vector search.
2. **Evaluates Evidence Quality:** Grades retrieved context for relevance before generating an answer.
3. **Dynamic Web Fallback:** Triggers real-time web search (**Tavily**) only when private knowledge is insufficient or missing.
4. **Self-Correction & Query Rewriting:** Automatically reformulates ambiguous or poor user queries with loop guardrails.
5. **Traceability & Auditability:** Exposes full reasoning paths and logs decision trees for administrator oversight.

---

## 🏗️ System Architecture & Workflow

                    ┌──────────────────┐
                    │   User / Admin   │
                    └────────┬─────────┘
                             │
                     POST /api/chat
                             ▼
                    ┌──────────────────┐
                    │ FastAPI Backend  │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │    LangGraph     │
                    │ Agent Control    │
                    └────────┬─────────┘
                             │
        ┌────────────────────┴────────────────────┐
        ▼                                         ▼
┌─────────────────┐                       ┌─────────────────┐
│   Private KB    │                       │   Tavily Web    │
│ (Pinecone Vector│                       │     Search      │
│      DB)        │                       └────────┬────────┘
└────────┬────────┘                                │
└────────────────────┬────────────────────┘
▼
┌──────────────────┐
│    Groq LLM      │
│ Grounded Answer  │
└──────────────────┘


### 🧠 Agentic Decision Graph

- **[1] Intent Router:** Determines whether the input is a simple greeting vs. a complex IT support query.
- **[2] Private Retrieval:** Queries internal vector indices (**Pinecone**) using semantic embeddings.
- **[3] Evidence Evaluator:** Evaluates private document relevance.
  - If **GOOD**: Generates response directly grounded in private documents.
  - If **WEAK**: Passes control to the web retrieval agent.
- **[4] Web Search Fallback:** Executes external web searches via **Tavily**.
- **[5] Web Evidence Evaluator:** Evaluates web search results.
  - If **GOOD**: Generates a response with an explicit external-source citation/warning.
  - If **WEAK**: Triggers the Query Rewriter.
- **[6] Self-Correction Loop:** Rewrites the query to improve context matching and retries retrieval up to a maximum iteration limit.

---

## 💻 Tech Stack

| Layer | Technology | Function |
| :--- | :--- | :--- |
| **Agentic Framework** | **LangGraph** | Stateful execution loops, conditional branching, and agent state management |
| **LLM Engine** | **Groq** (`openai/gpt-oss-20b`) / **OpenAI** (`gpt-4o-mini`) | Fast inference for intent routing, evidence grading, query rewriting, and answer generation |
| **Embeddings** | **HuggingFace** (`all-MiniLM-L6-v2`) / **OpenAI** | 384-dimensional dense semantic vectors |
| **Vector DB** | **Pinecone** | Cloud-native vector store with metadata filtering and namespace isolation |
| **Web Search Engine** | **Tavily API** | Agentic web search engine optimized for LLM context retrieval |
| **Backend API** | **FastAPI** & **Uvicorn** | Asynchronous REST endpoints (`POST /api/chat`, `POST /api/ingest`, `GET /api/health`) |
| **Frontend UI** | **HTML5 / CSS3 / Vanilla JS** | Web interface displaying real-time reasoning traces and interactive document uploads |
| **Audit & Storage** | **SQLite** | Audit logging of agent traces, query routes, and system logs |
| **DevOps & Containerization** | **Docker** & **Python 3.10+** | Reproducible builds and microservice deployment |

---

## 📂 Repository Structure

```text
.
├── app/
│   ├── api/
│   │   └── routes.py              # API endpoints (Chat, Ingestion, Health)
│   ├── core/
│   │   ├── config.py              # App config & environment variables
│   │   └── logging.py             # System logging configuration
│   ├── rag/
│   │   ├── state.py               # LangGraph state schema & node definitions
│   │   ├── vectorstore.py         # Pinecone index management & embeddings
│   │   └── workflow.py            # Complete Agentic RAG graph definition
│   ├── services/
│   │   ├── audit.py               # SQLite execution trace logger
│   │   └── ingestion.py           # Document parsing (.pdf, .docx, .md, .txt) & chunking
│   └── main.py                    # FastAPI application initialization
├── data/
│   └── sample_kb/                 # Default knowledge base policies
├── static/                        # Frontend UI static assets (CSS, JS)
├── templates/                     # HTML templates
├── tests/                         # Unit and integration test suites
├── Dockerfile                     # Docker container configuration
├── ingest_sample_kb.py            # Local KB initialization script
├── requirements.txt               # Python package dependencies
└── run.py 

                        # Application entrypoint
⚡ Quick Start & Setup

Prerequisites
Python 3.10+ installed

Docker (Optional, for containerized run)

API Keys for Groq, OpenAI, Pinecone, and Tavily

1️⃣ Installation

Clone the repository and set up a virtual environment:

Bash
git clone [https://github.com/solutionundertaken95/Agentic-Rag-Application.git](https://github.com/solutionundertaken95/Agentic-Rag-Application.git)
cd Agentic-Rag-Application

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate


# Install dependencies

pip install -r requirements.txt

2️⃣ Environment Configuration

Create a .env file in the project root directory:

Code snippet
# LLM Configuration
GROQ_API_KEY=your_groq_api_key
OPENAI_API_KEY=your_openai_api_key
GROQ_MODEL=openai/gpt-oss-20b
OPENAI_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small

# Vector Database & Search
PINECONE_API_KEY=your_pinecone_api_key
PINECONE_INDEX_NAME=fde-it-support-rag
PINECONE_NAMESPACE=company-it-kb
TAVILY_API_KEY=your_tavily_api_key

# Security & Admin
ADMIN_API_KEY=your_secure_admin_key
APP_ENV=development


3️⃣ Ingest Initial Knowledge Base
Populate the Pinecone index with sample IT handbook and runbook documents:

Bash
python ingest_sample_kb.py


4️⃣ Run the Application
Start the FastAPI application server:

Bash
python run.py
Web UI: Access at http://127.0.0.1:8000

Interactive API Docs (Swagger): Access at http://127.0.0.1:8000/docs

🐳 Docker Deployment
To build and run the application in a Docker container:

Bash
# Build Docker image
docker build -t agentic-rag-copilot .

# Run container
docker run -d -p 8000:8000 --env-file .env --name it-copilot agentic-rag-copilot
🔒 Security & Admin Ingestion
The copilot features an authenticated endpoint (POST /api/ingest) for uploading new policy documents dynamically without restarting the server:

Supported File Formats: .pdf, .docx, .md, .txt

Authentication: Protected by the X-Admin-Key header matching ADMIN_API_KEY in your .env.

📄 License
Distributed under the MIT License. See LICENSE for more information.