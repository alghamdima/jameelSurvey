import os
import secrets
from pathlib import Path
from PIL import Image

def optimize_and_save_image(file_obj, upload_dir: Path, prefix: str = "img", max_dimension: int = 1920) -> str:
    """
    يقوم بحفظ الصورة وضغطها وتغيير أبعادها تلقائياً بتقنية متطورة (LANCZOS Resampling)
    لتقليص الحجم من عشرات الميجابايتات إلى مئات الكيلوبايتات مع المحافظة على دقة وجودة عالية جداً.
    """
    token = secrets.token_hex(8)
    filename = f"{prefix}_{token}.webp"
    filepath = upload_dir / filename

    try:
        file_obj.seek(0)
        with Image.open(file_obj) as img:
            # الحفاظ على الشفافية في حال وجودها
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                img = img.convert("RGBA")
                fmt = "WEBP"
            else:
                img = img.convert("RGB")
                fmt = "WEBP"

            # تغيير الأبعاد إذا كانت أكبر من الحد الأقصى مع الحفاظ على النسبة
            if max(img.size) > max_dimension:
                img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

            # حفظ بصيغة WebP الحديثة فائقة الضغط والسرعة
            img.save(filepath, format=fmt, quality=82, method=4)
            return filename
    except Exception:
        # Fallback في حال حدوث أي خطأ في فك الترميز: حفظ مباشر
        fallback_name = f"{prefix}_{token}.png"
        fallback_path = upload_dir / fallback_name
        file_obj.seek(0)
        with open(fallback_path, "wb") as f:
            f.write(file_obj.read())
        return fallback_name
