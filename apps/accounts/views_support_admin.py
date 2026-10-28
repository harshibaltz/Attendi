from django.shortcuts import get_object_or_404
from django.db import transaction
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import audit
from apps.core.models import SupportReply, SupportTicket
from apps.core.permissions import IsAdmin
from apps.core.scoping import scope_users
from apps.core.views_support import ticket_data, ticket_queryset
from .models import User


def scoped_tickets(user):
    allowed = scope_users(User.objects.all(), user).values("id")
    return ticket_queryset().filter(user_id__in=allowed)


class SupportMessagesView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        tickets = scoped_tickets(request.user)[:200]
        return Response([ticket_data(ticket) for ticket in tickets])


class SupportTicketAdminView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request, ticket_id):
        return Response(ticket_data(get_object_or_404(scoped_tickets(request.user), id=ticket_id)))

    def patch(self, request, ticket_id):
        ticket = get_object_or_404(scoped_tickets(request.user), id=ticket_id)
        new_status = request.data.get("status")
        message = request.data.get("message")
        if new_status is None and message is None:
            raise ValidationError({"detail": "Send a status or reply message."})
        if new_status is not None and new_status not in SupportTicket.Status.values:
            raise ValidationError({"status": "Invalid status."})
        if message is not None and (not isinstance(message, str) or not 1 <= len(message.strip()) <= 10000):
            raise ValidationError({"message": "Reply must be 1-10000 characters."})
        with transaction.atomic():
            if new_status is not None:
                ticket.status = new_status
                ticket.save(update_fields=["status", "updated_at"])
            if message is not None:
                SupportReply.objects.create(ticket=ticket, author=request.user, message=message.strip())
            audit(user=request.user, action="SUPPORT_UPDATED", resource_type="SupportTicket", resource_id=ticket.id,
                  request=request, metadata={"status": ticket.status})
        return Response(ticket_data(scoped_tickets(request.user).get(id=ticket.id)))
