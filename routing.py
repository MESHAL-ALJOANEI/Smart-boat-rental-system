# server/chat/routing.py - CORRECTED
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Add 'api/' prefix to match the URL being requested by the client
    re_path(r'^api/ws/chat/(?P<room_id>\d+)/$', consumers.ChatConsumer.as_asgi()),
    # The '^' ensures it matches from the beginning of the path after the domain/port
]