from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers.ask import router as ask_router
from app.api.routers.documents import router as documents_router

app = FastAPI(
    title="AI Engineer Portfolio — Track",
    version="0.1.0",
    description="RAG over scientific/technical documents with forced citations",
    # No default_response_class=ORJSONResponse: FastAPI now serializes directly to JSON
    # bytes via Pydantic once a response_model/return type is set (every route here
    # has one), which is faster and doesn't need a custom response class -- and the
    # pinned FastAPI version deprecates ORJSONResponse for exactly this reason.
    license_info={
        "name": "Apache 2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
    },
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
)

app.include_router(ask_router)
app.include_router(documents_router)


@app.get("/")
async def root() -> dict:
    return {"message": "AI Engineer Portfolio API"}
