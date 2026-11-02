from django.urls import path

from . import views, views_admin, views_profile

urlpatterns = [
    path("users/", views.UserListView.as_view(), name="user-list"),
    path("users/export/", views.UserExportView.as_view(), name="user-export"),
    path("users/<uuid:user_id>/", views.UserDetailView.as_view(), name="user-detail"),
    path("students/me/activity/", views_profile.StudentActivityView.as_view(), name="my-activity"),
    path("students/<uuid:student_id>/activity/", views_profile.StudentActivityView.as_view(), name="student-activity"),
    path("admin/roster/upload/", views_admin.RosterUploadView.as_view(), name="roster-upload"),
    path("admin/accounts/", views_admin.AdminAccountListView.as_view(), name="admin-account-list"),
    path("admin/accounts/<uuid:user_id>/", views_admin.AdminAccountAssignView.as_view(), name="admin-account-assign"),
]
