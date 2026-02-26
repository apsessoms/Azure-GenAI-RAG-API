# Azure GenAI RAG API

## What This Project Is 

This is a **REST API that answers questions using your own documents** — not just what GPT already knows. You ask it a question, it searches a knowledge base for the most relevant content, hands that content to GPT, and returns an answer with citations. That pattern is called RAG: Retrieval-Augmented Generation.

**The practical application:** Instead of a generic chatbot, you get one that only knows what's in your indexed documents and has to cite its sources. For a DoD or federal environment, that's the difference between a toy and something you can actually trust.

---

## How the Project Is Organized

```
Azure-GenAI-RAG-API/
├── app/
│   ├── main.py          ← The API itself — three endpoints
│   ├── config.py        ← Configuration / environment variable loading
│   └── search_client.py ← Connects to Azure AI Search
└── requirements.txt     ← FastAPI, Uvicorn, python-dotenv
```



---

## The Three Pieces

### 1. `config.py` — Settings Management

```python
@dataclass(frozen=True)
class Settings:
    search_endpoint: str
    search_index_name: str
    search_api_key: str
    aoai_endpoint: str
    aoai_api_key: str
    aoai_deployment: str

def get_settings() -> Settings:
    return Settings(
        search_endpoint=os.environ["SEARCH_ENDPOINT"],
        ...
    )
```

**What it does:** Pulls all configuration from environment variables and packages them into an immutable `Settings` object. If any required variable is missing, it fails immediately at startup — not silently mid-request.

**The `frozen=True` means the settings can't be accidentally mutated at runtime. All six values come from env vars, so there are no hardcoded credentials anywhere in the codebase. In a production deployment, these would be backed by Key Vault references.

---

### 2. `search_client.py` — Azure AI Search Connection

```python
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential

def build_search_client(endpoint: str, index_name: str, api_key: str) -> SearchClient:
    return SearchClient(
        endpoint=endpoint,
        index_name=index_name,
        credential=AzureKeyCredential(api_key),
    )
```

**What it does:** One function that builds and returns a connected `SearchClient` pointed at your Azure AI Search index. Takes the endpoint, index name, the API key & returns a client ready to query.

Keeps the authentication/connection logic out of the main application logic. If you ever swap the credential type (e.g., moving from API key to Managed Identity), you change it in one place.

**Dev Environment was used for this project:** In a production IL5 environment, you'd replace `AzureKeyCredential(api_key)` with `ManagedIdentityCredential()` — no API key at all. The rest of the code doesn't change because the `SearchClient` interface is the same either way.

---

### 3. `main.py` — The API (Three Endpoints)

This is the core of the project. It runs three endpoints:

---

#### `GET /health`

```python
@app.get("/health")
def health():
    return {"status": "ok"}
```

Simple liveness check. Tells a load balancer or monitoring tool that the API is up. Every production API needs this.

---

#### `GET /debug/env`

```python
@app.get("/debug/env")
def debug_env():
    return {
        "SEARCH_ENDPOINT": os.getenv("SEARCH_ENDPOINT"),
        "SEARCH_API_KEY_set": bool(os.getenv("SEARCH_API_KEY")),
        ...
    }
```

A diagnostic endpoint that shows which environment variables are loaded — and crucially, for secrets it only returns `True` or `False` (whether the key is set), never the actual value. Useful when you're first deploying and need to verify the environment is configured correctly without exposing credentials in the response.

---

#### `POST /ask` — The RAG Pipeline

Here's what happens when you call it:

```python
class AskRequest(BaseModel):
    question: str
```

First, the request is validated by Pydantic. If `question` is missing or not a string, FastAPI rejects it with a 422 before your code even runs.

**Step 1: Search**

```python
results = client.search(
    search_text=req.question,
    top=5,
)
```

Takes the user's question as-is and runs it against the Azure AI Search index, pulling the top 5 most relevant document chunks. This is the "retrieval" part of RAG.

**Step 2: Build Context**

```python
sources = []
for r in results:
    doc = dict(r)
    sources.append({
        "id": doc.get("id"),
        "source_uri": doc.get("source_uri"),
        "content_preview": (doc.get("content") or "")[:300],
    })

context = "\n\n".join(
    [f"[{i+1}] {s['content_preview']}" for i, s in enumerate(sources)]
)
```

Formats the search results into a numbered list: `[1] ...text...`, `[2] ...text...`. This numbered format is intentional — it's what tells GPT how to cite its sources in the answer.

**Step 3: Generate Answer**

