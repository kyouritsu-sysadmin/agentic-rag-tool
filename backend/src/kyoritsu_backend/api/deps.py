import secrets
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from kyoritsu_backend.core.auth import Principal

bearer = HTTPBearer(auto_error=False)


def current_principal(
    request: Request, value: HTTPAuthorizationCredentials | None = Depends(bearer)
):
    if value:
        for credential in request.app.state.settings.credentials:
            if secrets.compare_digest(
                value.credentials.encode(), credential.token.get_secret_value().encode()
            ):
                return Principal(credential.subject, tuple(credential.companies), credential.admin)
    raise HTTPException(
        401, "A valid access token is required", headers={"WWW-Authenticate": "Bearer"}
    )


def application(request: Request):
    return request.app.state
