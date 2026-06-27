import time
from collections.abc import Awaitable, Callable
from typing import Any

import posthog
from fastapi import Request, Response

from app.config import settings

APP_NAME = "terremoto-venezuela-war-room-api"
SYSTEM_DISTINCT_ID = "terremoto_venezuela_war_room_api"

_client = (
    posthog.Posthog(
        settings.posthog_api_key,
        host=settings.posthog_host,
        disabled=False,
    )
    if settings.posthog_api_key
    else None
)


def analytics_enabled() -> bool:
    return _client is not None


def capture_event(event: str, properties: dict[str, Any] | None = None) -> None:
    if not _client:
        return

    _client.capture(
        event,
        distinct_id=SYSTEM_DISTINCT_ID,
        properties={
            "app": APP_NAME,
            "env": settings.environment,
            **(properties or {}),
        },
    )


async def analytics_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    started_at = time.perf_counter()
    status_code = 500

    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        route_path = getattr(route, "path", request.url.path)
        duration_ms = round((time.perf_counter() - started_at) * 1000)

        capture_event(
            "api_request_completed",
            {
                "method": request.method,
                "route": route_path,
                "statusCode": status_code,
                "durationMs": duration_ms,
                "isError": status_code >= 500,
                "isAdminRoute": route_path.startswith("/api/v1/admin"),
                "isWrite": request.method in {"POST", "PATCH", "PUT", "DELETE"},
            },
        )


async def shutdown_analytics() -> None:
    if _client:
        _client.shutdown()