```python
resp = aoai.chat.completions.create(
    model=s.aoai_deployment,
    messages=[
        {
            "role": "system",
            "content": (
                "You answer using ONLY the provided sources. "
                "If the answer is not in the sources, say you don't know. "
                "Cite sources like [1], [2]."
            ),
        },
        {
            "role": "user",
            "content": f"Question: {req.question}\n\nSources:\n{context}",
        },
    ],
    temperature=0.2,
)
```

The system prompt is the key part here. It does three things:
- **"ONLY the provided sources"** — prevents the model from using its training data to fill gaps. Every answer has to come from the retrieved documents.
- **"If the answer is not in the sources, say you don't know"** — prevents hallucination. If the documents don't contain the answer, the model admits it rather than making something up.
- **"Cite sources like [1], [2]"** — forces the model to link its claims back to specific retrieved chunks, making answers auditable.

`temperature=0.2` keeps responses factual and consistent rather than creative. For a knowledge retrieval use case, you want low temperature.

**Step 4: Return Everything**

```python
return {
    "answer": answer,
    "question": req.question,
    "sources": sources,
}
```

The response includes the answer, the original question (useful for logging/tracing), and the source chunks that informed the answer. A frontend can use `source_uri` to link directly to the source document.

---

## The Full Request/Response Flow

```
User sends: POST /ask  {"question": "What is the password policy?"}
                │
                ▼
    Azure AI Search ──► top 5 chunks from your index
                │
                ▼
    Prompt assembled:
      System: "Answer from sources only. Cite [1], [2]..."
      User:   "Question: What is the password policy?
               Sources:
               [1] Passwords must be at least 12 characters...
               [2] Passwords expire every 90 days..."
                │
                ▼
    Azure OpenAI (GPT) generates answer with citations
                │
                ▼
User receives: {
    "answer": "Passwords must be at least 12 characters [1] and expire every 90 days [2].",
    "sources": [...],
    "question": "What is the password policy?"
}
```

---

## Deploying Into Production

Once fully tested and validated in dev, this is how I would push to production.

**1. Swap API key auth for Managed Identity**

```python
# Current (fine for dev):
credential=AzureKeyCredential(api_key)

# Production (no secrets anywhere):
from azure.identity import ManagedIdentityCredential
credential=ManagedIdentityCredential()
```

API keys are long-lived secrets. In IL5, everything should authenticate via Managed Identity so that credentials rotate automatically and all access is in the Azure AD audit log.

**2. Add vector / hybrid search**

The current `/ask` endpoint uses keyword search only. For a production RAG system, you'd add vector embeddings to the query so semantically similar content surfaces even if the exact keywords don't match. Azure AI Search supports hybrid (keyword + vector) with a single API call.

**3. Remove the `/debug/env` endpoint before production**

It's a useful dev tool but shouldn't be reachable in a production deployment — even though it doesn't expose secret values, it exposes your infrastructure topology.

**4. Add structured error responses**

```python
# Current:
except Exception as e:
    return {"error": str(e)}

# Better: use FastAPI's HTTPException for proper status codes
from fastapi import HTTPException
raise HTTPException(status_code=502, detail="Search service unavailable")
```

Returning a 200 with an error body means monitoring tools can't detect failures by status code. Proper HTTP error codes let your alerting catch problems automatically.

**5. Add conversation history for multi-turn Q&A**

The current API is stateless — each `/ask` call is independent. For a chat interface, you'd pass the last N turns of conversation history into the messages array so the model can handle follow-up questions like "what about the exceptions to that policy?"

---

## Summary

**What is this project about?":**
> "It's a FastAPI backend that implements RAG — retrieval-augmented generation. You send it a question, it searches an Azure AI Search index for the most relevant document chunks, assembles those into a grounded prompt, and calls Azure OpenAI to generate an answer with source citations. The system prompt enforces that GPT can only answer from the retrieved content — if the answer isn't in the index, it says so rather than hallucinating."

**Things to change before deploying into production:**
> "The main thing I'd change for IL5 production use is replacing the API key authentication with Managed Identity — no long-lived secrets anywhere in the system. I'd also add hybrid search so the retrieval catches semantically similar content that doesn't share exact keywords, and I'd remove the debug endpoint. The error handling would move to proper HTTP status codes so monitoring tools can catch failures automatically."

**How does the grounding work?:**
> "The system prompt is doing the heavy lifting. It tells the model it can only use the provided sources — not its training data — and that if the answer isn't there it should say it doesn't know. The sources are formatted as a numbered list matching the citation format in the instructions, so the model naturally outputs [1], [2] references that link back to specific document chunks. That makes every answer auditable."
