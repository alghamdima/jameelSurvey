import secrets
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 25_000_000

def optimize_and_save_image(file_obj, upload_dir: Path, prefix: str = "img", max_dimension: int = 1920) -> str:
    file_obj.seek(0, 2)
    size = file_obj.tell()
    file_obj.seek(0)
    if not 0 < size <= MAX_UPLOAD_BYTES:
        raise ValueError("Image must be between 1 byte and 10 MB")
    try:
        with Image.open(file_obj) as source:
            if source.format not in {"PNG", "JPEG", "WEBP", "GIF"} or source.width * source.height > MAX_PIXELS:
                raise ValueError("Unsupported image or excessive dimensions")
            source.seek(0)
            img = ImageOps.exif_transpose(source)
            img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
            img = img.convert("RGBA" if "A" in img.getbands() or "transparency" in img.info else "RGB")
            filename = f"{prefix}_{secrets.token_hex(16)}.webp"
            img.save(upload_dir / filename, "WEBP", quality=82, method=4)
            return filename
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Invalid image file") from exc