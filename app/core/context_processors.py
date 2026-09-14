import urllib.parse
from app.core.config import settings

def get_base_path() -> str:
    return urllib.parse.urlparse(settings.BASE_URL).path.rstrip('/')

def app_url(path: str) -> str:
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    path = path if path.startswith("/") else "/" + path
    bp = get_base_path()
    if bp:
        if path == bp or path.startswith(bp + "/"):
            return path
        return f"{bp}{path}"
    return path
