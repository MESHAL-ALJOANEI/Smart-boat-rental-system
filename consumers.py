# server/chat/consumers.py

import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async # For safe DB access
from django.contrib.auth import get_user_model
from .models import Message, ChatRoom
from .serializers import MessageSerializer # To serialize outgoing messages

User = get_user_model()
logger = logging.getLogger(__name__)

class ChatConsumer(AsyncWebsocketConsumer):
    """
    Asynchronous WebSocket consumer for handling chat messages.
    """

    async def connect(self):
        """Handles new WebSocket connections."""
        self.user = self.scope.get('user') # Get user from AuthMiddlewareStack

        # Check if user is authenticated
        if not self.user or not self.user.is_authenticated:
            await self.close() # Reject unauthenticated connections
            return

        # Get room_id from the URL route
        self.room_id = self.scope['url_route']['kwargs'].get('room_id')
        if not self.room_id:
             await self.close() # Reject if room_id is not in URL
             return

        # Validate if the user is allowed in this room (Database access!)
        is_participant = await self.is_user_participant(self.room_id, self.user)
        if not is_participant:
            await self.close() # Reject if user is not a participant
            return

        # Define a unique group name for this chat room
        self.room_group_name = f'chat_{self.room_id}'

        # Join the room group (using channel layer)
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name # Unique channel name for this connection
        )

        # Accept the WebSocket connection
        await self.accept()
        logger.info(f"WebSocket connected: user {self.user.email}, room {self.room_id}, channel {self.channel_name}")


    async def disconnect(self, close_code):
        """Handles WebSocket disconnections."""
        logger.info(f"WebSocket disconnected: user {getattr(self, 'user', 'NA')}, room {getattr(self, 'room_id', 'NA')}")
        # Leave the room group if connection was successful
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    async def receive(self, text_data=None, bytes_data=None):
        """Handles messages received from the WebSocket client."""
        if not text_data:
            return # Ignore empty messages

        try:
            text_data_json = json.loads(text_data)
            
            # Handle different message types
            message_type = text_data_json.get('type', 'message')
            
            # Handle 'mark_read' message type
            if message_type == 'mark_read':
                await self.mark_messages_read()
                return
                
            # Regular message handling
            message_content = text_data_json.get('message')
        except json.JSONDecodeError:
            logger.warning("Received invalid JSON")
            # Optionally send an error back to the client
            await self.send(text_data=json.dumps({'error': 'Invalid JSON format.'}))
            return

        if not message_content:
             logger.warning("Received empty message content")
             await self.send(text_data=json.dumps({'error': 'Message content cannot be empty.'}))
             return

        # Save the message to the database (asynchronously)
        message_instance = await self.save_message(
            room_id=self.room_id,
            sender=self.user,
            content=message_content
        )

        if not message_instance:
             logger.error("Failed to save message")
             await self.send(text_data=json.dumps({'error': 'Failed to save message.'}))
             return

        # Prepare message data for broadcasting (use serializer for structure)
        # Note: Running serializer directly here might involve sync DB access if not careful
        # A simple dictionary is often fine for broadcasting basic info
        message_data = {
             'id': message_instance.id,
             'sender': { # Simple sender representation for broadcast
                 'id': self.user.id,
                 'email': self.user.email,
                 'first_name': self.user.first_name,
                 'last_name': self.user.last_name,
             },
             'content': message_instance.content,
             'timestamp': message_instance.timestamp.isoformat(), # Use ISO format string
             'room': message_instance.room_id # Include room ID
        }

        # Broadcast the message to the room group
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message', # Corresponds to the method name below
                'message': message_data # The data to send
            }
        )

    async def chat_message(self, event):
        """Handler for messages broadcasted to the group."""
        message = event['message'] # Extract message data from the event

        # Send the message down to the *this specific client's* WebSocket connection
        await self.send(text_data=json.dumps(message))


    # --- Database Helper Methods (using database_sync_to_async) ---

    @database_sync_to_async
    def is_user_participant(self, room_id, user):
        """Checks if a user is a participant in a room (DB Query)."""
        try:
            room = ChatRoom.objects.prefetch_related('participants').get(pk=room_id)
            return user in room.participants.all()
        except ChatRoom.DoesNotExist:
            return False

    @database_sync_to_async
    def save_message(self, room_id, sender, content):
        """Saves a message to the database (DB Query)."""
        try:
            room = ChatRoom.objects.get(pk=room_id)
            message = Message.objects.create(room=room, sender=sender, content=content)
            return message
        except ChatRoom.DoesNotExist:
            logger.error(f"Error: Room {room_id} not found when trying to save message.")
            return None
        except Exception as e:
             logger.error(f"Error saving message: {e}")
             return None
             
    async def mark_messages_read(self):
        """Mark all messages in the current room as read for this user."""
        success = await self.mark_messages_as_read(self.room_id, self.user)
        
        # Send confirmation to the client
        if success:
            await self.send(text_data=json.dumps({
                'type': 'read_status',
                'status': 'success',
                'message': 'Messages marked as read'
            }))
        else:
            await self.send(text_data=json.dumps({
                'type': 'read_status',
                'status': 'error',
                'message': 'Failed to mark messages as read'
            }))
            
    @database_sync_to_async
    def mark_messages_as_read(self, room_id, user):
        """Mark all messages in the room as read (DB Query)."""
        try:
            # Mark messages as read if they weren't sent by this user
            count = Message.objects.filter(
                room_id=room_id,
                is_read=False
            ).exclude(
                sender=user
            ).update(is_read=True)
            
            logger.info(f"Marked {count} messages as read for user {user.email} in room {room_id}")
            return True
        except Exception as e:
            logger.error(f"Error marking messages as read: {e}")
            return False