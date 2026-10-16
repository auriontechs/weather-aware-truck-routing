from django.urls import path
from . import views

urlpatterns = [
    path('health/', views.health),
    path('test-route/', views.test_route),
    path('plan/', views.plan),
]
