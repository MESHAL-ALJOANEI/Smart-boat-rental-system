# server/chat/permissions.py

from rest_framework import permissions
from .models import ChatRoom

class IsChatRoomParticipant(permissions.BasePermission):
    """
    Permission to check if the user is a participant of the chat room.
    Used for accessing messages within a specific room.
    """
    message = "You do not have permission to access this chat room."

    def has_permission(self, request, view):
        # This check relies on the view providing the room instance or room_pk
        # Typically checked within the view's get_queryset or perform_create
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        # This check applies if the view is operating on a specific ChatRoom instance (obj)
        if isinstance(obj, ChatRoom):
            return request.user in obj.participants.all()
        # If operating on a Message, check the message's room
        if hasattr(obj, 'room'):
             return request.user in obj.room.participants.all()
        return False # Deny if object type is unexpected