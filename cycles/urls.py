from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CycleViewSet

router = DefaultRouter()
router.register(r'', CycleViewSet, basename='cycle')  # empty prefix — already under /api/cycles/

urlpatterns = [
    path('', include(router.urls)),
]