
from rest_framework import viewsets, permissions, mixins, status
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers

from .models import ChatRoom, Message
from .serializers import ChatRoomSerializer, MessageSerializer
from .permissions import IsChatRoomParticipant

@extend_schema_view(
    list=extend_schema(summary="List chat rooms for the current user"),
    retrieve=extend_schema(summary="Get details of a specific chat room"),
)
class ChatRoomViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for listing and retrieving chat rooms the user participates in.
    Chat room creation is assumed to happen via other logic (e.g., booking confirmation).
    """
    serializer_class = ChatRoomSerializer
    permission_classes = [permissions.IsAuthenticated] # Base permission

    def get_queryset(self):
        """Filter rooms to only include those the requesting user is a participant of."""
        user = self.request.user
        return ChatRoom.objects.filter(participants=user).prefetch_related(
            'participants',
            'messages__sender' # Prefetch related data for efficiency
        ).distinct() # Use distinct if participant relationships cause duplicates


@extend_schema_view(
    list=extend_schema(
        summary="List messages in a specific chat room",
        parameters=[
            OpenApiParameter(
                name='room', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, required=True,
                description='The ID of the chat room to fetch messages for.'
            ),
        ]
    ),
    create=extend_schema(summary="Send a new message to a specific chat room"),
)
class MessageViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet
):
    """
    ViewSet for listing messages within a specific chat room
    and creating new messages in a room. Requires 'room' query parameter for listing.
    """
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated] # Participant check done in queryset/create

    def get_queryset(self):
        """
        Filter messages based on the 'room' query parameter.
        Ensure the user is a participant of the requested room.
        Also marks messages as read when retrieved.
        """
        user = self.request.user
        room_id = self.request.query_params.get('room')

        if not room_id:
            # Return empty queryset if room parameter is missing for list view
            return Message.objects.none()

        try:
            room_id = int(room_id)
        except ValueError:
             # Return empty queryset if room parameter is not a valid integer
             return Message.objects.none()

        # Get the room and verify participation
        try:
            # Check if the user is a participant BEFORE fetching messages
            room = ChatRoom.objects.prefetch_related('participants').get(pk=room_id)
            if user not in room.participants.all():
                 # If user is not a participant, return empty queryset (or raise PermissionDenied)
                 # Raising PermissionDenied might be clearer API behavior
                 # raise permissions.PermissionDenied(IsChatRoomParticipant.message)
                 return Message.objects.none()
        except ChatRoom.DoesNotExist:
             return Message.objects.none() # Room not found

        # Get the queryset of messages for this room
        messages = Message.objects.filter(room_id=room_id).select_related('sender').order_by('timestamp')
        
        # Mark messages as read if they weren't sent by this user and aren't read yet
        # We do this in a separate query to avoid affecting the result set
        Message.objects.filter(
            room_id=room_id, 
            sender__isnull=False,  # Ensure sender exists
            is_read=False  # Only update unread messages
        ).exclude(
            sender=user  # Don't mark the user's own messages
        ).update(is_read=True)  # Mark as read
        
        return messages


    def perform_create(self, serializer):
        """
        Set sender and room for the new message.
        Validate that the sender is a participant of the room.
        """
        user = self.request.user
        room_id = serializer.validated_data.get('room', None) # Get room from validated data if passed
        content = serializer.validated_data.get('content') # Get content

        # If room wasn't directly in validated data (e.g., not a writable field),
        # try getting it from request data or context (depends on frontend implementation)
        if not room_id and 'room' in self.request.data:
             try:
                 room_id = int(self.request.data['room'])
             except (ValueError, TypeError):
                  raise serializers.ValidationError({"room": "Invalid Room ID provided in request data."})
        elif not room_id:
             # Try context if view provides it differently (e.g., from URL in nested setup)
             room_from_context = self.get_serializer_context().get('room')
             if room_from_context:
                 room_id = room_from_context.pk
             else:
                 raise serializers.ValidationError({"room": "Chat room ID must be provided."})

        # Fetch the room and verify participation
        try:
            room = ChatRoom.objects.prefetch_related('participants').get(pk=room_id)
            if user not in room.participants.all():
                raise permissions.PermissionDenied(IsChatRoomParticipant.message)
        except ChatRoom.DoesNotExist:
            raise serializers.ValidationError({"room": f"ChatRoom with ID {room_id} does not exist."})

        # Save the message with sender and validated room
        # Note: serializer's create method might need adjustment if 'room' isn't a standard field
        # Alternative: Create message object directly here
        Message.objects.create(
            room=room,
            sender=user,
            content=content
        )
        # Since we created manually, we don't call serializer.save()
        # If serializer handles creation, ensure context is passed:
        # serializer.save(sender=user, room=room)


    # Override create to prevent returning the message list after POST
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer) # This now creates the message directly
        # Return a simple success or the created message itself, not headers from list view
        # Returning the created message is often useful
        # Fetch the last message created (might be slightly racy without locking)
        # Or adjust perform_create to return the created message instance
        # For simplicity, return success message:
        return Response({"message": "Message sent successfully."}, status=status.HTTP_201_CREATED)

    # Add endpoint to mark messages as read
    @extend_schema(
        summary="Mark all messages in a room as read",
        parameters=[
            OpenApiParameter(
                name='room', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, required=True,
                description='The ID of the chat room to mark messages as read.'
            ),
        ]
    )
    @action(detail=False, methods=['post'])
    def mark_read(self, request):
        """Mark all messages in a room as read."""
        user = request.user
        room_id = request.query_params.get('room')
        
        if not room_id:
            return Response(
                {"error": "Room ID is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        try:
            room_id = int(room_id)
        except ValueError:
            return Response(
                {"error": "Invalid room ID format"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # Check if room exists and user is a participant
        try:
            room = ChatRoom.objects.prefetch_related('participants').get(pk=room_id)
            if user not in room.participants.all():
                return Response(
                    {"error": "You are not a participant in this chat room"},
                    status=status.HTTP_403_FORBIDDEN
                )
        except ChatRoom.DoesNotExist:
            return Response(
                {"error": "Chat room not found"},
                status=status.HTTP_404_NOT_FOUND
            )
            
        # Mark all messages not sent by current user as read
        count = Message.objects.filter(
            room_id=room_id,
            is_read=False
        ).exclude(
            sender=user
        ).update(is_read=True)
        
        return Response(
            {"success": True, "marked_count": count},
            status=status.HTTP_200_OK
        )
    def list(self, request, *args, **kwargs):
        # return all without pagination
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    # Disable other actions if not needed via standard API
    def retrieve(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
    def update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
    def partial_update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
    def destroy(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)