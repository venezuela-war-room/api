import time
from collections.abc import Awaitable, Callable
from typing import Any

import posthog
from fastapi import Request, Response

from app.config import settings

APP_NAME = "terremoto-venezuela-war-room-api"
SYSTEM_DISTINCT_ID = "terremoto_venezuela_war_room_api"

if settings.posthog_api_key:
    posthog.project_api_key = settings.posthog_api_key
    posthog.host = settings.posthog_host
    posthog.disabled = False
else:
    posthog.disabled = True


def analytics_enabled() -> bool:
    return bool(settings.posthog_api_key)


def capture_event(event: str, properties: dict[str, Any] | None = None) -> None:
    if not analytics_enabled():
        return

    posthog.capture(
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
    if analytics_enabled():
        posthog.shutdown()
