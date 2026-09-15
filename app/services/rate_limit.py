import hashlib
import time
from fastapi import HTTPException, Request
from sqlalchemy import delete
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session
from app.models import RateLimitBucket

def enforce_rate_limit(db: Session, request: Request, scope: str, limit: int, window: int):
    now = int(time.time())
    start = now - now % window
    client = request.client.host if request.client else "unknown"
    key = hashlib.sha256(f"{scope}:{client}:{start}".encode()).hexdigest()
    db.execute(delete(RateLimitBucket).where(RateLimitBucket.expires_at <= now))
    statement = insert(RateLimitBucket).values(key=key, hits=1, expires_at=start + window)
    statement = statement.on_conflict_do_update(index_elements=["key"],
        set_={"hits": RateLimitBucket.hits + 1}).returning(RateLimitBucket.hits)
    hits = db.execute(statement).scalar_one()
    db.commit()
    if hits > limit:
        raise HTTPException(429, "Too many requests. Please try again later.",
                            headers={"Retry-After": str(start + window - now)})