from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('authentication.urls')),
    path('api/cycles/', include('cycles.urls')),
    path('api/members/', include('members.urls')),
    path('api/savings/', include('savings.urls')),
    path('api/dashboard/', include('dashboard.urls')),  # ← ADD THIS LINE
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)