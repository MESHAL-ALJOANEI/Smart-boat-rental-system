# server/chat/serializers.py

from rest_framework import serializers
from users.models import User
from .models import ChatRoom, Message
from users.serializers import UserDetailSerializer # For sender/participant details

class MessageSerializer(serializers.ModelSerializer):
    """Serializer for individual chat messages."""
    sender = UserDetailSerializer(read_only=True) # Show sender details

    class Meta:
        model = Message
        fields = ['id', 'room', 'sender', 'content', 'timestamp', 'is_read']
        read_only_fields = ['id', 'sender', 'timestamp'] # Room set implicitly or via URL
        extra_kwargs = {
            'content': {'required': True},
        }

    def create(self, validated_data):
        """Set sender during message creation."""
        # Room should be provided by the view context based on URL or request data
        room = self.context.get('room')
        if not room:
             raise serializers.ValidationError("Chat room context is missing.")
        validated_data['room'] = room
        validated_data['sender'] = self.context['request'].user
        return super().create(validated_data)


class ChatRoomSerializer(serializers.ModelSerializer):
    """Serializer for ChatRoom, potentially including recent messages."""
    # Show full details for participants
    participants = UserDetailSerializer(many=True, read_only=True)
    # Optional: Include last message or unread count
    last_message = MessageSerializer(read_only=True, source='messages.first') # Get latest message
    unread_count = serializers.SerializerMethodField() # Example: Calculate unread count

    # Field for creating a room (e.g., specify participant IDs)
    participant_ids = serializers.ListField(
        child=serializers.PrimaryKeyRelatedField(queryset=User.objects.all()),
        write_only=True,
        required=False # Might create room via booking instead
    )

    class Meta:
        model = ChatRoom
        fields = [
            'id',
            'name',
            'participants', # Read-only nested list
            'participant_ids', # Write-only list of IDs
            'booking', # Optional link to booking
            'created_at',
            'last_message', # Optional
            'unread_count', # Optional
        ]
        read_only_fields = ['id', 'participants', 'created_at', 'last_message', 'unread_count']

    def get_unread_count(self, obj):
        """Calculate unread messages for the requesting user."""
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if user:
            # Count messages in this room, not sent by the current user, and marked as unread
            return obj.messages.filter(is_read=False).exclude(sender=user).count()
        return 0

    def create(self, validated_data):
        """Handle creating a chat room with participants."""
        participant_ids = validated_data.pop('participant_ids', [])
        requesting_user = self.context['request'].user

        # Ensure the requesting user is always a participant
        participants = set(participant_ids)
        participants.add(requesting_user.pk) # Add requesting user's PK

        # Convert PKs back to User instances
        user_participants = User.objects.filter(pk__in=participants)

        # Prevent creating empty rooms or rooms with only one participant
        if user_participants.count() < 2:
             raise serializers.ValidationError("A chat room requires at least two participants.")

        # Check if a room with these exact participants already exists? (Optional)
        # Could be complex with ManyToMany

        # Create the room (booking might be set separately or passed in validated_data)
        room = ChatRoom.objects.create(**validated_data)
        room.participants.set(user_participants) # Set participants
        return room