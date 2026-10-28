"""Notification views (API Spec doc 07 45)."""
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification
from .serializers import NotificationSerializer
from .services import sync_platform_updates


class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sync_platform_updates(request.user)
        notifications = Notification.objects.filter(user=request.user)
        unread_only = request.query_params.get("unread")
        if unread_only in ("true", "1"):
            notifications = notifications.filter(read_at__isnull=True)
        return Response(NotificationSerializer(notifications[:50], many=True).data)


class NotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, notification_id):
        from django.shortcuts import get_object_or_404
        notification = get_object_or_404(Notification, id=notification_id, user=request.user)
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at", "updated_at"])
        return Response(NotificationSerializer(notification).data)


class NotificationReadAllView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
        return Response({"message": "All notifications marked as read."})
