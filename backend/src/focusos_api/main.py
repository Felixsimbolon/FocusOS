from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from focusos_api.database import (
    DatabaseUnavailable,
    InvalidSession,
    check_database_identity,
)

app = FastAPI(title="FocusOS API", version="0.1.0")
bearer = HTTPBearer(auto_error=False)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/database")
def database_health(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict[str, str]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        check_database_identity(credentials.credentials)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Database check unavailable") from exc

    return {"status": "ok"}
