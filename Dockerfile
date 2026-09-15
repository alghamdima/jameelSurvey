# syntax=docker/dockerfile:1
FROM python:3.11-slim

# منع بايثون من كتابة ملفات pyc وضمان إخراج السجلات مباشرة
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# تثبيت متطلبات النظام الأساسية لـ SQLite والفحص
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# تثبيت تبعات بايثون
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.lock

# نسخ كود التطبيق وملفات التهيئة
COPY app/ app/
COPY locales/ locales/
COPY alembic/ alembic/
COPY alembic.ini .
# Production secrets are supplied at runtime.

# إنشاء مجلد البيانات للتخزين الدائم وضبط الصلاحيات
RUN mkdir -p /app/data

EXPOSE 8000

# سكريبت بدء التشغيل لتطبيق ترحيلات Alembic ثم تشغيل Uvicorn
CMD ["sh", "-c", "alembic upgrade head && python -m app.cli.bootstrap && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
