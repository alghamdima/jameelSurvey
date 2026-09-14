import json
from pathlib import Path
from typing import Any

LOCALES_DIR = Path(__file__).resolve().parent.parent.parent / "locales"

_translations: dict[str, dict[str, Any]] = {}

def load_translations() -> None:
    """تحميل ملفات الترجمة لكل من العربية والإنجليزية."""
    global _translations
    for lang in ["ar", "en"]:
        file_path = LOCALES_DIR / f"{lang}.json"
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                _translations[lang] = json.load(f)
        else:
            _translations[lang] = {}

def get_text(key: str, lang: str = "ar", **kwargs: Any) -> str:
    """
    استرجاع النص المترجم باستخدام مفتاح هرمي مثل 'header.title'.
    إذا لم يتم العثور على المفتاح في اللغة المطلوبة، يتم البحث في اللغة الافتراضية (العربية) أو إرجاع المفتاح نفسه.
    """
    if not _translations:
        load_translations()
    
    current_lang = lang if lang in _translations else "ar"
    tokens = key.split(".")
    
    # محاولة الاستخراج من اللغة الحالية
    val: Any = _translations.get(current_lang, {})
    for token in tokens:
        if isinstance(val, dict):
            val = val.get(token)
        else:
            val = None
            break
            
    # احتياطياً من اللغة العربية
    if val is None and current_lang != "ar":
        val = _translations.get("ar", {})
        for token in tokens:
            if isinstance(val, dict):
                val = val.get(token)
            else:
                val = None
                break
                
    if val is None:
        return key

    if kwargs and isinstance(val, str):
        try:
            return val.format(**kwargs)
        except Exception:
            return val
            
    return str(val)

# تهيئة القواميس عند بدء التشغيل
load_translations()
