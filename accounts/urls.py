from django.urls import path

from . import views

# Names "login"/"logout" are global (LOGIN_URL, templates).
urlpatterns = [
    path("login/", views.login_page, name="login"),
    path("session/", views.SessionLoginView.as_view(), name="session-login"),
    path("logout/", views.logout_view, name="logout"),
]
