from django.urls import path

from . import views

urlpatterns = [
    path("class-sessions/<uuid:session_id>/attendance/", views.StartAttendanceView.as_view(), name="start-attendance"),
    path("attendance/sessions/", views.MyAttendanceSessionsView.as_view(), name="my-attendance-sessions"),
    path("attendance/start-flex/", views.FlexibleStartAttendanceView.as_view(), name="start-attendance-flex"),
    path("attendance/offline-sync/", views.OfflineSyncView.as_view(), name="attendance-offline-sync"),
    path("attendance/<uuid:attendance_session_id>/checkpoints/", views.CheckpointsView.as_view(), name="checkpoints"),
    path("attendance/<uuid:attendance_session_id>/checkpoints/auto-select/", views.AutoSelectStationsView.as_view(), name="auto-select-stations"),
    path("attendance/<uuid:attendance_session_id>/checkpoints/<uuid:checkpoint_id>/", views.CheckpointDetailView.as_view(), name="checkpoint-delete"),
    path("attendance/<uuid:attendance_session_id>/manual/", views.ManualAttendanceView.as_view(), name="manual-attendance"),
    path("attendance/<uuid:attendance_session_id>/manual/batch/", views.ManualAttendanceBatchView.as_view(), name="manual-attendance-batch"),
    path("attendance/<uuid:attendance_session_id>/tokens/", views.TokensView.as_view(), name="tokens"),
    path("attendance/<uuid:attendance_session_id>/my-station-token/", views.StationTokenView.as_view(), name="my-station-token"),
    path("attendance/<uuid:attendance_session_id>/station-credential/", views.StationCredentialView.as_view(), name="station-credential"),
    path("attendance/<uuid:attendance_session_id>/projector-credential/", views.ProjectorCredentialView.as_view(), name="projector-credential"),
    path("attendance/<uuid:attendance_session_id>/student-of-class/", views.StudentOfClassView.as_view(), name="student-of-class"),
    path("attendance/<uuid:attendance_session_id>/close/", views.CloseAttendanceView.as_view(), name="close-attendance"),
    path("students/me/points/", views.MyPointsView.as_view(), name="my-points"),
    path("students/me/station/", views.MyStationView.as_view(), name="my-station"),
    path("attendance/scan/", views.ScanView.as_view(), name="attendance-scan"),
    path("attendance/<uuid:attendance_session_id>/", views.AttendanceStatusView.as_view(), name="attendance-status"),
    path("attendance/<uuid:attendance_session_id>/records/", views.AttendanceSessionDetailView.as_view(), name="attendance-session-records"),
    path("class-sessions/<uuid:session_id>/attendance/records/", views.SessionRecordsView.as_view(), name="session-records"),
    path("students/me/attendance/", views.MyAttendanceView.as_view(), name="my-attendance"),
    path("attendance/records/<uuid:record_id>/", views.CorrectRecordView.as_view(), name="correct-record"),
]
