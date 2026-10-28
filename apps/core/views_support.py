from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import audit
from .models import SupportTicket


def ticket_data(ticket):
    return {
        "id": str(ticket.id),
        "subject": ticket.subject,
        "message": ticket.message,
        "status": ticket.status,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
        "actor_email": ticket.user.email if ticket.user else None,
        "actor_name": ticket.user.get_full_name() if ticket.user else None,
        "replies": [
            {"id": str(reply.id), "message": reply.message, "created_at": reply.created_at,
             "author_name": reply.author.get_full_name()}
            for reply in ticket.replies.all()
        ],
    }


def ticket_queryset():
    return SupportTicket.objects.select_related("user").prefetch_related("replies__author")


class SupportContactView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tickets = ticket_queryset().filter(user=request.user)[:200]
        return Response([ticket_data(ticket) for ticket in tickets])

    def post(self, request):
        subject = request.data.get("subject", "general")
        message = request.data.get("message", "")
        if not isinstance(subject, str) or not isinstance(message, str):
            raise ValidationError({"subject": "Subject and message must be text."})
        subject, message = subject.strip(), message.strip()
        if not subject or len(subject) > 200:
            raise ValidationError({"subject": "Subject must be 1-200 characters."})
        if not 10 <= len(message) <= 10000:
            raise ValidationError({"message": "Message must be 10-10000 characters."})
        ticket = SupportTicket.objects.create(user=request.user, subject=subject, message=message)
        audit(user=request.user, action="SUPPORT_CONTACT", resource_type="SupportTicket", resource_id=ticket.id, request=request)
        return Response(ticket_data(ticket), status=status.HTTP_201_CREATED)


class SupportTicketDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, ticket_id):
        ticket = get_object_or_404(ticket_queryset().filter(user=request.user), id=ticket_id)
        return Response(ticket_data(ticket))
