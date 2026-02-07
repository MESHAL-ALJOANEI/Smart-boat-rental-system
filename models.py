# server/chat/models.py

from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _

class ChatRoom(models.Model):
    """
    Represents a chat session between two users (e.g., Renter and Owner).
    """
    # Use a descriptive name, maybe based on participants or booking
    name = models.CharField(_('room name'), max_length=255, blank=True)
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='chat_rooms'
    )
    # Optional: Link chat room to a specific booking
    booking = models.ForeignKey(
        'bookings.Booking',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='chat_room'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['booking']),  # Add index for filtering by booking
        ]

    def __str__(self):
        # Generate a more meaningful name if needed
        participant_list = ", ".join([p.email for p in self.participants.all()])
        if self.booking:
            return f"Chat for Booking {self.booking.booking_id}"
        elif participant_list:
             return f"Chat between {participant_list}"
        elif self.name:
            return self.name
        return f"ChatRoom {self.id}"

class Message(models.Model):
    """
    Represents a single message within a ChatRoom.
    """
    room = models.ForeignKey(
        ChatRoom,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, # Keep message even if sender deleted
        null=True,
        related_name='sent_messages'
    )
    content = models.TextField(_('content'))
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)  # Add index for better query performance
    is_read = models.BooleanField(_('is read'), default=False, db_index=True)  # Add index for filtering unread messages

    class Meta:
        ordering = ['timestamp'] # Show oldest messages first

    def __str__(self):
        sender_email = self.sender.email if self.sender else 'Deleted User'
        return f"Message from {sender_email} in Room {self.room.id} at {self.timestamp}"