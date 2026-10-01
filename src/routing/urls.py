from django.urls import path

from routing.views import HealthView, RoutePlanView

urlpatterns = [
    path('health/', HealthView.as_view(), name='health'),
    path('routes/plan/', RoutePlanView.as_view(), name='route-plan'),
]
