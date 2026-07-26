from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services.tokens import AuthenticatedInstallation, TokenService

_bearer = HTTPBearer(auto_error=False)


def get_token_service(request: Request) -> TokenService:
    return cast(TokenService, request.app.state.token_service)


async def require_installation(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    service: Annotated[TokenService, Depends(get_token_service)],
) -> AuthenticatedInstallation:
    installation = None
    if credentials is not None and credentials.scheme.lower() == "bearer":
        installation = await service.authenticate(credentials.credentials)
    if installation is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid installation token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return installation
