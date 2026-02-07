from django.contrib import admin
from .models import Message, ChatRoom

# inline messages
class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')
    search_fields = ('name',)
    inlines = [MessageInline]
admin.site.register(Message)
admin.site.register(ChatRoom, ChatRoomAdmin)
