from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CycleViewSet

router = DefaultRouter()
router.register(r'cycles', CycleViewSet, basename='cycle')  # ✅ Changed from r'' to r'cycles'

urlpatterns = [
    path('', include(router.urls)),
]