from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from app.core.config import settings
from app.core.auth import ensure_admin_user_exists
from app.core.csrf import new_csrf_token
from app.core.tokens import verify_token
from app.db.session import SessionLocal
from app.routers import public, admin

def initialize():
    settings.validate_runtime()
    with SessionLocal() as db:
        ensure_admin_user_exists(db)

@asynccontextmanager
async def lifespan(app):
    await run_in_threadpool(initialize)
    yield

app = FastAPI(title=settings.APP_NAME, version="1.1.0", debug=settings.DEBUG, lifespan=lifespan,
              docs_url="/docs" if settings.DEBUG else None,
              redoc_url=None, openapi_url="/openapi.json" if settings.DEBUG else None)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    # Bound declared bodies before parsing multipart forms; individual images are capped as well.
    length = request.headers.get("content-length")
    if length:
        try:
            if int(length) < 0 or int(length) > 22 * 1024 * 1024:
                return JSONResponse({"detail": "Request body too large"}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
    cookie = request.cookies.get("csrf_token", "")
    csrf = cookie if verify_token(cookie, "csrf") else new_csrf_token()
    request.state.csrf_token = csrf
    response = await call_next(request)
    if csrf != cookie:
        response.set_cookie("csrf_token", csrf, httponly=True, secure=settings.cookie_secure,
                            samesite="lax", path=settings.base_path or "/",
                            max_age=settings.ADMIN_SESSION_TTL_SECONDS)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if "/static/" not in request.url.path:
        response.headers["Cache-Control"] = "no-store"
    return response

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(public.router)
app.include_router(admin.router)
if settings.base_path:
    sub_app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    sub_app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    sub_app.include_router(public.router)
    sub_app.include_router(admin.router)
    app.mount(settings.base_path, sub_app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)