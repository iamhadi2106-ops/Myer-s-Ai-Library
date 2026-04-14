from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

handler400 = 'library.views.error_400'
handler403 = 'library.views.error_403'
handler404 = 'library.views.error_404'
handler500 = 'library.views.error_500'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('library.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
