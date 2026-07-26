from datetime import datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.api.deps import get_token_service, require_installation
from app.services.rate_limits import InstallationRateLimits
from app.services.tokens import AuthenticatedInstallation, TokenService

router = APIRouter(prefix="/api/v1/installations", tags=["installations"])


class InstallationResponse(BaseModel):
    token: str
    created_at: datetime


def get_rate_limits(request: Request) -> InstallationRateLimits:
    return cast(InstallationRateLimits, request.app.state.rate_limits)


def _client_ip(request: Request) -> str:
    if request.client is None:
        return "unknown"
    return request.client.host


@router.post("", response_model=InstallationResponse, status_code=status.HTTP_201_CREATED)
async def register_installation(
    request: Request,
    service: Annotated[TokenService, Depends(get_token_service)],
    limits: Annotated[InstallationRateLimits, Depends(get_rate_limits)],
) -> InstallationResponse:
    decision = await limits.consume_registration(_client_ip(request))
    if not decision.allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limited")
    issued = await service.create()
    return InstallationResponse(token=issued.token, created_at=issued.created_at)


@router.post("/rotate", response_model=InstallationResponse)
async def rotate_installation(
    installation: Annotated[AuthenticatedInstallation, Depends(require_installation)],
    service: Annotated[TokenService, Depends(get_token_service)],
) -> InstallationResponse:
    issued = await service.rotate(installation.token_id)
    if issued is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid installation token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return InstallationResponse(token=issued.token, created_at=issued.created_at)
