from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

app = FastAPI(
    title="Smartico.one LLM",
    version="2.0.0",
    description="API for Smartico.one LLM",
    default_response_class=ORJSONResponse,
    license_info={
        "name": "Apache 2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
    },
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "*",
        # "http://localhost:80",
        # "http://localhost:8200",
        # "http://localhost:8300",
        # "http://localhost:8400",
        # "http://localhost:8500",
    ],
    allow_methods=["GET"],
    # allow_headers=["*"],
    # expose_headers=["*"],
    # allow_credentials=True,
)


@app.get("/")
async def root():
    return {"message": "Welcome to APILLM"}
