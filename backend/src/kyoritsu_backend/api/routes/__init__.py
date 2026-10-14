from fastapi import APIRouter
from . import auth, models, retrieval, threads, runs, documents, jobs

router = APIRouter()
for module in (auth, models, retrieval, threads, runs, documents, jobs):
    router.include_router(module.router)
