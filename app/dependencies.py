"""FastAPI dependencies that resolve the calling principal."""

from typing import Annotated

from fastapi import Header, HTTPException, Path, status

from .models import Principal

ORGANIZATION_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,62}$"


def current_principal(
    organization_id: Annotated[str, Path(pattern=ORGANIZATION_ID_PATTERN)],
    x_user_id: Annotated[str | None, Header()] = None,
) -> Principal:
    """Build the principal from the authenticated user header and the path."""
    if not x_user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing user")
    return Principal(user_id=x_user_id, organization_id=organization_id)
