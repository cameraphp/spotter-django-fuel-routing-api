from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from routing.planner import plan_route
from routing.services.errors import (
    NoFeasiblePlanError,
    ProviderError,
    ProviderTimeout,
    StationCoordinatesNotPrepared,
    USAValidationError,
)


def _error_body(code: str, detail: str) -> dict[str, Any]:
    return {'code': code, 'detail': detail}


class HealthView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request: Request) -> Response:
        return Response({'status': 'ok'}, status=status.HTTP_200_OK)


class RoutePlanView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request: Request) -> Response:
        try:
            payload = request.data
            result = plan_route(payload)
        except ValidationError as exc:
            if isinstance(exc.detail, dict) and len(exc.detail):
                msg = '; '.join(
                    f'{k}: {v}' for k, v in exc.detail.items()
                ) if isinstance(exc.detail, dict) else str(exc.detail)
            else:
                msg = str(exc.detail) if isinstance(exc.detail, str) else str(exc.detail)
            body = _error_body('VALIDATION_ERROR', str(msg))
            return Response(body, status=status.HTTP_400_BAD_REQUEST)
        except USAValidationError as exc:
            body = _error_body(exc.code, exc.detail)
            return Response(body, status=status.HTTP_400_BAD_REQUEST)
        except StationCoordinatesNotPrepared as exc:
            body = _error_body(exc.code, exc.detail)
            return Response(body, status=428)
        except NoFeasiblePlanError as exc:
            body = _error_body(exc.code, exc.detail)
            return Response(body, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except ProviderTimeout as exc:
            body = _error_body(exc.code, exc.detail)
            return Response(body, status=status.HTTP_504_GATEWAY_TIMEOUT)
        except ProviderError as exc:
            body = _error_body(exc.code, exc.detail)
            return Response(body, status=status.HTTP_502_BAD_GATEWAY)
        return Response(result, status=status.HTTP_200_OK)
