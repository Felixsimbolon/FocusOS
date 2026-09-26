from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from focusos_api.database import (
    DatabaseUnavailable,
    InvalidSession,
    check_database_identity,
)
from focusos_api.profiles import (
    ProfileEnvelope,
    ProfileInput,
    read_profile,
    save_profile,
)

app = FastAPI(title="FocusOS API", version="0.1.0")
bearer = HTTPBearer(auto_error=False)


def require_access_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required")
    return credentials.credentials


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/database")
def database_health(access_token: str = Depends(require_access_token)) -> dict[str, str]:
    try:
        check_database_identity(access_token)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Database check unavailable") from exc
    return {"status": "ok"}


@app.get("/profile", response_model=ProfileEnvelope)
def profile_get(access_token: str = Depends(require_access_token)) -> ProfileEnvelope:
    try:
        return ProfileEnvelope(profile=read_profile(access_token))
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Profile unavailable") from exc


@app.put("/profile", response_model=ProfileEnvelope)
def profile_put(
    profile: ProfileInput,
    access_token: str = Depends(require_access_token),
) -> ProfileEnvelope:
    try:
        return ProfileEnvelope(profile=save_profile(access_token, profile))
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Profile unavailable") from exc
