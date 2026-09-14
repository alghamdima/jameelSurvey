from pathlib import Path
import urllib.parse
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.routers import public, admin

app = FastAPI(
    title=settings.APP_NAME,
    description="عبد اللطيف جميل للتمويل",
    version="1.0.0",
    debug=settings.DEBUG
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# تضمين موجهات المسارات على المستوى الجذري
app.include_router(public.router)
app.include_router(admin.router)

# دعم المسار الفرعي (مثل /survey) تلقائياً عند ضبط BASE_URL
base_path = urllib.parse.urlparse(settings.BASE_URL).path.rstrip('/')
if base_path:
    sub_app = FastAPI(
        title=settings.APP_NAME,
        description="عبد اللطيف جميل للتمويل",
        version="1.0.0",
        debug=settings.DEBUG
    )
    sub_app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    sub_app.include_router(public.router)
    sub_app.include_router(admin.router)
    app.mount(base_path, sub_app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
