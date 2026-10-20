from __future__ import annotations

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from .schemas import RunRequest, ReanalysisRequest
from .workflow import RunService

service = RunService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    service.resume_pending()
    yield


app = FastAPI(title="Investment Research Agent", version="0.1.0", lifespan=lifespan)
if os.getenv("FRONTEND_ORIGIN"):
    app.add_middleware(CORSMiddleware, allow_origins=[os.environ["FRONTEND_ORIGIN"]], allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Idempotency-Key"])


@app.exception_handler(HTTPException)
async def http_error(request, exc: HTTPException):
    body = exc.detail if isinstance(exc.detail, dict) else {"code": "HTTP_ERROR", "message": str(exc.detail), "retryable": False, "run_id": None}
    return JSONResponse(status_code=exc.status_code, content=body)


@app.exception_handler(RequestValidationError)
async def request_error(request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"code": "INVALID_REQUEST", "message": "请求参数无效", "retryable": False, "run_id": None})


def error(status: int, code: str, message: str, run_id: str | None = None, retryable: bool = False):
    raise HTTPException(status_code=status, detail={"code": code, "message": message, "retryable": retryable, "run_id": run_id})


def required_run(run_id: str) -> dict:
    run = service.store.get(run_id)
    if run is None:
        error(404, "RUN_NOT_FOUND", "未找到任务", run_id)
    return run


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/runs", status_code=202)
def create_run(request: RunRequest):
    run_id = service.submit(request)
    return {"run_id": run_id, "status": "queued", "detail_url": f"/runs/{run_id}"}


@app.get("/runs")
def list_runs(limit: int = Query(default=20, ge=1, le=100)):
    return service.store.list(limit)


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    return required_run(run_id)


@app.get("/runs/{run_id}/artifacts")
def get_artifacts(run_id: str):
    required_run(run_id)
    names = ["00_company.json", "01_research.json", "01_sources.json", "02_metrics.json", "02_analysis.json", "03_report_draft.json", "03_writing_validation.json", "01_evidence_review.json", "04_validation.json", "revision.json"]
    return {name: service.store.read(run_id, name) for name in names if service.store.exists(run_id, name)}


@app.get("/runs/{run_id}/report", response_class=PlainTextResponse)
def get_report(run_id: str, download: bool = False):
    required_run(run_id)
    if not service.store.exists(run_id, "report.md"):
        error(409, "REPORT_NOT_READY", "报告尚未生成", run_id, retryable=True)
    headers = {"Content-Disposition": f'attachment; filename="research-{run_id[:8]}.md"'} if download else {}
    return PlainTextResponse(service.store.read(run_id, "report.md"), media_type="text/markdown; charset=utf-8", headers=headers)


class CompanySelection(BaseModel):
    cik: int


@app.post("/runs/{run_id}/resolve-company", status_code=202)
def resolve_company(run_id: str, selection: CompanySelection):
    required_run(run_id)
    try:
        service.resolve_company(run_id, selection.cik)
    except ValueError as exc:
        error(409, "INVALID_COMPANY_SELECTION", str(exc), run_id)
    return {"run_id": run_id, "status": "queued"}


@app.post("/runs/{run_id}/retry", status_code=202)
def retry_run(run_id: str, idempotency_key: str = Header(..., alias="Idempotency-Key")):
    required_run(run_id)
    try:
        service.retry(run_id, idempotency_key)
    except ValueError as exc:
        error(409, "RETRY_NOT_ALLOWED", str(exc), run_id)
    return {"run_id": run_id, "status": "queued"}


@app.post("/runs/{run_id}/reanalyze", status_code=202)
def reanalyze_run(run_id: str, request: ReanalysisRequest, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200)):
    required_run(run_id)
    try:
        new_id = service.reanalyze(run_id, idempotency_key, request.supplements, request.mode)
    except ValueError as exc:
        error(409, "REANALYSIS_NOT_ALLOWED", str(exc), run_id)
    return {"run_id": new_id, "status": "queued", "detail_url": f"/runs/{new_id}"}
