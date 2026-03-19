from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.routers import health


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(" Starting arXiv RAG API...")
    yield
    print("Shutting down arXiv RAG API...")


app = FastAPI(
    title="arXiv Paper Curator",
    description="Production RAG system for academic paper search and Q&A",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── routers ──────────────────────────────
app.include_router(health.router, tags=["health"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
