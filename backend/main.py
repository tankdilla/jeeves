# main.py
from dotenv import load_dotenv
load_dotenv()

import time
import uuid
from fastapi import FastAPI, Request, Response
from routers import influencers, campaigns, threads, messages
from db import engine
from logging_config import get_logger
from routers.webhooks_sendgrid import router as sendgrid_webhooks_router

logger = get_logger("jeeves", component="api")

app = FastAPI(title="Jeeves Influencer Outreach MVP")

@app.on_event("startup")
def on_startup():
    logger.info("API started", extra={"db_url": str(engine.url)})

@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    start = time.time()

    # Process
    try:
        response: Response = await call_next(request)
    except Exception:
        logger.exception(
            "Unhandled exception",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
            },
        )
        raise

    duration_ms = int((time.time() - start) * 1000)

    logger.info(
        "request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )

    response.headers["x-request-id"] = request_id
    return response

app.include_router(influencers.router, prefix="/influencers", tags=["influencers"])
app.include_router(campaigns.router, prefix="/campaigns", tags=["campaigns"])
app.include_router(threads.router, prefix="/threads", tags=["threads"])
app.include_router(messages.router, prefix="/messages", tags=["messages"])

app.include_router(sendgrid_webhooks_router)

@app.get("/health")
def health():
    return {"ok": True}
