import traceback
from fastapi import FastAPI
from pydantic import BaseModel
from app.config import get_settings
from app.search_client import build_search_client
from openai import AzureOpenAI

app = FastAPI(title="RAG API", version="0.2.0")

import os

@app.get("/debug/env")
def debug_env():
    return {
        "SEARCH_ENDPOINT": os.getenv("SEARCH_ENDPOINT"),
        "SEARCH_INDEX_NAME": os.getenv("SEARCH_INDEX_NAME"),
        "SEARCH_API_KEY_set": bool(os.getenv("SEARCH_API_KEY")),
        "AOAI_ENDPOINT": os.getenv("AOAI_ENDPOINT"),
        "AOAI_DEPLOYMENT": os.getenv("AOAI_DEPLOYMENT"),
        "AOAI_API_KEY_set": bool(os.getenv("AOAI_API_KEY")),
    }

class AskRequest(BaseModel):
    question: str

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/ask")
def ask(req: AskRequest):
    try:
        s = get_settings()
        client = build_search_client(
            s.search_endpoint,
            s.search_index_name,
            s.search_api_key
        )

        results = client.search(
            search_text=req.question,
            top=5,
        )

        sources = []
        for r in results:
            doc = dict(r)

            sources.append({
                "id": doc.get("id"),
                "source_uri": doc.get("source_uri"),
                "content_preview": (doc.get("content") or "")[:300],
            })

                # Build context from retrieved docs
        context = "\n\n".join(
            [f"[{i+1}] {s['content_preview']}" for i, s in enumerate(sources)]
        )

        # Call Azure OpenAI
        aoai = AzureOpenAI(
            api_key=s.aoai_api_key,
            azure_endpoint=s.aoai_endpoint,
            api_version="2024-02-15-preview",
        )

        resp = aoai.chat.completions.create(
            model=s.aoai_deployment,  # deployment name: "chat"
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

        answer = resp.choices[0].message.content

        return {
            "answer": answer,
            "question": req.question,
            "sources": sources,
        }

    except Exception as e:
        return {"error": str(e)}