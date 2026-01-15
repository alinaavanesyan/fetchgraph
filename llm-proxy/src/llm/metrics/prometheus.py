from __future__ import annotations

import os

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, CollectorRegistry, generate_latest

router = APIRouter()


def make_registry() -> CollectorRegistry:
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        raise RuntimeError("PROMETHEUS_MULTIPROC_DIR is unsupported in single-process metrics mode")
    return REGISTRY  # type: ignore[return-value]


def metrics_response() -> Response:
    registry = make_registry()
    data = generate_latest(registry)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@router.get("/metrics", include_in_schema=False)
async def metrics():
    return metrics_response()
