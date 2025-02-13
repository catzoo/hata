__all__ = ()

from datetime import datetime

from ...env import CACHE_USER, CACHE_PRESENCE, ALLOW_DEAD_EVENTS

from ...backend.futures import Task
from ...backend.export import include

from ..core import CLIENTS, CHANNELS, GUILDS, MESSAGES, KOKORO, APPLICATION_COMMANDS, APPLICATION_ID_TO_CLIENT, \
    STAGES, USERS
from ..user import User, create_partial_user_from_id, thread_user_create, thread_user_update, thread_user_pop, \
    thread_user_delete
from ..channel import CHANNEL_TYPE_MAP, ChannelGuildBase, ChannelPrivate, ChannelGuildUndefined, ChannelThread
from ..utils import Relationship, Gift
from ..guild import EMOJI_UPDATE_CREATE, EMOJI_UPDATE_DELETE, EMOJI_UPDATE_EDIT, VOICE_STATE_NONE, VOICE_STATE_JOIN, \
    VOICE_STATE_LEAVE, VOICE_STATE_UPDATE, Guild, STICKER_UPDATE_EDIT, STICKER_UPDATE_CREATE, STICKER_UPDATE_DELETE, \
    VOICE_STATE_MOVE
from ..role import Role
from ..invite import Invite
from ..message import EMBED_UPDATE_NONE, Message, MessageRepr
from ..interaction import ApplicationCommand, ApplicationCommandPermission, InteractionEvent
from ..integration import Integration
from ..stage import Stage
from ..emoji import ReactionDeleteEvent, ReactionAddEvent, create_partial_emoji_from_data

from .core import maybe_ensure_launch, add_parser, DEFAULT_EVENT_HANDLER
from .filters import filter_clients, filter_clients_or_me, first_client, first_client_or_me, filter_just_me
from .intent import INTENT_MASK_GUILDS, INTENT_MASK_GUILD_USERS, INTENT_MASK_GUILD_EMOJIS_AND_STICKERS, \
    INTENT_MASK_GUILD_VOICE_STATES, INTENT_MASK_GUILD_PRESENCES, INTENT_MASK_GUILD_MESSAGES, \
    INTENT_MASK_GUILD_REACTIONS, INTENT_MASK_DIRECT_MESSAGES, INTENT_MASK_DIRECT_REACTIONS, INTENT_SHIFT_GUILD_USERS
from .event_types import GuildUserChunkEvent, VoiceServerUpdateEvent
from .guild_sync import guild_sync, check_channel

Client = include('Client')


# we don't call ready from this function directly
def READY(client, data):
    try:
        shard_info = data['shard']
    except KeyError:
        shard_id = 0
    else:
        shard_id = shard_info[0]
    
    ready_state = client.ready_state
    guild_datas = data['guilds']
    
    client._delay_ready(guild_datas, shard_id)
    client._init_on_ready(data['user'])
    
    # if the client is bot, we get only partial guilds,
    # and those disappear so there is not reason to create them
    if not client.is_bot:
        for guild_data in guild_datas:
            guild = Guild(guild_data, client)
            ready_state.feed_guild(client, guild)
    
    try:
        relationship_datas = data['relationships']
    except KeyError:
        pass
    else:
        for relationship_data in relationship_datas:
            Relationship(client, relationship_data, int(relationship_data['id']))
    
    try:
        channel_private_datas = data['private_channels']
    except KeyError:
        pass
    else:
        for channel_private_data in channel_private_datas:
            CHANNEL_TYPE_MAP.get(channel_private_data['type'], ChannelGuildUndefined)(channel_private_data, client, 0)
    
    old_application_id = client.application.id
    client.application._create_update(data['application'], True)
    new_application_id = client.application.id
    
    if old_application_id != new_application_id:
        if APPLICATION_ID_TO_CLIENT.get(old_application_id, None) is client:
            del APPLICATION_ID_TO_CLIENT[old_application_id]
        
        APPLICATION_ID_TO_CLIENT[new_application_id] = client
    
    # ignore `'user_settings'`
    
    maybe_ensure_launch(client)
    
    # 'client.events.ready' gonna be called by _delay_ready at the end
    
    return ...

add_parser(
    'READY',
    READY,
    READY,
    READY,
    READY)
del READY

def RESUMED(client, data):
    return ...

add_parser(
    'RESUMED',
    RESUMED,
    RESUMED,
    RESUMED,
    RESUMED)
del RESUMED

def USER_UPDATE__CAL(client, data):
    old_attributes = client._difference_update_attributes(data)
    if not old_attributes:
        return
    
    Task(client.events.client_edit(client, old_attributes), KOKORO)

def USER_UPDATE__OPT(client, data):
    client._update_attributes(data)

add_parser(
    'USER_UPDATE',
    USER_UPDATE__CAL,
    USER_UPDATE__CAL,
    USER_UPDATE__OPT,
    USER_UPDATE__OPT)
del USER_UPDATE__CAL, \
    USER_UPDATE__OPT

def MESSAGE_CREATE__CAL(client, data):
    channel_id = int(data['channel_id'])
    try:
        channel = CHANNELS[channel_id]
    except KeyError:
        if data.get('guild_id', None) is not None:
            return
        
        channel = ChannelPrivate._create_dataless(channel_id)
        message = channel._create_new_message(data)
        channel._finish_dataless(client, message.author)
    else:
        message = channel._create_new_message(data)
    
    Task(client.events.message_create(client, message), KOKORO)

def MESSAGE_CREATE__OPT(client, data):
    channel_id = int(data['channel_id'])
    try:
        channel = CHANNELS[channel_id]
    except KeyError:
        if data.get('guild_id', None) is not None:
            return
        
        channel = ChannelPrivate._create_dataless(channel_id)
        message = channel._create_new_message(data)
        channel._finish_dataless(client, message.author)
    else:
        channel._create_new_message(data)

add_parser(
    'MESSAGE_CREATE',
    MESSAGE_CREATE__CAL,
    MESSAGE_CREATE__CAL,
    MESSAGE_CREATE__OPT,
    MESSAGE_CREATE__OPT)
del MESSAGE_CREATE__CAL, \
    MESSAGE_CREATE__OPT

if ALLOW_DEAD_EVENTS:
    def MESSAGE_DELETE__CAL_SC(client, data):
        channel_id = int(data['channel_id'])
        message_id = int(data['id'])
        
        try:
            channel = CHANNELS[channel_id]
        except KeyError:
            message = None
        else:
            message = channel._pop_message(message_id)
        
        if message is None:
            guild_id = data.get('guild_id', None)
            if guild_id is None:
                guild_id = 0
            else:
                guild_id = int(guild_id)
            
            message = MessageRepr(message_id, channel_id, guild_id)
        
        Task(client.events.message_delete(client, message), KOKORO)
    
    
    def MESSAGE_DELETE__CAL_MC(client, data):
        channel_id = int(data['channel_id'])
        message_id = int(data['id'])
        
        channel = CHANNELS.get('channel_id', None)
        
        if channel is None:
            clients = None
            message = None
        else:
            clients = filter_clients(
                channel.clients,
                INTENT_MASK_GUILD_MESSAGES if isinstance(channel, ChannelGuildBase) else INTENT_MASK_DIRECT_MESSAGES
            )
            
            if clients.send(None) is not client:
                clients.close()
                return
            
            message = channel._pop_message(message_id)
        
        if message is None:
            guild_id = data.get('guild_id', None)
            if guild_id is None:
                guild_id = 0
            else:
                guild_id = int(guild_id)
            
            message = MessageRepr(message_id, channel_id, guild_id)
        
        if clients is None:
            event_handler = client.events.message_delete
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client, message), KOKORO)
        else:
            for client_ in clients:
                event_handler = client_.events.message_delete
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client_, message), KOKORO)

else:
    def MESSAGE_DELETE__CAL_SC(client, data):
        channel_id = int(data['channel_id'])
        try:
            channel = CHANNELS[channel_id]
        except KeyError:
            # Can happen that 1 client gets message or guild delete payload earlier, than the other message delete one,
            # so do not sync guild at this case.
            return
        
        message_id = int(data['id'])
        message = channel._pop_message(message_id)
        if message is None:
            return
        
        Task(client.events.message_delete(client, message), KOKORO)
    
    def MESSAGE_DELETE__CAL_MC(client, data):
        channel_id = int(data['channel_id'])
        try:
            channel = CHANNELS[channel_id]
        except KeyError:
            # Can happen that 1 client gets message or guild delete payload earlier, than the other message delete one,
            # so do not sync guild at this case.
            return
        
        clients = filter_clients(
            channel.clients,
            INTENT_MASK_GUILD_MESSAGES if isinstance(channel, ChannelGuildBase) else INTENT_MASK_DIRECT_MESSAGES
        )
        
        if clients.send(None) is not client:
            clients.close()
            return
        
        message_id = int(data['id'])
        message = channel._pop_message(message_id)
        if message is None:
            clients.close()
            return
        
        for client_ in clients:
            event_handler = client_.events.message_delete
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client_, message), KOKORO)


def MESSAGE_DELETE__OPT_SC(client, data):
    channel_id = int(data['channel_id'])
    try:
        channel = CHANNELS[channel_id]
    except KeyError:
        # Can happen that 1 client gets message or guild delete payload earlier, than the other message delete one,
        # so do not sync guild at this case.
        return
    
    message_id = int(data['id'])
    channel._pop_message(message_id)

def MESSAGE_DELETE__OPT_MC(client, data):
    channel_id = int(data['channel_id'])
    try:
        channel = CHANNELS[channel_id]
    except KeyError:
        # Can happen that 1 client gets message or guild delete payload earlier, than the other message delete one,
        # so do not sync guild at this case.
        return
    
    if first_client(
            channel.clients,
            INTENT_MASK_GUILD_MESSAGES if isinstance(channel, ChannelGuildBase) else INTENT_MASK_DIRECT_MESSAGES
                ) is not client:
        return
    
    message_id = int(data['id'])
    channel._pop_message(message_id)

add_parser(
    'MESSAGE_DELETE',
    MESSAGE_DELETE__CAL_SC,
    MESSAGE_DELETE__CAL_MC,
    MESSAGE_DELETE__OPT_SC,
    MESSAGE_DELETE__OPT_MC)
del MESSAGE_DELETE__CAL_SC, \
    MESSAGE_DELETE__CAL_MC, \
    MESSAGE_DELETE__OPT_SC, \
    MESSAGE_DELETE__OPT_MC

if ALLOW_DEAD_EVENTS:
    def MESSAGE_DELETE_BULK__CAL_SC(client, data):
        channel_id = int(data['channel_id'])
        
        try:
            channel = CHANNELS[channel_id]
        except KeyError:
            missed = [int(message_id) for message_id in data['ids']]
            messages = []
        else:
            messages, missed = channel._pop_multiple([int(message_id) for message_id in data['ids']])
        
        if missed:
            guild_id = data.get('guild_id', None)
            if guild_id is None:
                guild_id = 0
            else:
                guild_id = int(guild_id)
            
            for message_id in missed:
                message = MessageRepr(message_id, channel_id, guild_id)
                messages.append(message)
        
        event_handler = client.events.message_delete
        for message in messages:
            Task(event_handler(client, message), KOKORO)
    
    
    def MESSAGE_DELETE_BULK__CAL_MC(client, data):
        channel_id = int(data['channel_id'])
        
        try:
            channel = CHANNELS[channel_id]
        except KeyError:
            clients = None
            
            messages = []
            missed = [int(message_id) for message_id in data['ids']]
        
        else:
            clients = filter_clients(channel.clients, INTENT_MASK_GUILD_MESSAGES)
            if clients.send(None) is not client:
                clients.close()
                return
            
            messages, missed = channel._pop_multiple([int(message_id) for message_id in data['ids']])
        
        
        if missed:
            guild_id = data.get('guild_id', None)
            if (guild_id is None):
                guild_id = 0
            else:
                guild_id = int(guild_id)
            
            for message_id in missed:
                message = MessageRepr(message_id, channel_id, guild_id)
                messages.append(message)
        
        
        if clients is None:
            event_handler = client.events.message_delete
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                for message in messages:
                    Task(event_handler(client, message), KOKORO)
        
        else:
            for client_ in clients:
                event_handler = client_.events.message_delete
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    for message in messages:
                        Task(event_handler(client_, message), KOKORO)

else:
    def MESSAGE_DELETE_BULK__CAL_SC(client, data):
        channel_id = int(data['channel_id'])
        try:
            channel = CHANNELS[channel_id]
        except KeyError:
            # Can happen that 1 client gets message or guild delete payload earlier, than the other message delete one,
            # so do not sync guild at this case.
            return
        
        message_ids = [int(message_id) for message_id in data['ids']]
        messages, missed = channel._pop_multiple(message_ids)
        
        event_handler = client.events.message_delete
        for message in messages:
            Task(event_handler(client, message), KOKORO)
    
    def MESSAGE_DELETE_BULK__CAL_MC(client, data):
        channel_id = int(data['channel_id'])
        try:
            channel = CHANNELS[channel_id]
        except KeyError:
            # Can happen that 1 client gets message or guild delete payload earlier, than the other message delete one,
            # so do not sync guild at this case.
            return
        
        clients = filter_clients(channel.clients, INTENT_MASK_GUILD_MESSAGES)
        if clients.send(None) is not client:
            clients.close()
            return
        
        message_ids = [int(message_id) for message_id in data['ids']]
        messages, missed = channel._pop_multiple(message_ids)
        
        for client_ in clients:
            event_handler = client_.events.message_delete
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                for message in messages:
                    Task(event_handler(client_, message), KOKORO)

def MESSAGE_DELETE_BULK__OPT_SC(client, data):
    channel_id = int(data['channel_id'])
    try:
        channel = CHANNELS[channel_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    message_ids = [int(message_id) for message_id in data['ids']]
    channel._pop_multiple(message_ids)

def MESSAGE_DELETE_BULK__OPT_MC(client, data):
    channel_id = int(data['channel_id'])
    try:
        channel = CHANNELS[channel_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    if first_client(channel.clients, INTENT_MASK_GUILD_MESSAGES) is not client:
        return
    
    message_ids = [int(message_id) for message_id in data['ids']]
    channel._pop_multiple(message_ids)

add_parser(
    'MESSAGE_DELETE_BULK',
    MESSAGE_DELETE_BULK__CAL_SC,
    MESSAGE_DELETE_BULK__CAL_MC,
    MESSAGE_DELETE_BULK__OPT_SC,
    MESSAGE_DELETE_BULK__OPT_MC)
del MESSAGE_DELETE_BULK__CAL_SC, \
    MESSAGE_DELETE_BULK__CAL_MC, \
    MESSAGE_DELETE_BULK__OPT_SC, \
    MESSAGE_DELETE_BULK__OPT_MC


if ALLOW_DEAD_EVENTS:
    def MESSAGE_UPDATE__CAL_SC(client, data):
        message_id = int(data['id'])
        message = MESSAGES.get(message_id, None)
        if message is None:
            if 'edited_timestamp' not in data:
                return
            
            # Dead event handling
            message = Message(data)
            Task(client.events.message_edit(client, message, None), KOKORO)
            return
        
        
        if 'edited_timestamp' in data:
            old_attributes = message._difference_update_attributes(data)
            if not old_attributes:
                return
            
            Task(client.events.message_edit(client, message, old_attributes), KOKORO)
        else:
            change_state = message._update_embed(data)
            if change_state == EMBED_UPDATE_NONE:
                return
            
            Task(client.events.embed_update(client, message, change_state), KOKORO)
    
    def MESSAGE_UPDATE__CAL_MC(client, data):
        message_id = int(data['id'])
        message = MESSAGES.get(message_id, None)
        if message is None:
            if 'edited_timestamp' not in data:
                return
            
            message = Message(data)
            message_cached_before = False
        else:
            message_cached_before = True
        
        channel = message.channel
        if channel is None:
            # If channel is nto there, we do not need to dispatch it for all the clients, because we just can't.
            event_handler = client.events.message_edit
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client, message, None), KOKORO)
        
        clients = filter_clients(channel.clients,
            INTENT_MASK_GUILD_MESSAGES if isinstance(channel, ChannelGuildBase) else INTENT_MASK_DIRECT_MESSAGES)
        
        if clients.send(None) is not client:
            clients.close()
            return
        
        
        if 'edited_timestamp' in data:
            if message_cached_before:
                old_attributes = message._difference_update_attributes(data)
                if not old_attributes:
                    clients.close()
                    return
            else:
                old_attributes = None
            
            for client_ in clients:
                event_handler = client_.events.message_edit
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client_, message, old_attributes), KOKORO)
        else:
            if message_cached_before:
                result = message._update_embed(data)
                if not result:
                    clients.close()
                    return
                
                for client_ in clients:
                    event_handler = client_.events.embed_update
                    if (event_handler is not DEFAULT_EVENT_HANDLER):
                        Task(event_handler(client_, message, result), KOKORO)

else:
    def MESSAGE_UPDATE__CAL_SC(client, data):
        message_id = int(data['id'])
        message = MESSAGES.get(message_id, None)
        if message is None:
            return
        
        if 'edited_timestamp' in data:
            old_attributes = message._difference_update_attributes(data)
            if not old_attributes:
                return
            
            Task(client.events.message_edit(client, message, old_attributes), KOKORO)
        else:
            change_state = message._update_embed(data)
            if change_state == EMBED_UPDATE_NONE:
                return
            
            Task(client.events.embed_update(client, message, change_state), KOKORO)
    
    def MESSAGE_UPDATE__CAL_MC(client, data):
        message_id = int(data['id'])
        message = MESSAGES.get(message_id, None)
        if message is None:
            return
        
        channel = message.channel
        clients = filter_clients(
            channel.clients,
            INTENT_MASK_GUILD_MESSAGES if isinstance(channel, ChannelGuildBase) else INTENT_MASK_DIRECT_MESSAGES
        )
        
        if clients.send(None) is not client:
            clients.close()
            return
        
        if 'edited_timestamp' in data:
            old_attributes = message._difference_update_attributes(data)
            if not old_attributes:
                clients.close()
                return
            
            for client_ in clients:
                event_handler = client_.events.message_edit
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client_, message, old_attributes), KOKORO)
        else:
            result = message._update_embed(data)
            if not result:
                clients.close()
                return
                
            for client_ in clients:
                event_handler = client_.events.embed_update
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client_, message, result), KOKORO)


def MESSAGE_UPDATE__OPT_SC(client, data):
    message_id = int(data['id'])
    message = MESSAGES.get(message_id, None)
    if message is None:
        return
    
    if 'edited_timestamp' in data:
        message._update_attributes(data)
    else:
        message._update_embed_no_return(data)

def MESSAGE_UPDATE__OPT_MC(client, data):
    message_id = int(data['id'])
    message = MESSAGES.get(message_id, None)
    if message is None:
        return
    
    channel = message.channel
    if first_client(
        channel.clients,
        INTENT_MASK_GUILD_MESSAGES if isinstance(channel, ChannelGuildBase) else INTENT_MASK_DIRECT_MESSAGES
    ) is not client:
        return
    
    if 'edited_timestamp' in data:
        message._update_attributes(data)
    else:
        message._update_embed_no_return(data)


add_parser(
    'MESSAGE_UPDATE',
    MESSAGE_UPDATE__CAL_SC,
    MESSAGE_UPDATE__CAL_MC,
    MESSAGE_UPDATE__OPT_SC,
    MESSAGE_UPDATE__OPT_MC)
del MESSAGE_UPDATE__CAL_SC, \
    MESSAGE_UPDATE__CAL_MC, \
    MESSAGE_UPDATE__OPT_SC, \
    MESSAGE_UPDATE__OPT_MC



if ALLOW_DEAD_EVENTS:
    def MESSAGE_REACTION_ADD__CAL_SC(client, data):
        message_id = int(data['message_id'])
        message = MESSAGES.get(message_id, None)
        
        user_id = int(data['user_id'])
        user = create_partial_user_from_id(user_id)
        emoji = create_partial_emoji_from_data(data['emoji'])
        
        if message is None:
            channel_id = int(data['channel_id'])
            
            guild_id = data.get('guild_id', None)
            if (guild_id is None):
                guild_id = 0
            else:
                guild_id = int(guild_id)
            
            message = MessageRepr(message_id, channel_id, guild_id)
        else:
            message._add_reaction(emoji, user)
        
        event = ReactionAddEvent(message, emoji, user)
        Task(client.events.reaction_add(client, event), KOKORO)
    
    
    def MESSAGE_REACTION_ADD__CAL_MC(client, data):
        message_id = int(data['message_id'])
        message = MESSAGES.get(message_id, None)
        if message is None:
            channel_id = int(data['channel_id'])
        else:
            channel_id = message.channel_id
        
        channel = CHANNELS.get(channel_id, None)
        
        if channel is None:
            clients = None
        else:
            clients = filter_clients(channel.clients,
                INTENT_MASK_GUILD_REACTIONS if isinstance(channel, ChannelGuildBase) else INTENT_MASK_DIRECT_REACTIONS)
            if clients.send(None) is not client:
                clients.close()
                return
        
        user_id = int(data['user_id'])
        user = create_partial_user_from_id(user_id)
        emoji = create_partial_emoji_from_data(data['emoji'])
        
        if message is None:
            guild_id = data.get('guild_id', None)
            if (guild_id is None):
                guild_id = 0
            else:
                guild_id = int(guild_id)
            
            message = MessageRepr(message_id, channel_id, guild_id)
        else:
            message._add_reaction(emoji, user)
        
        event = ReactionAddEvent(message, emoji, user)
        if clients is None:
            event_handler = client.events.reaction_add
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client, event), KOKORO)
        else:
            for client_ in clients:
                event_handler = client_.events.reaction_add
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client_, event), KOKORO)
else:
    def MESSAGE_REACTION_ADD__CAL_SC(client, data):
        message_id = int(data['message_id'])
        message = MESSAGES.get(message_id, None)
        if message is None:
            return
        
        user_id = int(data['user_id'])
        user = create_partial_user_from_id(user_id)
        emoji = create_partial_emoji_from_data(data['emoji'])
        message._add_reaction(emoji, user)
        
        event = ReactionAddEvent(message, emoji, user)
        Task(client.events.reaction_add(client, event), KOKORO)
    
    def MESSAGE_REACTION_ADD__CAL_MC(client, data):
        message_id = int(data['message_id'])
        message = MESSAGES.get(message_id, None)
        if message is None:
            return
        
        channel = message.channel
        clients = filter_clients(channel.clients,
            INTENT_MASK_GUILD_REACTIONS if isinstance(channel, ChannelGuildBase) else INTENT_MASK_DIRECT_REACTIONS)
        if clients.send(None) is not client:
            clients.close()
            return
        
        user_id = int(data['user_id'])
        user = create_partial_user_from_id(user_id)
        emoji = create_partial_emoji_from_data(data['emoji'])
        message._add_reaction(emoji, user)
        
        event = ReactionAddEvent(message, emoji, user)
        for client_ in clients:
            event_handler = client_.events.reaction_add
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client_, event), KOKORO)

def MESSAGE_REACTION_ADD__OPT_SC(client, data):
    message_id = int(data['message_id'])
    message = MESSAGES.get(message_id, None)
    if message is None:
        return
    
    user_id = int(data['user_id'])
    user = create_partial_user_from_id(user_id)
    emoji = create_partial_emoji_from_data(data['emoji'])
    message._add_reaction(emoji, user)

def MESSAGE_REACTION_ADD__OPT_MC(client, data):
    message_id = int(data['message_id'])
    message = MESSAGES.get(message_id, None)
    if message is None:
        return
    
    channel = message.channel
    if first_client(
        channel.clients,
        INTENT_MASK_GUILD_REACTIONS if isinstance(channel, ChannelGuildBase) else INTENT_MASK_DIRECT_REACTIONS
    ) is not client:
        return
    
    user_id = int(data['user_id'])
    user = create_partial_user_from_id(user_id)
    emoji = create_partial_emoji_from_data(data['emoji'])
    message._add_reaction(emoji, user)

add_parser(
    'MESSAGE_REACTION_ADD',
    MESSAGE_REACTION_ADD__CAL_SC,
    MESSAGE_REACTION_ADD__CAL_MC,
    MESSAGE_REACTION_ADD__OPT_SC,
    MESSAGE_REACTION_ADD__OPT_MC)
del MESSAGE_REACTION_ADD__CAL_SC, \
    MESSAGE_REACTION_ADD__CAL_MC, \
    MESSAGE_REACTION_ADD__OPT_SC, \
    MESSAGE_REACTION_ADD__OPT_MC

if ALLOW_DEAD_EVENTS:
    def MESSAGE_REACTION_REMOVE_ALL__CAL_SC(client, data):
        message_id = int(data['message_id'])
        message = MESSAGES.get(message_id, None)
        if message is None:
            channel_id = int(data['channel_id'])
            
            guild_id = data.get('guild_id', None)
            if (guild_id is None):
                guild_id = 0
            else:
                guild_id = int(guild_id)
            
            message = MessageRepr(message_id, channel_id, guild_id)
            reactions = None
        
        else:
            old_reactions = message.old_reactions
            if (old_reactions is None) or (not old_reactions):
                return
            
            # Copy the reaction instead of creating a new container to message.
            reactions = old_reactions.copy()
            old_reactions.clear()
        
        Task(client.events.reaction_clear(client, message, reactions), KOKORO)
    
    
    def MESSAGE_REACTION_REMOVE_ALL__CAL_MC(client, data):
        message_id = int(data['message_id'])
        message = MESSAGES.get(message_id, None)
        if message is None:
            channel_id = int(data['channel_id'])
        else:
            channel_id = message.channel_id
        
        channel = CHANNELS.get(channel_id, None)
        
        if channel is None:
            clients = None
        else:
            clients = filter_clients(
                channel.clients,
                INTENT_MASK_GUILD_REACTIONS if isinstance(channel, ChannelGuildBase) else INTENT_MASK_DIRECT_REACTIONS
            )
            if clients.send(None) is not client:
                clients.close()
                return
        
        if message is None:
            guild_id = data.get('guild_id', None)
            if guild_id is None:
                guild_id = 0
            else:
                guild_id = int(guild_id)
            
            message = MessageRepr(message_id, channel_id, guild_id)
            reactions = None
        
        else:
            old_reactions = message.reactions
            if (old_reactions is None) or (not old_reactions):
                clients.close()
                return
            
            reactions = old_reactions.copy()
            old_reactions.clear()
        
        if clients is None:
            event_handler = client.events.reaction_clear
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client, message, reactions), KOKORO)
        else:
            for client_ in clients:
                event_handler = client_.events.reaction_clear
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client_, message, reactions), KOKORO)

else:
    def MESSAGE_REACTION_REMOVE_ALL__CAL_SC(client, data):
        message_id = int(data['message_id'])
        message = MESSAGES.get(message_id, None)
        if message is None:
            return
        
        old_reactions = message.reactions
        if (old_reactions is None) or (not old_reactions):
            return
        
        reactions = old_reactions.copy()
        old_reactions.clear()
        
        Task(client.events.reaction_clear(client, message, reactions), KOKORO)
    
    def MESSAGE_REACTION_REMOVE_ALL__CAL_MC(client, data):
        message_id = int(data['message_id'])
        message = MESSAGES.get(message_id, None)
        if message is None:
            return
        
        channel = message.channel
        clients = filter_clients(channel.clients,
            INTENT_MASK_GUILD_REACTIONS if isinstance(channel, ChannelGuildBase) else INTENT_MASK_DIRECT_REACTIONS)
        if clients.send(None) is not client:
            clients.close()
            return
        
        old_reactions = message.reactions
        if (old_reactions is None) or (not old_reactions):
            clients.close()
            return
        
        reactions = old_reactions.copy()
        old_reactions.clear()
        
        for client_ in clients:
            event_handler = client_.events.reaction_clear
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client_, message, reactions), KOKORO)

def MESSAGE_REACTION_REMOVE_ALL__OPT_SC(client, data):
    message_id = int(data['message_id'])
    message = MESSAGES.get(message_id, None)
    if message is None:
        return
    
    old_reactions = message.reactions
    if (old_reactions is not None):
        old_reactions.clear()


def MESSAGE_REACTION_REMOVE_ALL__OPT_MC(client, data):
    message_id = int(data['message_id'])
    message = MESSAGES.get(message_id, None)
    if message is None:
        return
    
    channel = message.channel
    if first_client(
            channel.clients,
            INTENT_MASK_GUILD_REACTIONS if isinstance(channel, ChannelGuildBase) else INTENT_MASK_DIRECT_REACTIONS
                ) is not client:
        return
    
    old_reactions = message.reactions
    if (old_reactions is not None):
        old_reactions.clear()

add_parser(
    'MESSAGE_REACTION_REMOVE_ALL',
    MESSAGE_REACTION_REMOVE_ALL__CAL_SC,
    MESSAGE_REACTION_REMOVE_ALL__CAL_MC,
    MESSAGE_REACTION_REMOVE_ALL__OPT_SC,
    MESSAGE_REACTION_REMOVE_ALL__OPT_MC)
del MESSAGE_REACTION_REMOVE_ALL__CAL_SC, \
    MESSAGE_REACTION_REMOVE_ALL__CAL_MC, \
    MESSAGE_REACTION_REMOVE_ALL__OPT_SC, \
    MESSAGE_REACTION_REMOVE_ALL__OPT_MC



if ALLOW_DEAD_EVENTS:
    def MESSAGE_REACTION_REMOVE__CAL_SC(client, data):
        message_id = int(data['message_id'])
        message = MESSAGES.get(message_id, None)
        
        user_id = int(data['user_id'])
        user = create_partial_user_from_id(user_id)
        emoji = create_partial_emoji_from_data(data['emoji'])
        
        if message is None:
            channel_id = int(data['channel_id'])
            
            guild_id = data.get('guild_id', None)
            if guild_id is None:
                guild_id = 0
            else:
                guild_id = int(guild_id)
            
            message = MessageRepr(message_id, channel_id, guild_id)
        else:
            message._remove_reaction(emoji, user)
        
        event = ReactionDeleteEvent(message, emoji, user)
        Task(client.events.reaction_delete(client, event), KOKORO)
    
    
    def MESSAGE_REACTION_REMOVE__CAL_MC(client, data):
        message_id = int(data['message_id'])
        message = MESSAGES.get(message_id, None)
        if message is None:
            channel_id = int(data['channel_id'])
        else:
            channel_id = message.channel_id
        
        channel = CHANNELS.get(channel_id, None)
        
        if channel is None:
            clients = None
        else:
            clients = filter_clients(channel.clients,
                INTENT_MASK_GUILD_REACTIONS if isinstance(channel, ChannelGuildBase) else INTENT_MASK_DIRECT_REACTIONS)
            if clients.send(None) is not client:
                clients.close()
                return
        
        user_id = int(data['user_id'])
        user = create_partial_user_from_id(user_id)
        emoji = create_partial_emoji_from_data(data['emoji'])
        
        if message is None:
            guild_id = data.get('guild_id', None)
            if guild_id is None:
                guild_id = 0
            else:
                guild_id = int(guild_id)
            
            message = MessageRepr(message_id, channel_id, guild_id)
        else:
            message._remove_reaction(emoji, user)
        
        event = ReactionDeleteEvent(message, emoji, user)
        
        if clients is None:
            event_handler = client.events.reaction_delete
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client, event), KOKORO)
        else:
            for client_ in clients:
                event_handler = client_.events.reaction_delete
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client_, event), KOKORO)
    
else:
    def MESSAGE_REACTION_REMOVE__CAL_SC(client, data):
        message_id = int(data['message_id'])
        message = MESSAGES.get(message_id, None)
        if message is None:
            return
        
        user_id = int(data['user_id'])
        user = create_partial_user_from_id(user_id)
        emoji = create_partial_emoji_from_data(data['emoji'])
        message._remove_reaction(emoji, user)
        
        event = ReactionDeleteEvent(message, emoji, user)
        Task(client.events.reaction_delete(client, event), KOKORO)
    
    
    def MESSAGE_REACTION_REMOVE__CAL_MC(client, data):
        message_id = int(data['message_id'])
        message = MESSAGES.get(message_id, None)
        if message is None:
            return
        
        channel = message.channel
        clients = filter_clients(channel.clients,
            INTENT_MASK_GUILD_REACTIONS if isinstance(channel, ChannelGuildBase) else INTENT_MASK_DIRECT_REACTIONS)
        if clients.send(None) is not client:
            clients.close()
            return
        
        user_id = int(data['user_id'])
        user = create_partial_user_from_id(user_id)
        emoji = create_partial_emoji_from_data(data['emoji'])
        message._remove_reaction(emoji, user)
        
        event = ReactionDeleteEvent(message, emoji, user)
        for client_ in clients:
            event_handler = client_.events.reaction_delete
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client_, event), KOKORO)

def MESSAGE_REACTION_REMOVE__OPT_SC(client, data):
    message_id = int(data['message_id'])
    message = MESSAGES.get(message_id, None)
    if message is None:
        return
    
    user_id = int(data['user_id'])
    user = create_partial_user_from_id(user_id)
    emoji = create_partial_emoji_from_data(data['emoji'])
    message._remove_reaction(emoji, user)

def MESSAGE_REACTION_REMOVE__OPT_MC(client, data):
    message_id = int(data['message_id'])
    message = MESSAGES.get(message_id, None)
    if message is None:
        return
    
    channel = message.channel
    if first_client(
            channel.clients,
            INTENT_MASK_GUILD_REACTIONS if isinstance(channel, ChannelGuildBase) else INTENT_MASK_DIRECT_REACTIONS
                ) is not client:
        return
    
    user_id = int(data['user_id'])
    user = create_partial_user_from_id(user_id)
    emoji = create_partial_emoji_from_data(data['emoji'])
    message._remove_reaction(emoji, user)

add_parser(
    'MESSAGE_REACTION_REMOVE',
    MESSAGE_REACTION_REMOVE__CAL_SC,
    MESSAGE_REACTION_REMOVE__CAL_MC,
    MESSAGE_REACTION_REMOVE__OPT_SC,
    MESSAGE_REACTION_REMOVE__OPT_MC)
del MESSAGE_REACTION_REMOVE__CAL_SC, \
    MESSAGE_REACTION_REMOVE__CAL_MC, \
    MESSAGE_REACTION_REMOVE__OPT_SC, \
    MESSAGE_REACTION_REMOVE__OPT_MC

if ALLOW_DEAD_EVENTS:
    def MESSAGE_REACTION_REMOVE_EMOJI__CAL_SC(client, data):
        message_id = int(data['message_id'])
        message = MESSAGES.get(message_id, None)
        
        emoji = create_partial_emoji_from_data(data['emoji'])
        
        if message is None:
            channel_id = int(data['channel_id'])
            
            guild_id = data.get('guild_id', None)
            if (guild_id is None):
                guild_id = 0
            else:
                guild_id = int(guild_id)
            
            message = MessageRepr(message_id, channel_id, guild_id)
            users = None
        else:
            users = message._remove_reaction_emoji(emoji)
            if users is None:
                return
        
        Task(client.events.reaction_delete_emoji(client, message, emoji, users), KOKORO)
    
    
    def MESSAGE_REACTION_REMOVE_EMOJI__CAL_MC(client, data):
        message_id = int(data['message_id'])
        message = MESSAGES.get(message_id, None)
        if message is None:
            channel_id = int(data['channel_id'])
        else:
            channel_id = message.channel_id
        
        channel = CHANNELS.get(channel_id, None)
        
        if (channel is None):
            clients = None
        else:
            clients = filter_clients(channel.clients,
                INTENT_MASK_GUILD_REACTIONS if isinstance(channel, ChannelGuildBase) else INTENT_MASK_DIRECT_REACTIONS)
            if clients.send(None) is not client:
                clients.close()
                return
        
        emoji = create_partial_emoji_from_data(data['emoji'])
        
        if message is None:
            guild_id = data.get('guild_id')
            if (guild_id is None):
                guild_id = 0
            else:
                guild_id = int(guild_id)
            
            message = MessageRepr(message_id, channel_id, guild_id)
            users = None
        else:
            users = message._remove_reaction_emoji(emoji)
            if (users is None):
                if (clients is not None):
                    clients.close()
                    return
        
        if clients is None:
            event_handler = client.events.reaction_delete_emoji
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client, message, emoji, users), KOKORO)
        else:
            for client_ in clients:
                event_handler = client_.events.reaction_delete_emoji
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client_, message, emoji, users), KOKORO)

else:
    def MESSAGE_REACTION_REMOVE_EMOJI__CAL_SC(client, data):
        message_id = int(data['message_id'])
        message = MESSAGES.get(message_id, None)
        if message is None:
            return
        
        emoji = create_partial_emoji_from_data(data['emoji'])
        users = message._remove_reaction_emoji(emoji)
        if users is None:
            return
        
        Task(client.events.reaction_delete_emoji(client, message, emoji, users), KOKORO)
    
    
    def MESSAGE_REACTION_REMOVE_EMOJI__CAL_MC(client, data):
        message_id = int(data['message_id'])
        message = MESSAGES.get(message_id, None)
        if message is None:
            return
        
        channel = message.channel
        clients = filter_clients(channel.clients,
            INTENT_MASK_GUILD_REACTIONS if isinstance(channel, ChannelGuildBase) else INTENT_MASK_DIRECT_REACTIONS)
        if clients.send(None) is not client:
            clients.close()
            return
        
        emoji = create_partial_emoji_from_data(data['emoji'])
        users = message._remove_reaction_emoji(emoji)
        if users is None:
            clients.close()
            return
        
        for client_ in clients:
            event_handler = client_.events.reaction_delete_emoji
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client_, message, emoji, users), KOKORO)

def MESSAGE_REACTION_REMOVE_EMOJI__OPT_SC(client, data):
    message_id = int(data['message_id'])
    message = MESSAGES.get(message_id, None)
    if message is None:
        return
    
    emoji = create_partial_emoji_from_data(data['emoji'])
    message._remove_reaction_emoji(emoji)

def MESSAGE_REACTION_REMOVE_EMOJI__OPT_MC(client, data):
    message_id = int(data['message_id'])
    message = MESSAGES.get(message_id, None)
    if message is None:
        return
    
    channel = message.channel
    if first_client(
            channel.clients,
            INTENT_MASK_GUILD_REACTIONS if isinstance(channel, ChannelGuildBase) else INTENT_MASK_DIRECT_REACTIONS
                ) is not client:
        return
    
    emoji = create_partial_emoji_from_data(data['emoji'])
    message._remove_reaction_emoji(emoji)

add_parser(
    'MESSAGE_REACTION_REMOVE_EMOJI',
    MESSAGE_REACTION_REMOVE_EMOJI__CAL_SC,
    MESSAGE_REACTION_REMOVE_EMOJI__CAL_MC,
    MESSAGE_REACTION_REMOVE_EMOJI__OPT_SC,
    MESSAGE_REACTION_REMOVE_EMOJI__OPT_MC)
del MESSAGE_REACTION_REMOVE_EMOJI__CAL_SC, \
    MESSAGE_REACTION_REMOVE_EMOJI__CAL_MC, \
    MESSAGE_REACTION_REMOVE_EMOJI__OPT_SC, \
    MESSAGE_REACTION_REMOVE_EMOJI__OPT_MC


if CACHE_PRESENCE:
    def PRESENCE_UPDATE__CAL_SC(client, data):
        user_data = data['user']
        user_id = int(user_data.pop('id'))
        try:
            user = USERS[user_id]
        except KeyError:
            return # pretty much we don't care
        
        while True:
            if user_data:
                old_attributes = user._difference_update_attributes(user_data)
                if old_attributes:
                    presence = False
                    break
            
            old_attributes = user._difference_update_presence(data)
            if old_attributes:
                presence = True
                break
            
            return
        
        if presence:
            event_handler = client.events.user_presence_update
        else:
            event_handler = client.events.user_edit
        
        Task(event_handler(client, user, old_attributes), KOKORO)
    
    def PRESENCE_UPDATE__CAL_MC(client, data):
        user_data = data['user']
        user_id = int(user_data.pop('id'))
        try:
            user = USERS[user_id]
        except KeyError:
            return #pretty much we don't care
        
        while True:
            if user_data:
                old_attributes = user._difference_update_attributes(user_data)
                if old_attributes:
                    presence = False
                    break
            
            old_attributes = user._difference_update_presence(data)
            if old_attributes:
                presence = True
                break
            
            return
        
        for client_ in CLIENTS.values():
            if client_.intents&INTENT_MASK_GUILD_PRESENCES:
                if presence:
                    event_handler = client_.events.user_presence_update
                else:
                    event_handler = client_.events.user_edit
                
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client_, user, old_attributes), KOKORO)
    
    
    def PRESENCE_UPDATE__OPT(client, data):
        user_data = data['user']
        user_id = int(user_data.pop('id'))
        try:
            user = USERS[user_id]
        except KeyError:
            return # pretty much we don't care
        
        if user_data:
            user._update_attributes(user_data)
        
        user._update_presence(data)

else:
    def PRESENCE_UPDATE__CAL_SC(client, data):
        return
    
    PRESENCE_UPDATE__CAL_MC = PRESENCE_UPDATE__CAL_SC
    PRESENCE_UPDATE__OPT = PRESENCE_UPDATE__CAL_SC

add_parser(
    'PRESENCE_UPDATE',
    PRESENCE_UPDATE__CAL_SC,
    PRESENCE_UPDATE__CAL_MC,
    PRESENCE_UPDATE__OPT,
    PRESENCE_UPDATE__OPT)
del PRESENCE_UPDATE__CAL_SC, \
    PRESENCE_UPDATE__CAL_MC, \
    PRESENCE_UPDATE__OPT

if CACHE_USER:
    def GUILD_MEMBER_UPDATE__CAL_SC(client, data):
        guild_id = int(data['guild_id'])
        try:
            guild = GUILDS[guild_id]
        except KeyError:
            guild_sync(client, data, 'GUILD_MEMBER_UPDATE')
            return
        
        user, old_attributes = User._difference_update_profile(data, guild)
        
        if not old_attributes:
            return
        
        if isinstance(user, Client):
            guild._invalidate_permission_cache()
        
        Task(client.events.guild_user_edit(client, user, guild, old_attributes), KOKORO)
    
    def GUILD_MEMBER_UPDATE__CAL_MC(client, data):
        guild_id = int(data['guild_id'])
        try:
            guild = GUILDS[guild_id]
        except KeyError:
            guild_sync(client, data, 'GUILD_MEMBER_UPDATE')
            return
        
        clients = filter_clients_or_me(guild.clients, INTENT_MASK_GUILD_USERS, client)
        if clients.send(None) is not client:
            clients.close()
            return
        
        user, old_attributes = User._difference_update_profile(data, guild)
        
        if not old_attributes:
            clients.close()
            return
        
        if isinstance(user, Client):
            guild._invalidate_permission_cache()
        
        clients.send(user)
        for client_ in clients:
            event_handler = client_.events.guild_user_edit
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client_, user, guild, old_attributes), KOKORO)
    
    def GUILD_MEMBER_UPDATE__OPT_SC(client, data):
        guild_id = int(data['guild_id'])
        try:
            guild = GUILDS[guild_id]
        except KeyError:
            guild_sync(client, data, 'GUILD_MEMBER_UPDATE')
            return
        
        user = User._update_profile(data, guild)

        if isinstance(user, Client):
            guild._invalidate_permission_cache()
    
    def GUILD_MEMBER_UPDATE__OPT_MC(client, data):
        guild_id = int(data['guild_id'])
        try:
            guild = GUILDS[guild_id]
        except KeyError:
            guild_sync(client, data, 'GUILD_MEMBER_UPDATE')
            return
        
        if first_client_or_me(guild.clients, INTENT_MASK_GUILD_USERS, client) is not client:
            return
        
        user = User._update_profile(data, guild)
        
        if isinstance(user, Client):
            guild._invalidate_permission_cache()

else:
    def GUILD_MEMBER_UPDATE__CAL_SC(client, data):
        user_id = int(data['user']['id'])
        if user_id != client.id:
            return
        
        guild_id = int(data['guild_id'])
        try:
            guild = GUILDS[guild_id]
        except KeyError:
            guild_sync(client, data, 'GUILD_MEMBER_UPDATE')
            return
        
        old_attributes = client._difference_update_profile_only(data, guild)
        
        if not old_attributes:
            return
        
        guild._invalidate_permission_cache()
        
        Task(client.events.guild_user_edit(client, client, guild, old_attributes), KOKORO)
    
    GUILD_MEMBER_UPDATE__CAL_MC = GUILD_MEMBER_UPDATE__CAL_SC
    
    def GUILD_MEMBER_UPDATE__OPT_SC(client, data):
        user_id = int(data['user']['id'])
        if user_id != client.id:
            return
        
        guild_id = int(data['guild_id'])
        try:
            guild = GUILDS[guild_id]
        except KeyError:
            guild_sync(client, data, 'GUILD_MEMBER_UPDATE')
            return
        
        client._update_profile_only(data, guild)
        
        guild._invalidate_permission_cache()
    
    GUILD_MEMBER_UPDATE__OPT_MC = GUILD_MEMBER_UPDATE__OPT_SC

add_parser(
    'GUILD_MEMBER_UPDATE',
    GUILD_MEMBER_UPDATE__CAL_SC,
    GUILD_MEMBER_UPDATE__CAL_MC,
    GUILD_MEMBER_UPDATE__OPT_SC,
    GUILD_MEMBER_UPDATE__OPT_MC)
del GUILD_MEMBER_UPDATE__CAL_SC, \
    GUILD_MEMBER_UPDATE__CAL_MC, \
    GUILD_MEMBER_UPDATE__OPT_SC, \
    GUILD_MEMBER_UPDATE__OPT_MC

def CHANNEL_DELETE__CAL_SC(client, data):
    channel_id = int(data['id'])
    try:
        channel = CHANNELS[channel_id]
    except KeyError:
        return
    
    if isinstance(channel, ChannelGuildBase):
        guild = channel.guild
        if guild is None:
            return
        
        channel._delete()
    else:
        channel._delete(client)
    
    Task(client.events.channel_delete(client, channel), KOKORO)

def CHANNEL_DELETE__CAL_MC(client, data):
    channel_id = int(data['id'])
    try:
        channel = CHANNELS[channel_id]
    except KeyError:
        return
    
    if isinstance(channel, ChannelGuildBase):
        clients = filter_clients(channel.clients, INTENT_MASK_GUILDS)
        if clients.send(None) is not client:
            clients.close()
            return
        
        channel._delete()
        
        for client_ in clients:
            event_handler = client_.events.channel_delete
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client_, channel), KOKORO)
        
    else:
        channel._delete(client)
        
        event_handler = client.events.channel_delete
        if (event_handler is not DEFAULT_EVENT_HANDLER):
            Task(client.events.channel_delete(client, channel), KOKORO)

def CHANNEL_DELETE__OPT(client, data):
    channel_id = int(data['id'])
    try:
        channel = CHANNELS[channel_id]
    except KeyError:
        return
    
    if isinstance(channel, ChannelGuildBase):
        channel._delete()
    else:
        channel._delete(client)

add_parser(
    ('CHANNEL_DELETE', 'THREAD_DELETE'),
    CHANNEL_DELETE__CAL_SC,
    CHANNEL_DELETE__CAL_MC,
    CHANNEL_DELETE__OPT,
    CHANNEL_DELETE__OPT)
del CHANNEL_DELETE__CAL_SC, \
    CHANNEL_DELETE__CAL_MC, \
    CHANNEL_DELETE__OPT

def CHANNEL_UPDATE__CAL_SC(client, data):
    channel_id = int(data['id'])
    try:
        channel = CHANNELS[channel_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    old_attributes = channel._difference_update_attributes(data)
    if not old_attributes:
        return
    
    Task(client.events.channel_edit(client, channel, old_attributes), KOKORO)

def CHANNEL_UPDATE__CAL_MC(client, data):
    channel_id = int(data['id'])
    try:
        channel = CHANNELS[channel_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    clients = filter_clients(channel.clients, INTENT_MASK_GUILDS)
    if clients.send(None) is not client:
        clients.close()
        return
    
    old_attributes = channel._difference_update_attributes(data)
    if not old_attributes:
        clients.close()
        return
    
    for client_ in clients:
        event_handler = client_.events.channel_edit
        if (event_handler is not DEFAULT_EVENT_HANDLER):
            Task(event_handler(client_, channel, old_attributes), KOKORO)

def CHANNEL_UPDATE__OPT_SC(client, data):
    channel_id = int(data['id'])
    try:
        channel = CHANNELS[channel_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    channel._update_attributes(data)

def CHANNEL_UPDATE__OPT_MC(client, data):
    channel_id = int(data['id'])
    try:
        channel = CHANNELS[channel_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    if first_client(channel.clients, INTENT_MASK_GUILDS) is not client:
        return
    
    channel._update_attributes(data)

add_parser(
    ('CHANNEL_UPDATE', 'THREAD_UPDATE'),
    CHANNEL_UPDATE__CAL_SC,
    CHANNEL_UPDATE__CAL_MC,
    CHANNEL_UPDATE__OPT_SC,
    CHANNEL_UPDATE__OPT_MC)
del CHANNEL_UPDATE__CAL_SC, \
    CHANNEL_UPDATE__CAL_MC, \
    CHANNEL_UPDATE__OPT_SC, \
    CHANNEL_UPDATE__OPT_MC

def CHANNEL_CREATE__CAL(client, data):
    channel_type = CHANNEL_TYPE_MAP.get(data['type'], ChannelGuildUndefined)
    
    guild_id = data.get('guild_id', None)
    if guild_id is None:
        channel_type(data, client, 0)
        return
    
    guild_id = int(guild_id)
    channel = channel_type(data, client, guild_id)
    
    Task(client.events.channel_create(client, channel), KOKORO)

def CHANNEL_CREATE__OPT(client, data):
    channel_type = CHANNEL_TYPE_MAP.get(data['type'], ChannelGuildUndefined)
    
    guild_id = data.get('guild_id', None)
    if guild_id is None:
        guild_id = 0
    else:
        guild_id = int(guild_id)
    
    channel_type(data, client, guild_id)


add_parser(
    ('CHANNEL_CREATE', 'THREAD_CREATE'),
    CHANNEL_CREATE__CAL,
    CHANNEL_CREATE__CAL,
    CHANNEL_CREATE__OPT,
    CHANNEL_CREATE__OPT)
del CHANNEL_CREATE__CAL, \
    CHANNEL_CREATE__OPT

def CHANNEL_PINS_UPDATE__CAL(client, data):
    channel_id = int(data['channel_id'])
    try:
        channel = CHANNELS[channel_id]
    except KeyError:
        guild_sync(client, data, ('CHANNEL_PINS_UPDATE', check_channel, channel_id))
        return
    
    #ignoring message search
    Task(client.events.channel_pin_update(client, channel), KOKORO)

def CHANNEL_PINS_UPDATE__OPT(client, data):
    pass

add_parser(
    'CHANNEL_PINS_UPDATE',
    CHANNEL_PINS_UPDATE__CAL,
    CHANNEL_PINS_UPDATE__CAL,
    CHANNEL_PINS_UPDATE__OPT,
    CHANNEL_PINS_UPDATE__OPT)
del CHANNEL_PINS_UPDATE__CAL, \
    CHANNEL_PINS_UPDATE__OPT

def CHANNEL_RECIPIENT_ADD_CAL(client, data):
    channel_id = int(data['channel_id'])
    try:
        channel = CHANNELS[channel_id]
    except KeyError:
        return
    
    user = User(data['user'])
    users = channel.users
    if user not in users:
        users.append(user)
    
    Task(client.events.channel_group_user_add(client, channel, user), KOKORO)

def CHANNEL_RECIPIENT_ADD__OPT(client, data):
    channel_id = int(data['channel_id'])
    try:
        channel = CHANNELS[channel_id]
    except KeyError:
        return
    
    user = User(data['user'])
    users = channel.users
    if user not in users:
        users.append(user)

add_parser(
    'CHANNEL_RECIPIENT_ADD',
    CHANNEL_RECIPIENT_ADD_CAL,
    CHANNEL_RECIPIENT_ADD_CAL,
    CHANNEL_RECIPIENT_ADD__OPT,
    CHANNEL_RECIPIENT_ADD__OPT)
del CHANNEL_RECIPIENT_ADD_CAL, \
    CHANNEL_RECIPIENT_ADD__OPT

def CHANNEL_RECIPIENT_REMOVE__CAL_SC(client, data):
    channel_id = int(data['channel_id'])
    try:
        channel = CHANNELS[channel_id]
    except KeyError:
        return
    
    user = User(data['user'])
    try:
        channel.users.remove(user)
    except ValueError:
        return
    
    if client != user:
        Task(client.events.channel_group_user_delete(client, channel, user), KOKORO)

def CHANNEL_RECIPIENT_REMOVE__CAL_MC(client, data):
    channel_id = int(data['channel_id'])
    try:
        channel = CHANNELS[channel_id]
    except KeyError:
        return
    
    user = User(data['user'])
    try:
        channel.users.remove(user)
    except ValueError:
        return
    
    for client_ in channel.clients:
        if (client_ is client) or (client_ != user):
            event_handler = client_.events.channel_group_user_delete
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client_, channel, user), KOKORO)

def CHANNEL_RECIPIENT_REMOVE__OPT(client, data):
    channel_id = int(data['channel_id'])
    try:
        channel = CHANNELS[channel_id]
    except KeyError:
        return

    user = User(data['user'])
    try:
        channel.users.remove(user)
    except ValueError:
        pass

add_parser(
    'CHANNEL_RECIPIENT_REMOVE',
    CHANNEL_RECIPIENT_REMOVE__CAL_SC,
    CHANNEL_RECIPIENT_REMOVE__CAL_MC,
    CHANNEL_RECIPIENT_REMOVE__OPT,
    CHANNEL_RECIPIENT_REMOVE__OPT)
del CHANNEL_RECIPIENT_REMOVE__CAL_SC, \
    CHANNEL_RECIPIENT_REMOVE__CAL_MC, \
    CHANNEL_RECIPIENT_REMOVE__OPT


def GUILD_EMOJIS_UPDATE__CAL_SC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return

    changes = guild._update_emojis(data['emojis'])
    
    if not changes:
        return
    
    for action, emoji, old_attributes in changes:
        if action == EMOJI_UPDATE_EDIT:
            event_handler = client.events.emoji_edit
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client, emoji, old_attributes), KOKORO)
            continue
            
        if action == EMOJI_UPDATE_CREATE:
            event_handler = client.events.emoji_create
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client, emoji), KOKORO)
            continue
        
        if action == EMOJI_UPDATE_DELETE:
            event_handler = client.events.emoji_delete
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client, emoji), KOKORO)
            continue
        
        # no more case

def GUILD_EMOJIS_UPDATE__CAL_MC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    clients = filter_clients(guild.clients, INTENT_MASK_GUILD_EMOJIS_AND_STICKERS)
    if clients.send(None) is not client:
        clients.close()
        return
    
    changes = guild._update_emojis(data['emojis'])
    
    if not changes:
        clients.close()
        return
    
    for client_ in clients:
        for action, emoji, old_attributes in changes:
            if action == EMOJI_UPDATE_EDIT:
                event_handler = client_.events.emoji_edit
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client_, emoji, old_attributes), KOKORO)
                continue
            
            if action == EMOJI_UPDATE_CREATE:
                event_handler = client_.events.emoji_create
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client_, emoji), KOKORO)
                continue
            
            if action == EMOJI_UPDATE_DELETE:
                event_handler = client_.events.emoji_delete
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client_, emoji), KOKORO)
                continue
            
            continue
            # no more case

def GUILD_EMOJIS_UPDATE__OPT_SC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    guild._sync_emojis(data['emojis'])

def GUILD_EMOJIS_UPDATE__OPT_MC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    if first_client(guild.clients, INTENT_MASK_GUILD_EMOJIS_AND_STICKERS) is not client:
        return
    
    guild._sync_emojis(data['emojis'])

add_parser(
    'GUILD_EMOJIS_UPDATE',
    GUILD_EMOJIS_UPDATE__CAL_SC,
    GUILD_EMOJIS_UPDATE__CAL_MC,
    GUILD_EMOJIS_UPDATE__OPT_SC,
    GUILD_EMOJIS_UPDATE__OPT_MC)
del GUILD_EMOJIS_UPDATE__CAL_SC, \
    GUILD_EMOJIS_UPDATE__CAL_MC, \
    GUILD_EMOJIS_UPDATE__OPT_SC, \
    GUILD_EMOJIS_UPDATE__OPT_MC


def GUILD_STICKERS_UPDATE__CAL_SC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return

    changes = guild._update_stickers(data['stickers'])
    
    if not changes:
        return
    
    for action, sticker, old_attributes in changes:
        if action == STICKER_UPDATE_EDIT:
            event_handler = client.events.sticker_edit
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client, sticker, old_attributes), KOKORO)
            continue
            
        if action == STICKER_UPDATE_CREATE:
            event_handler = client.events.sticker_create
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client, sticker), KOKORO)
            continue
        
        if action == STICKER_UPDATE_DELETE:
            event_handler = client.events.sticker_delete
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client, sticker), KOKORO)
            continue
        
        # no more case

def GUILD_STICKERS_UPDATE__CAL_MC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    clients = filter_clients(guild.clients, INTENT_MASK_GUILD_EMOJIS_AND_STICKERS)
    if clients.send(None) is not client:
        clients.close()
        return
    
    changes = guild._update_stickers(data['stickers'])
    
    if not changes:
        clients.close()
        return
    
    for client_ in clients:
        for action, sticker, old_attributes in changes:
            if action == STICKER_UPDATE_EDIT:
                event_handler = client_.events.sticker_edit
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client_, sticker, old_attributes), KOKORO)
                continue
                
            if action == STICKER_UPDATE_CREATE:
                event_handler = client_.events.sticker_create
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client_, sticker), KOKORO)
                continue
            
            if action == STICKER_UPDATE_DELETE:
                event_handler = client_.events.sticker_delete
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client_, sticker), KOKORO)
                continue
            
            continue
            # no more case

def GUILD_STICKERS_UPDATE__OPT_SC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    guild._sync_stickers(data['stickers'])

def GUILD_STICKERS_UPDATE__OPT_MC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    if first_client(guild.clients, INTENT_MASK_GUILD_EMOJIS_AND_STICKERS) is not client:
        return
    
    guild._sync_stickers(data['stickers'])

add_parser(
    'GUILD_STICKERS_UPDATE',
    GUILD_STICKERS_UPDATE__CAL_SC,
    GUILD_STICKERS_UPDATE__CAL_MC,
    GUILD_STICKERS_UPDATE__OPT_SC,
    GUILD_STICKERS_UPDATE__OPT_MC)
del GUILD_STICKERS_UPDATE__CAL_SC, \
    GUILD_STICKERS_UPDATE__CAL_MC, \
    GUILD_STICKERS_UPDATE__OPT_SC, \
    GUILD_STICKERS_UPDATE__OPT_MC


def GUILD_MEMBER_ADD__CAL_SC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    user = User(data, guild)
    guild.user_count +=1
    
    Task(client.events.guild_user_add(client, guild, user), KOKORO)

def GUILD_MEMBER_ADD__CAL_MC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    clients = filter_clients(guild.clients, INTENT_MASK_GUILD_USERS)
    if clients.send(None) is not client:
        clients.close()
        return
    
    user = User(data, guild)
    guild.user_count +=1
    
    for client_ in clients:
        event_handler = client_.events.guild_user_add
        if (event_handler is not DEFAULT_EVENT_HANDLER):
            Task(event_handler(client_, guild, user), KOKORO)

if CACHE_USER:
    def GUILD_MEMBER_ADD__OPT_SC(client, data):
        guild_id = int(data['guild_id'])
        try:
            guild = GUILDS[guild_id]
        except KeyError:
            guild_sync(client, data, None)
            return
        
        User(data, guild)
        guild.user_count +=1
    
    def GUILD_MEMBER_ADD__OPT_MC(client, data):
        guild_id = int(data['guild_id'])
        try:
            guild = GUILDS[guild_id]
        except KeyError:
            guild_sync(client, data, None)
            return
        
        if first_client(guild.clients, INTENT_MASK_GUILD_USERS) is not client:
            return
        
        User(data, guild)
        guild.user_count +=1
else:
    def GUILD_MEMBER_ADD__OPT_SC(client, data):
        guild_id = int(data['guild_id'])
        try:
            guild = GUILDS[guild_id]
        except KeyError:
            guild_sync(client, data, None)
            return
        
        guild.user_count +=1

    def GUILD_MEMBER_ADD__OPT_MC(client, data):
        guild_id = int(data['guild_id'])
        try:
            guild = GUILDS[guild_id]
        except KeyError:
            guild_sync(client, data, None)
            return
        
        if first_client(guild.clients, INTENT_MASK_GUILD_USERS) is not client:
            return
        
        guild.user_count +=1

add_parser(
    'GUILD_MEMBER_ADD',
    GUILD_MEMBER_ADD__CAL_SC,
    GUILD_MEMBER_ADD__CAL_MC,
    GUILD_MEMBER_ADD__OPT_SC,
    GUILD_MEMBER_ADD__OPT_MC)
del GUILD_MEMBER_ADD__CAL_SC, \
    GUILD_MEMBER_ADD__CAL_MC, \
    GUILD_MEMBER_ADD__OPT_SC, \
    GUILD_MEMBER_ADD__OPT_MC

if CACHE_USER:
    def GUILD_MEMBER_REMOVE__CAL_SC(client, data):
        guild_id = int(data['guild_id'])
        try:
            guild = GUILDS[guild_id]
        except KeyError:
            guild_sync(client, data, 'GUILD_MEMBER_REMOVE')
            return
        
        user = User(data['user'])
        
        try:
            del guild.users[user.id]
        except KeyError:
            guild_profile = None
        else:
            if isinstance(user, Client):
                guild_profile = user.guild_profiles.get(guild_id, None)
            else:
                guild_profile = user.guild_profiles.pop(guild_id, None)
        
        guild.user_count -= 1
        
        Task(client.events.guild_user_delete(client, guild, user, guild_profile), KOKORO)
    
    def GUILD_MEMBER_REMOVE__CAL_MC(client, data):
        guild_id = int(data['guild_id'])
        try:
            guild = GUILDS[guild_id]
        except KeyError:
            guild_sync(client, data, 'GUILD_MEMBER_REMOVE')
            return
        
        clients = filter_clients(guild.clients, INTENT_MASK_GUILD_USERS)
        if clients.send(None) is not client:
            clients.close()
            return
        
        user = User(data['user'])
        
        try:
            del guild.users[user.id]
        except KeyError:
            guild_profile = None
        else:
            if isinstance(user, Client):
                guild_profile = user.guild_profiles.get(guild_id, None)
            else:
                guild_profile = user.guild_profiles.pop(guild_id, None)
        
        guild.user_count -= 1
        
        for client_ in clients:
            event_handler = client_.events.guild_user_delete
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client_, guild, user, guild_profile), KOKORO)
    
    def GUILD_MEMBER_REMOVE__OPT_SC(client, data):
        guild_id = int(data['guild_id'])
        try:
            guild = GUILDS[guild_id]
        except KeyError:
            guild_sync(client, data, 'GUILD_MEMBER_REMOVE')
            return
        
        user = User(data['user'])
        
        try:
            del guild.users[user.id]
        except KeyError:
            pass
        else:
            if not isinstance(user, Client):
                try:
                    del user.guild_profiles[guild]
                except KeyError:
                    pass
        
        guild.user_count -= 1
    
    def GUILD_MEMBER_REMOVE__OPT_MC(client, data):
        guild_id = int(data['guild_id'])
        try:
            guild = GUILDS[guild_id]
        except KeyError:
            guild_sync(client, data, 'GUILD_MEMBER_REMOVE')
            return
        
        if first_client(guild.clients, INTENT_MASK_GUILD_USERS) is not client:
            return
        
        user = User(data['user'])
        
        try:
            del guild.users[user.id]
        except KeyError:
            pass
        else:
            if not isinstance(user, Client):
                try:
                    del user.guild_profiles[guild_id]
                except KeyError:
                    pass
        
        guild.user_count -= 1

else:
    def GUILD_MEMBER_REMOVE__CAL_SC(client, data):
        guild_id = int(data['guild_id'])
        try:
            guild = GUILDS[guild_id]
        except KeyError:
            guild_sync(client, data, 'GUILD_MEMBER_REMOVE')
            return
        
        user = User(data['user'])
        guild.user_count -= 1
        
        Task(client.events.guild_user_delete(client, guild, user, None), KOKORO)

    def GUILD_MEMBER_REMOVE__CAL_MC(client, data):
        guild_id = int(data['guild_id'])
        try:
            guild = GUILDS[guild_id]
        except KeyError:
            guild_sync(client, data, 'GUILD_MEMBER_REMOVE')
            return
        
        clients = filter_clients(guild.clients, INTENT_MASK_GUILD_USERS)
        if clients.send(None) is not client:
            clients.close()
            return
        
        user = User(data['user'])
        guild.user_count -= 1
        
        for client_ in clients:
            event_handler = client_.events.guild_user_delete
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                Task(event_handler(client_, guild, user, None), KOKORO)
    
    def GUILD_MEMBER_REMOVE__OPT_SC(client, data):
        guild_id = int(data['guild_id'])
        try:
            guild = GUILDS[guild_id]
        except KeyError:
            guild_sync(client, data, 'GUILD_MEMBER_REMOVE')
            return
        
        guild.user_count -= 1
    
    def GUILD_MEMBER_REMOVE__OPT_MC(client, data):
        guild_id = int(data['guild_id'])
        try:
            guild = GUILDS[guild_id]
        except KeyError:
            guild_sync(client, data, 'GUILD_MEMBER_REMOVE')
            return
        
        if first_client(guild.clients, INTENT_MASK_GUILD_USERS) is not client:
            return
        
        guild.user_count -= 1

add_parser(
    'GUILD_MEMBER_REMOVE',
    GUILD_MEMBER_REMOVE__CAL_SC,
    GUILD_MEMBER_REMOVE__CAL_MC,
    GUILD_MEMBER_REMOVE__OPT_SC,
    GUILD_MEMBER_REMOVE__OPT_MC)
del GUILD_MEMBER_REMOVE__CAL_SC, \
    GUILD_MEMBER_REMOVE__CAL_MC, \
    GUILD_MEMBER_REMOVE__OPT_SC, \
    GUILD_MEMBER_REMOVE__OPT_MC

# This is a low priority event. Is called after `GUILD_MEMBER_REMOVE`, so we should have everything cached.

def GUILD_JOIN_REQUEST_DELETE__CAL(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        return
    
    user_id = int(data['user_id'])
    try:
        user = USERS[user_id]
    except KeyError:
        return
    
    Task(client.events.guild_join_reject(client, guild, user), KOKORO)

def GUILD_JOIN_REQUEST_DELETE__OPT(client, data):
    pass


add_parser(
    'GUILD_JOIN_REQUEST_DELETE',
    GUILD_JOIN_REQUEST_DELETE__CAL,
    GUILD_JOIN_REQUEST_DELETE__CAL,
    GUILD_JOIN_REQUEST_DELETE__OPT,
    GUILD_JOIN_REQUEST_DELETE__OPT)
del GUILD_JOIN_REQUEST_DELETE__CAL, \
    GUILD_JOIN_REQUEST_DELETE__OPT

if CACHE_PRESENCE:
    def GUILD_CREATE__CAL(client, data):
        guild_state = data.get('unavailable', False)
        if guild_state:
            return
        
        guild = Guild(data, client)
        
        ready_state = client.ready_state
        if (ready_state is None) or (not ready_state.feed_guild(client, guild)):
            if (client.intents&INTENT_SHIFT_GUILD_USERS) and guild.is_large:
                Task(client._request_members(guild.id), KOKORO)
            
            Task(client.events.guild_create(client, guild), KOKORO)


    def GUILD_CREATE__OPT(client, data):
        guild_state = data.get('unavailable', False)
        if guild_state:
            return
        
        guild = Guild(data, client)
        
        ready_state = client.ready_state
        if (ready_state is None) or (not ready_state.feed_guild(client, guild)):
            if (client.intents&INTENT_SHIFT_GUILD_USERS) and guild.is_large:
                Task(client._request_members(guild.id), KOKORO)

elif CACHE_USER:
    def GUILD_CREATE__CAL(client, data):
        guild_state = data.get('unavailable', False)
        if guild_state:
            return
        
        guild = Guild(data, client)
        
        ready_state = client.ready_state
        if (ready_state is None) or (not ready_state.feed_guild(client, guild)):
            if (client.intents&INTENT_SHIFT_GUILD_USERS):
                Task(client._request_members(guild.id), KOKORO)
            
            Task(client.events.guild_create(client, guild), KOKORO)

    def GUILD_CREATE__OPT(client, data):
        guild_state = data.get('unavailable', False)
        if guild_state:
            return
        
        guild = Guild(data, client)
        
        ready_state = client.ready_state
        if (ready_state is None) or (not ready_state.feed_guild(client, guild)) and \
                (client.intents&INTENT_SHIFT_GUILD_USERS):
            Task(client._request_members(guild.id), KOKORO)

else:
    def GUILD_CREATE__CAL(client, data):
        guild_state = data.get('unavailable', False)
        if guild_state:
            return
        
        guild = Guild(data, client)
        
        ready_state = client.ready_state
        if (ready_state is None) or (not ready_state.feed_guild(client, guild)):
            Task(client.events.guild_create(client, guild), KOKORO)
    
    def GUILD_CREATE__OPT(client, data):
        guild_state = data.get('unavailable', False)
        if guild_state:
            return
        
        guild = Guild(data, client)
        
        ready_state = client.ready_state
        if (ready_state is not None):
            ready_state.feed_guild(client, guild)


add_parser(
    'GUILD_CREATE',
    GUILD_CREATE__CAL,
    GUILD_CREATE__CAL,
    GUILD_CREATE__OPT,
    GUILD_CREATE__OPT)
del GUILD_CREATE__CAL, \
    GUILD_CREATE__OPT

def GUILD_UPDATE__CAL_SC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    old_attributes = guild._difference_update_attributes(data)
    if not old_attributes:
        return
    
    Task(client.events.guild_edit(client, guild, old_attributes), KOKORO)

def GUILD_UPDATE__CAL_MC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    clients = filter_clients(guild.clients, INTENT_MASK_GUILDS)
    if clients.send(None) is not client:
        clients.close()
        return
    
    old_attributes = guild._difference_update_attributes(data)
    if not old_attributes:
        clients.close()
        return
    
    for client_ in clients:
        event_handler = client_.events.guild_edit
        if (event_handler is DEFAULT_EVENT_HANDLER):
            Task(event_handler(client_, guild, old_attributes), KOKORO)

def GUILD_UPDATE__OPT_SC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    guild._update_attributes(data)

def GUILD_UPDATE__OPT_MC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    if first_client(guild.clients, INTENT_MASK_GUILDS) is not client:
        return
    
    guild._update_attributes(data)

add_parser(
    'GUILD_UPDATE',
    GUILD_UPDATE__CAL_SC,
    GUILD_UPDATE__CAL_MC,
    GUILD_UPDATE__OPT_SC,
    GUILD_UPDATE__OPT_MC)
del GUILD_UPDATE__CAL_SC, \
    GUILD_UPDATE__CAL_MC, \
    GUILD_UPDATE__OPT_SC, \
    GUILD_UPDATE__OPT_MC

def GUILD_DELETE__CAL(client, data):
    guild_id = int(data['id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        return
    
    if data.get('unavailable', 2) == 1:
        return
    
    guild_profile = client.guild_profiles.pop(guild, None)
    
    guild._delete(client)
    
    ready_state = client.ready_state
    if (ready_state is not None):
        ready_state.discard_guild(guild)
    
    Task(client.events.guild_delete(client, guild, guild_profile), KOKORO)

def GUILD_DELETE__OPT(client, data):
    guild_id = int(data['id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        return
    
    if data.get('unavailable', 2) == 1:
        return
    
    try:
        del client.guild_profiles[guild_id]
    except KeyError:
        pass
    
    guild._delete(client)

    ready_state = client.ready_state
    if (ready_state is not None):
        ready_state.discard_guild(guild)

add_parser(
    'GUILD_DELETE',
    GUILD_DELETE__CAL,
    GUILD_DELETE__CAL,
    GUILD_DELETE__OPT,
    GUILD_DELETE__OPT)
del GUILD_DELETE__CAL, \
    GUILD_DELETE__OPT

def GUILD_BAN_ADD__CAL(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, 'GUILD_BAN_ADD')
        return
    
    user = User(data['user'])
    
    Task(client.events.guild_ban_add(client, guild, user), KOKORO)

def GUILD_BAN_ADD__OPT(client, data):
    pass

add_parser(
    'GUILD_BAN_ADD',
    GUILD_BAN_ADD__CAL,
    GUILD_BAN_ADD__CAL,
    GUILD_BAN_ADD__OPT,
    GUILD_BAN_ADD__OPT)
del GUILD_BAN_ADD__CAL, \
    GUILD_BAN_ADD__OPT

def GUILD_BAN_REMOVE__CAL(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, 'GUILD_BAN_REMOVE')
        return
    
    user = User(data['user'])
    Task(client.events.guild_ban_delete(client, guild, user), KOKORO)

def GUILD_BAN_REMOVE__OPT(client, data):
    pass

add_parser(
    'GUILD_BAN_REMOVE',
    GUILD_BAN_REMOVE__CAL,
    GUILD_BAN_REMOVE__CAL,
    GUILD_BAN_REMOVE__OPT,
    GUILD_BAN_REMOVE__OPT)
del GUILD_BAN_REMOVE__CAL, \
    GUILD_BAN_REMOVE__OPT


if CACHE_PRESENCE:
    def GUILD_MEMBERS_CHUNK(client, data):
        guild_id = int(data['guild_id'])
        try:
            guild = GUILDS[guild_id]
        except KeyError:
            return
        
        users = []
        for user_data in data['members']:
            user = User(user_data, guild)
            users.append(user)
        
        try:
            presence_datas = data['presences']
        except KeyError:
            pass
        else:
            guild._apply_presences(presence_datas)
        
        event = object.__new__(GuildUserChunkEvent)
        event.guild = guild
        event.users = users
        event.nonce = data.get('nonce', None)
        event.index = data['chunk_index']
        event.count = data['chunk_count']
        
        Task(client.events.guild_user_chunk(client, event), KOKORO)
else:
    def GUILD_MEMBERS_CHUNK(client, data):
        guild_id = int(data['guild_id'])
        try:
            guild = GUILDS[guild_id]
        except KeyError:
            return
        
        users = []
        for user_data in data['members']:
            user = User(user_data, guild)
            users.append(user)
        
        event = object.__new__(GuildUserChunkEvent)
        event.guild = guild
        event.users = users
        event.nonce = data.get('nonce', None)
        event.index = data['chunk_index']
        event.count = data['chunk_count']
        
        Task(client.events.guild_user_chunk(client, event), KOKORO)

add_parser(
    'GUILD_MEMBERS_CHUNK',
    GUILD_MEMBERS_CHUNK,
    GUILD_MEMBERS_CHUNK,
    GUILD_MEMBERS_CHUNK,
    GUILD_MEMBERS_CHUNK)
del GUILD_MEMBERS_CHUNK

def INTEGRATION_CREATE__CAL(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, 'INTEGRATION_CREATE')
        return
    
    integration = Integration(data)
    
    Task(client.events.integration_create(client, guild, integration), KOKORO)

def INTEGRATION_CREATE__OPT(client, data):
    pass

add_parser(
    'INTEGRATION_CREATE',
    INTEGRATION_CREATE__CAL,
    INTEGRATION_CREATE__CAL,
    INTEGRATION_CREATE__OPT,
    INTEGRATION_CREATE__OPT)
del INTEGRATION_CREATE__CAL, \
    INTEGRATION_CREATE__OPT

def INTEGRATION_DELETE__CAL(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, 'INTEGRATION_DELETE')
        return
    
    integration_id = int(data['id'])
    try:
        application_id = data['application_id']
    except KeyError:
        application_id = None
    else:
        application_id = int(application_id)
    
    Task(client.events.integration_delete(client, guild, integration_id, application_id), KOKORO)

def INTEGRATION_DELETE__OPT(client, data):
    pass

add_parser(
    'INTEGRATION_DELETE',
    INTEGRATION_DELETE__CAL,
    INTEGRATION_DELETE__CAL,
    INTEGRATION_DELETE__OPT,
    INTEGRATION_DELETE__OPT)
del INTEGRATION_DELETE__CAL, \
    INTEGRATION_DELETE__OPT

def INTEGRATION_UPDATE__CAL(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, 'INTEGRATION_UPDATE')
        return
    
    integration = Integration(data)
    
    Task(client.events.integration_edit(client, guild, integration), KOKORO)

def INTEGRATION_UPDATE__OPT(client, data):
    pass

add_parser(
    'INTEGRATION_UPDATE',
    INTEGRATION_UPDATE__CAL,
    INTEGRATION_UPDATE__CAL,
    INTEGRATION_UPDATE__OPT,
    INTEGRATION_UPDATE__OPT)
del INTEGRATION_UPDATE__CAL, \
    INTEGRATION_UPDATE__OPT


def GUILD_INTEGRATIONS_UPDATE__CAL(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, 'GUILD_INTEGRATIONS_UPDATE')
        return
    
    Task(client.events.integration_update(client, guild), KOKORO)

def GUILD_INTEGRATIONS_UPDATE__OPT(client, data):
    pass

add_parser(
    'GUILD_INTEGRATIONS_UPDATE',
    GUILD_INTEGRATIONS_UPDATE__CAL,
    GUILD_INTEGRATIONS_UPDATE__CAL,
    GUILD_INTEGRATIONS_UPDATE__OPT,
    GUILD_INTEGRATIONS_UPDATE__OPT)
del GUILD_INTEGRATIONS_UPDATE__CAL, \
    GUILD_INTEGRATIONS_UPDATE__OPT


def GUILD_ROLE_CREATE__CAL_SC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, 'GUILD_ROLE_CREATE')
        return
    
    role = Role(data['role'], guild)
    
    Task(client.events.role_create(client, role), KOKORO)

def GUILD_ROLE_CREATE__CAL_MC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, 'GUILD_ROLE_CREATE')
        return
    
    clients = filter_clients(guild.clients, INTENT_MASK_GUILDS)
    if clients.send(None) is not client:
        clients.close()
        return
    
    role = Role(data['role'], guild)
    
    for client_ in clients:
        event_handler = client_.events.role_create
        if (event_handler is not DEFAULT_EVENT_HANDLER):
            Task(event_handler(client_, role), KOKORO)

def GUILD_ROLE_CREATE__OPT_SC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, 'GUILD_ROLE_CREATE')
        return
    
    Role(data['role'], guild)

def GUILD_ROLE_CREATE__OPT_MC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, 'GUILD_ROLE_CREATE')
        return
    
    if first_client(guild.clients, INTENT_MASK_GUILDS) is not client:
        return
    
    Role(data['role'], guild)

add_parser(
    'GUILD_ROLE_CREATE',
    GUILD_ROLE_CREATE__CAL_SC,
    GUILD_ROLE_CREATE__CAL_MC,
    GUILD_ROLE_CREATE__OPT_SC,
    GUILD_ROLE_CREATE__OPT_MC)
del GUILD_ROLE_CREATE__CAL_SC, \
    GUILD_ROLE_CREATE__CAL_MC, \
    GUILD_ROLE_CREATE__OPT_SC, \
    GUILD_ROLE_CREATE__OPT_MC

def GUILD_ROLE_DELETE__CAL_SC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    role_id = int(data['role_id'])
    try:
        role = guild.roles[role_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    role._delete()
    
    Task(client.events.role_delete(client, role, guild), KOKORO)

def GUILD_ROLE_DELETE__CAL_MC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    clients = filter_clients(guild.clients, INTENT_MASK_GUILDS)
    if clients.send(None) is not client:
        clients.close()
        return
    
    role_id = int(data['role_id'])
    try:
        role = guild.roles[role_id]
    except KeyError:
        clients.close()
        guild_sync(client, data, None)
        return
    
    role._delete()
    
    for client_ in clients:
        event_handler = client_.events.role_delete
        if (event_handler is not DEFAULT_EVENT_HANDLER):
            Task(event_handler(client_, role, guild), KOKORO)

def GUILD_ROLE_DELETE__OPT_SC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    role_id = int(data['role_id'])
    try:
        role = guild.roles[role_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    role._delete()

def GUILD_ROLE_DELETE__OPT_MC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    if first_client(guild.clients, INTENT_MASK_GUILDS) is not client:
        return
    
    role_id = int(data['role_id'])
    try:
        role = guild.roles[role_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    role._delete()

add_parser(
    'GUILD_ROLE_DELETE',
    GUILD_ROLE_DELETE__CAL_SC,
    GUILD_ROLE_DELETE__CAL_MC,
    GUILD_ROLE_DELETE__OPT_SC,
    GUILD_ROLE_DELETE__OPT_MC)
del GUILD_ROLE_DELETE__CAL_SC, \
    GUILD_ROLE_DELETE__CAL_MC, \
    GUILD_ROLE_DELETE__OPT_SC, \
    GUILD_ROLE_DELETE__OPT_MC

def GUILD_ROLE_UPDATE__CAL_SC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    role_data = data['role']
    role_id = int(role_data['id'])
    try:
        role = guild.roles[role_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    old_attributes = role._difference_update_attributes(data['role'])
    if not old_attributes:
        return
    
    Task(client.events.role_edit(client, role, old_attributes), KOKORO)

def GUILD_ROLE_UPDATE__CAL_MC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    clients = filter_clients(guild.clients, INTENT_MASK_GUILDS)
    if clients.send(None) is not client:
        clients.close()
        return
    
    role_data = data['role']
    role_id = int(role_data['id'])
    try:
        role = guild.roles[role_id]
    except KeyError:
        clients.close()
        guild_sync(client, data, None)
        return
    
    old_attributes = role._difference_update_attributes(data['role'])
    if not old_attributes:
        clients.close()
        return
    
    for client_ in clients:
        event_handler = client_.events.role_edit
        if (event_handler is not DEFAULT_EVENT_HANDLER):
            Task(event_handler(client_, role, old_attributes), KOKORO)

def GUILD_ROLE_UPDATE__OPT_SC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    role_data = data['role']
    role_id = int(role_data['id'])
    try:
        role = guild.roles[role_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    role._update_attributes(data['role'])

def GUILD_ROLE_UPDATE__OPT_MC(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    if first_client(guild.clients, INTENT_MASK_GUILDS) is not client:
        return
    
    role_data = data['role']
    role_id = int(role_data['id'])
    try:
        role = guild.roles[role_id]
    except KeyError:
        guild_sync(client, data, None)
        return
    
    role._update_attributes(data['role'])

add_parser(
    'GUILD_ROLE_UPDATE',
    GUILD_ROLE_UPDATE__CAL_SC,
    GUILD_ROLE_UPDATE__CAL_MC,
    GUILD_ROLE_UPDATE__OPT_SC,
    GUILD_ROLE_UPDATE__OPT_MC)
del GUILD_ROLE_UPDATE__CAL_SC, \
    GUILD_ROLE_UPDATE__CAL_MC, \
    GUILD_ROLE_UPDATE__OPT_SC, \
    GUILD_ROLE_UPDATE__OPT_MC

def WEBHOOKS_UPDATE__CAL(client, data):
    guild_id = int(data['guild_id'])
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        guild_sync(client, data, 'WEBHOOKS_UPDATE')
        return
    
    channel_id = int(data['channel_id'])
    channel = CHANNELS.get(channel_id, None)
    
    #if this happens the client might ask for update.
    Task(client.events.webhook_update(client, channel,), KOKORO)

def WEBHOOKS_UPDATE__OPT(client, data):
    pass

add_parser(
    'WEBHOOKS_UPDATE',
    WEBHOOKS_UPDATE__CAL,
    WEBHOOKS_UPDATE__CAL,
    WEBHOOKS_UPDATE__OPT,
    WEBHOOKS_UPDATE__OPT)
del WEBHOOKS_UPDATE__CAL, \
    WEBHOOKS_UPDATE__OPT

def VOICE_STATE_UPDATE__CAL_SC(client, data):
    try:
        guild_id = data['guild_id']
    except KeyError:
        # Do not handle outside of guild calls
        return
    else:
        guild_id = int(guild_id)
        try:
            guild = GUILDS[guild_id]
        except KeyError:
            guild_sync(client, data, 'VOICE_STATE_UPDATE')
            return
    
    try:
        user_data = data['member']
    except KeyError:
        user_data = data['user']
    
    user = User(user_data)
    
    if user is client:
        for action, voice_state, change in guild._update_voice_state(data, user):
            if action == VOICE_STATE_JOIN:
                event_handler = client.events.voice_client_join
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client, voice_state), KOKORO)
                continue
            
            if action == VOICE_STATE_MOVE:
                event_handler = client.events.voice_client_move
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                     Task(event_handler(client, voice_state, change), KOKORO)
                continue
            
            if action == VOICE_STATE_LEAVE:
                event_handler = client.events.voice_client_leave
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                     Task(event_handler(client, voice_state, change), KOKORO)
                continue
            
            if action == VOICE_STATE_UPDATE:
                event_handler = client.events.voice_client_update
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                     Task(event_handler(client, voice_state, change), KOKORO)
            continue
    
    else:
        for action, voice_state, change in guild._update_voice_state(data, user):
            if action == VOICE_STATE_JOIN:
                event_handler = client.events.user_voice_join
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client, voice_state), KOKORO)
                continue
            
            if action == VOICE_STATE_MOVE:
                event_handler = client.events.user_voice_move
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client, voice_state, change), KOKORO)
                continue
            
            if action == VOICE_STATE_LEAVE:
                event_handler = client.events.user_voice_leave
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client, voice_state, change), KOKORO)
                continue
            
            if action == VOICE_STATE_UPDATE:
                event_handler = client.events.user_voice_update
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client, voice_state, VOICE_STATE_JOIN), KOKORO)
                continue


def VOICE_STATE_UPDATE__CAL_MC(client, data):
    try:
        guild_id = data['guild_id']
    except KeyError:
        # Do not handle outside of guild calls
        return
    
    guild_id = int(guild_id)
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        # Ignore this case
        return
    
    clients = filter_clients(guild.clients, INTENT_MASK_GUILD_VOICE_STATES)
    if clients.send(None) is not client:
        clients.close()
        return
    
    try:
        user_data = data['member']
    except KeyError:
        user_data = data['user']
    
    user = User(user_data)
    
    actions = list(guild._update_voice_state(data, user))
    if not actions:
        clients.close()
        return
    
    if isinstance(user, Client):
        for action, voice_state, change in actions:
            if action == VOICE_STATE_JOIN:
                event_handler = user.events.voice_client_join
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(user, voice_state), KOKORO)
                continue
            
            if action == VOICE_STATE_MOVE:
                event_handler = user.events.voice_client_move
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                     Task(event_handler(user, voice_state, change), KOKORO)
                continue
            
            if action == VOICE_STATE_LEAVE:
                event_handler = user.events.voice_client_leave
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                     Task(event_handler(user, voice_state, change), KOKORO)
                continue
            
            if action == VOICE_STATE_UPDATE:
                event_handler = user.events.voice_client_update
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                     Task(event_handler(user, voice_state, change), KOKORO)
                continue
    
    for client_ in clients:
        for action, voice_state, change in actions:
            if action == VOICE_STATE_JOIN:
                event_handler = client_.events.user_voice_join
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client_, voice_state), KOKORO)
                continue
            
            if action == VOICE_STATE_MOVE:
                event_handler = client_.events.user_voice_move
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client_, voice_state, change), KOKORO)
                continue
            
            if action == VOICE_STATE_LEAVE:
                event_handler = client_.events.user_voice_leave
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client_, voice_state, change), KOKORO)
                continue
            
            if action == VOICE_STATE_UPDATE:
                event_handler = client_.events.user_voice_update
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client_, voice_state, change), KOKORO)
                continue


def VOICE_STATE_UPDATE__OPT_SC(client, data):
    try:
        guild_id = data['guild_id']
    except KeyError:
        # Do not handle outside of guild calls
        return
    
    guild_id = int(guild_id)
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        return
    
    try:
        user_data = data['member']
    except KeyError:
        user_data = data['user']
    
    user = User(user_data, guild)
    
    if user is client:
        for action, voice_state, change in guild._update_voice_state(data, user):
            if action == VOICE_STATE_JOIN:
                event_handler = client.events.voice_client_join
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client, voice_state), KOKORO)
                continue
            
            if action == VOICE_STATE_MOVE:
                event_handler = client.events.voice_client_move
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                     Task(event_handler(client, voice_state, change), KOKORO)
                continue
            
            if action == VOICE_STATE_LEAVE:
                event_handler = client.events.voice_client_leave
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                     Task(event_handler(client, voice_state, change), KOKORO)
                continue
            
            if action == VOICE_STATE_UPDATE:
                event_handler = client.events.voice_client_update
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                     Task(event_handler(client, voice_state, change), KOKORO)
                continue
    else:
        guild._update_voice_state_restricted(data, user)


def VOICE_STATE_UPDATE__OPT_MC(client, data):
    try:
        guild_id = data['guild_id']
    except KeyError:
        # Do not handle outside of guild calls
        return
    
    try:
        guild = GUILDS[guild_id]
    except KeyError:
        return
    
    if first_client(guild.clients, INTENT_MASK_GUILD_VOICE_STATES) is not client:
        return
    
    try:
        user_data = data['member']
    except KeyError:
        user_data = data['user']
    
    user = User(user_data)
    
    if isinstance(user, Client):
        for action, voice_state, change in guild._update_voice_state(data, user):
            if action == VOICE_STATE_JOIN:
                event_handler = user.events.voice_client_join
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(user, voice_state), KOKORO)
                continue
            
            if action == VOICE_STATE_MOVE:
                event_handler = user.events.voice_client_move
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                     Task(event_handler(user, voice_state, change), KOKORO)
                continue
            
            if action == VOICE_STATE_LEAVE:
                event_handler = user.events.voice_client_leave
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                     Task(event_handler(user, voice_state, change), KOKORO)
                continue
            
            if action == VOICE_STATE_UPDATE:
                event_handler = user.events.voice_client_update
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                     Task(event_handler(user, voice_state, change), KOKORO)
                continue
    
    else:
        guild._update_voice_state_restricted(data, user)


add_parser(
    'VOICE_STATE_UPDATE',
    VOICE_STATE_UPDATE__CAL_SC,
    VOICE_STATE_UPDATE__CAL_MC,
    VOICE_STATE_UPDATE__OPT_SC,
    VOICE_STATE_UPDATE__OPT_MC)
del VOICE_STATE_UPDATE__CAL_SC, \
    VOICE_STATE_UPDATE__CAL_MC, \
    VOICE_STATE_UPDATE__OPT_SC, \
    VOICE_STATE_UPDATE__OPT_MC


def VOICE_SERVER_UPDATE_CAL(client, data):
    guild_id = data.get('guild_id', None)
    if guild_id is None:
        guild_id = 0
    else:
        guild_id = int(guild_id)
    
    endpoint = data.get('endpoint', None)
    token = data.get('token', None)
    
    event = VoiceServerUpdateEvent()
    event.endpoint = endpoint
    event.guild_id = guild_id
    event.token = token
    
    Task(client.events.voice_server_update(client, event), KOKORO)

def VOICE_SERVER_UPDATE_OPT(client, data):
    pass

add_parser(
    'VOICE_SERVER_UPDATE',
    VOICE_SERVER_UPDATE_CAL,
    VOICE_SERVER_UPDATE_CAL,
    VOICE_SERVER_UPDATE_OPT,
    VOICE_SERVER_UPDATE_OPT)
del VOICE_SERVER_UPDATE_CAL, \
    VOICE_SERVER_UPDATE_OPT


if CACHE_PRESENCE:
    def TYPING_START__CAL(client, data):
        channel_id = int(data['channel_id'])
        try:
            channel = CHANNELS[channel_id]
        except KeyError:
            guild_sync(client, data, ('TYPING_START', check_channel, channel_id))
            return
        
        user_id = int(data['user_id'])
        user = create_partial_user_from_id(user_id)
        
        timestamp = datetime.utcfromtimestamp(data.get('timestamp', None))
        
        Task(client.events.typing(client, channel, user, timestamp), KOKORO)
    
    def TYPING_START__OPT(client, data):
        return
else:
    def TYPING_START__CAL(client, data):
        return
    TYPING_START__OPT=TYPING_START__CAL

add_parser(
    'TYPING_START',
    TYPING_START__CAL,
    TYPING_START__CAL,
    TYPING_START__OPT,
    TYPING_START__OPT)
del TYPING_START__CAL, \
    TYPING_START__OPT

def INVITE_CREATE__CAL(client, data):
    invite = Invite(data, False)
    Task(client.events.invite_create(client, invite), KOKORO)

def INVITE_CREATE__OPT(client, data):
    pass

add_parser(
    'INVITE_CREATE',
    INVITE_CREATE__CAL,
    INVITE_CREATE__CAL,
    INVITE_CREATE__OPT,
    INVITE_CREATE__OPT)
del INVITE_CREATE__CAL, \
    INVITE_CREATE__OPT

def INVITE_DELETE__CAL(client, data):
    invite = Invite(data, True)
    Task(client.events.invite_delete(client, invite), KOKORO)

def INVITE_DELETE__OPT(client, data):
    pass

add_parser('INVITE_DELETE',
    INVITE_DELETE__CAL,
    INVITE_DELETE__CAL,
    INVITE_DELETE__OPT,
    INVITE_DELETE__OPT)
del INVITE_DELETE__CAL, \
    INVITE_DELETE__OPT

def RELATIONSHIP_ADD__CAL(client, data):
    user_id = int(data['id'])
    try:
        old_relationship = client.relationships.pop(user_id)
    except KeyError:
        old_relationship = None
    
    new_relationship = Relationship(client, data, user_id)
    
    if old_relationship is None:
        coroutine = client.events.relationship_add(client, new_relationship)
    else:
        coroutine = client.events.relationship_change(client, old_relationship, new_relationship)
    Task(coroutine, KOKORO)

def RELATIONSHIP_ADD__OPT(client, data):
    user_id = int(data['id'])
    try:
        del client.relationships[user_id]
    except KeyError:
        pass
    
    Relationship(client, data, user_id)

add_parser(
    'RELATIONSHIP_ADD',
    RELATIONSHIP_ADD__CAL,
    RELATIONSHIP_ADD__CAL,
    RELATIONSHIP_ADD__OPT,
    RELATIONSHIP_ADD__OPT)
del RELATIONSHIP_ADD__CAL, \
    RELATIONSHIP_ADD__OPT

def RELATIONSHIP_REMOVE__CAL(client, data):
    user_id = int(data['id'])
    try:
        old_relationship = client.relationships.pop(user_id)
    except KeyError:
        return
    
    Task(client.events.relationship_delete(client, old_relationship), KOKORO)

def RELATIONSHIP_REMOVE__OPT(client, data):
    user_id = int(data['id'])
    try:
        del client.user.relations[user_id]
    except KeyError:
        pass

add_parser(
    'RELATIONSHIP_REMOVE',
    RELATIONSHIP_REMOVE__CAL,
    RELATIONSHIP_REMOVE__CAL,
    RELATIONSHIP_REMOVE__OPT,
    RELATIONSHIP_REMOVE__OPT)
del RELATIONSHIP_REMOVE__CAL, \
    RELATIONSHIP_REMOVE__OPT

#empty list
def PRESENCES_REPLACE(client, data):
    pass

add_parser(
    'PRESENCES_REPLACE',
    PRESENCES_REPLACE,
    PRESENCES_REPLACE,
    PRESENCES_REPLACE,
    PRESENCES_REPLACE)
del PRESENCES_REPLACE

def USER_SETTINGS_UPDATE(client, data):
    pass

add_parser(
    'USER_SETTINGS_UPDATE',
    USER_SETTINGS_UPDATE,
    USER_SETTINGS_UPDATE,
    USER_SETTINGS_UPDATE,
    USER_SETTINGS_UPDATE)
del USER_SETTINGS_UPDATE

def GIFT_CODE_UPDATE__CAL(client, data):
    channel_id = int(data['channel_id'])
    try:
        channel = CHANNELS[channel_id]
    except KeyError:
        guild_sync(client, data, ('GIFT_CODE_UPDATE', check_channel, channel_id))
        return
    
    gift = Gift(data)
    Task(client.events.gift_update(client, channel, gift), KOKORO)

def GIFT_CODE_UPDATE__OPT(client, data):
    pass

add_parser(
    'GIFT_CODE_UPDATE',
    GIFT_CODE_UPDATE__CAL,
    GIFT_CODE_UPDATE__CAL,
    GIFT_CODE_UPDATE__OPT,
    GIFT_CODE_UPDATE__OPT)
del GIFT_CODE_UPDATE__CAL, \
    GIFT_CODE_UPDATE__OPT

#hooman only event
def USER_ACHIEVEMENT_UPDATE(client, data):
    pass

add_parser(
    'USER_ACHIEVEMENT_UPDATE',
    USER_ACHIEVEMENT_UPDATE,
    USER_ACHIEVEMENT_UPDATE,
    USER_ACHIEVEMENT_UPDATE,
    USER_ACHIEVEMENT_UPDATE)
del USER_ACHIEVEMENT_UPDATE

#hooman only event
def MESSAGE_ACK(client, data):
    # contains `message_id` and `channel_id`, no clue, how it could be useful.
    pass

add_parser(
    'MESSAGE_ACK',
    MESSAGE_ACK,
    MESSAGE_ACK,
    MESSAGE_ACK,
    MESSAGE_ACK)
del MESSAGE_ACK

#hooman only event, with the own presence data, what we get anyways.
def SESSIONS_REPLACE(client, data):
    pass

add_parser(
    'SESSIONS_REPLACE',
    SESSIONS_REPLACE,
    SESSIONS_REPLACE,
    SESSIONS_REPLACE,
    SESSIONS_REPLACE)
del SESSIONS_REPLACE

# Hooman only event,
def USER_GUILD_SETTINGS_UPDATE(client, data):
    # individual guild settings data.
    pass

add_parser(
    'USER_GUILD_SETTINGS_UPDATE',
    USER_GUILD_SETTINGS_UPDATE,
    USER_GUILD_SETTINGS_UPDATE,
    USER_GUILD_SETTINGS_UPDATE,
    USER_GUILD_SETTINGS_UPDATE)
del USER_GUILD_SETTINGS_UPDATE


# Hooman only event,
def CHANNEL_UNREAD_UPDATE(client, data):
    pass

add_parser(
    'CHANNEL_UNREAD_UPDATE',
    CHANNEL_UNREAD_UPDATE,
    CHANNEL_UNREAD_UPDATE,
    CHANNEL_UNREAD_UPDATE,
    CHANNEL_UNREAD_UPDATE)
del CHANNEL_UNREAD_UPDATE




def INTERACTION_CREATE__CAL(client, data):
    # Since interaction can be called from guilds, where the bot is not in, we will call it even if the respective
    # channel & guild are not cached.
    event = InteractionEvent(data)
    
    Task(client.events.interaction_create(client, event), KOKORO)

def INTERACTION_CREATE__OPT(client, data):
    pass

add_parser(
    'INTERACTION_CREATE',
    INTERACTION_CREATE__CAL,
    INTERACTION_CREATE__CAL,
    INTERACTION_CREATE__OPT,
    INTERACTION_CREATE__OPT)
del INTERACTION_CREATE__CAL, \
    INTERACTION_CREATE__OPT


def APPLICATION_COMMAND_CREATE__CAL(client, data):
    guild_id = int(data['guild_id'])
    
    application_command = ApplicationCommand.from_data(data)
    
    Task(client.events.application_command_create(client, guild_id, application_command), KOKORO)

def APPLICATION_COMMAND_CREATE__OPT(client, data):
    pass

add_parser(
    'APPLICATION_COMMAND_CREATE',
    APPLICATION_COMMAND_CREATE__CAL,
    APPLICATION_COMMAND_CREATE__CAL,
    APPLICATION_COMMAND_CREATE__OPT,
    APPLICATION_COMMAND_CREATE__OPT)
del APPLICATION_COMMAND_CREATE__CAL, \
    APPLICATION_COMMAND_CREATE__OPT


def APPLICATION_COMMAND_UPDATE__CAL(client, data):
    guild_id = int(data['guild_id'])
    application_command_id = data['id']
    
    try:
        application_command = APPLICATION_COMMANDS[application_command_id]
    except KeyError:
        application_command = ApplicationCommand.from_data(data)
        old_attributes = None
    else:
        old_attributes = application_command._difference_update_attributes(data)
        if not old_attributes:
            return
    
    Task(client.events.application_command_update(client, guild_id, application_command, old_attributes), KOKORO)

def APPLICATION_COMMAND_UPDATE__OPT(client, data):
    application_command_id = data['id']
    try:
        application_command = APPLICATION_COMMANDS[application_command_id]
    except KeyError:
        pass
    else:
        application_command._update_attributes(data)

add_parser(
    'APPLICATION_COMMAND_UPDATE',
    APPLICATION_COMMAND_UPDATE__CAL,
    APPLICATION_COMMAND_UPDATE__CAL,
    APPLICATION_COMMAND_UPDATE__OPT,
    APPLICATION_COMMAND_UPDATE__OPT)
del APPLICATION_COMMAND_UPDATE__CAL, \
    APPLICATION_COMMAND_UPDATE__OPT


def APPLICATION_COMMAND_DELETE__CAL(client, data):
    guild_id = int(data['guild_id'])
    application_command = ApplicationCommand.from_data(data)
    
    Task(client.events.application_command_delete(client, guild_id, application_command), KOKORO)

def APPLICATION_COMMAND_DELETE__OPT(client, data):
    pass

add_parser(
    'APPLICATION_COMMAND_DELETE',
    APPLICATION_COMMAND_DELETE__CAL,
    APPLICATION_COMMAND_DELETE__CAL,
    APPLICATION_COMMAND_DELETE__OPT,
    APPLICATION_COMMAND_DELETE__OPT)
del APPLICATION_COMMAND_DELETE__CAL, \
    APPLICATION_COMMAND_DELETE__OPT


def APPLICATION_COMMAND_PERMISSIONS_UPDATE__CAL(client, data):
    application_command_permission = ApplicationCommandPermission.from_data(data)
    
    Task(client.events.application_command_permission_update(client, application_command_permission), KOKORO)

def APPLICATION_COMMAND_PERMISSIONS_UPDATE__OPT(client, data):
    pass

add_parser(
    'APPLICATION_COMMAND_PERMISSIONS_UPDATE',
    APPLICATION_COMMAND_PERMISSIONS_UPDATE__CAL,
    APPLICATION_COMMAND_PERMISSIONS_UPDATE__CAL,
    APPLICATION_COMMAND_PERMISSIONS_UPDATE__OPT,
    APPLICATION_COMMAND_PERMISSIONS_UPDATE__OPT)
del APPLICATION_COMMAND_PERMISSIONS_UPDATE__CAL, \
    APPLICATION_COMMAND_PERMISSIONS_UPDATE__OPT


def STAGE_INSTANCE_CREATE__CAL(client, data):
    stage = Stage(data)
    
    Task(client.events.stage_create(client, stage), KOKORO)

def STAGE_INSTANCE_CREATE__OPT(client, data):
    Stage(data)

add_parser(
    'STAGE_INSTANCE_CREATE',
    STAGE_INSTANCE_CREATE__CAL,
    STAGE_INSTANCE_CREATE__CAL,
    STAGE_INSTANCE_CREATE__OPT,
    STAGE_INSTANCE_CREATE__OPT)
del STAGE_INSTANCE_CREATE__CAL, \
    STAGE_INSTANCE_CREATE__OPT


def STAGE_INSTANCE_UPDATE__CAL_SC(client, data):
    stage_id = int(data['id'])
    try:
        stage = STAGES[stage_id]
    except KeyError:
        return
    
    old_attributes = stage._difference_update_attributes(data)
    if not old_attributes:
        return
    
    Task(client.events.stage_edit(client, stage, old_attributes), KOKORO)

def STAGE_INSTANCE_UPDATE__CAL_MC(client, data):
    stage_id = int(data['id'])
    try:
        stage = STAGES[stage_id]
    except KeyError:
        return
    
    clients = filter_clients(stage.channel.clients, INTENT_MASK_GUILDS)
    if clients.send(None) is not client:
        clients.close()
        return
    
    old_attributes = stage._difference_update_attributes(data)
    if not old_attributes:
        return
    
    for client_ in clients:
        event_handler = client_.events.stage_edit
        if (event_handler is not DEFAULT_EVENT_HANDLER):
            Task(event_handler(client_, stage, old_attributes), KOKORO)


def STAGE_INSTANCE_UPDATE__OPT(client, data):
    stage_id = int(data['id'])
    try:
        stage = STAGES[stage_id]
    except KeyError:
        return
    
    stage._update_attributes(data)


add_parser(
    'STAGE_INSTANCE_UPDATE',
    STAGE_INSTANCE_UPDATE__CAL_SC,
    STAGE_INSTANCE_UPDATE__CAL_MC,
    STAGE_INSTANCE_UPDATE__OPT,
    STAGE_INSTANCE_UPDATE__OPT)
del STAGE_INSTANCE_UPDATE__CAL_SC, \
    STAGE_INSTANCE_UPDATE__CAL_MC, \
    STAGE_INSTANCE_UPDATE__OPT


def STAGE_INSTANCE_DELETE__CAL_SC(client, data):
    stage_id = int(data['id'])
    try:
        stage = STAGES[stage_id]
    except KeyError:
        return
    
    stage._delete()
    
    Task(client.events.stage_delete(client, stage), KOKORO)

def STAGE_INSTANCE_DELETE__CAL_MC(client, data):
    stage_id = int(data['id'])
    try:
        stage = STAGES[stage_id]
    except KeyError:
        return
    
    clients = filter_clients(stage.channel.clients, INTENT_MASK_GUILDS)
    if clients.send(None) is not client:
        clients.close()
        return
    
    stage._delete()
    
    for client_ in clients:
        event_handler = client_.events.stage_delete
        if (event_handler is not DEFAULT_EVENT_HANDLER):
            Task(event_handler(client_, stage), KOKORO)


def STAGE_INSTANCE_DELETE__OPT(client, data):
    stage_id = int(data['id'])
    try:
        stage = STAGES[stage_id]
    except KeyError:
        return
    
    stage._delete()


add_parser(
    'STAGE_INSTANCE_DELETE',
    STAGE_INSTANCE_DELETE__CAL_SC,
    STAGE_INSTANCE_DELETE__CAL_MC,
    STAGE_INSTANCE_DELETE__OPT,
    STAGE_INSTANCE_DELETE__OPT)
del STAGE_INSTANCE_DELETE__CAL_SC, \
    STAGE_INSTANCE_DELETE__CAL_MC, \
    STAGE_INSTANCE_DELETE__OPT


def THREAD_LIST_SYNC(client, data):
    guild_id = int(data['guild_id'])
    
    thread_channel_datas = data['threads']
    for thread_channel_data in thread_channel_datas:
        ChannelThread(thread_channel_data, client, guild_id)
    
    thread_user_datas = data['members']
    for thread_user_data in thread_user_datas:
        thread_chanel_id = int(data['id'])
        try:
            thread_channel = CHANNELS[thread_chanel_id]
        except KeyError:
            return
        
        user_id = int(thread_user_data['user_id'])
        user = create_partial_user_from_id(user_id)
        
        thread_user_create(thread_channel, user, thread_user_data)


add_parser(
    'THREAD_LIST_SYNC',
    THREAD_LIST_SYNC,
    THREAD_LIST_SYNC,
    THREAD_LIST_SYNC,
    THREAD_LIST_SYNC)
del THREAD_LIST_SYNC


def THREAD_MEMBER_UPDATE__CAL_SC(client, data):
    thread_chanel_id = int(data['id'])
    try:
        thread_channel = CHANNELS[thread_chanel_id]
    except KeyError:
        return
    
    old_attributes = thread_user_update(thread_channel, client, data)
    if (old_attributes is None):
        return
    
    Task(client.user_thread_profile_edit(client, thread_channel, client, old_attributes), KOKORO)


def THREAD_MEMBER_UPDATE__CAL_MC(client, data):
    thread_chanel_id = int(data['id'])
    try:
        thread_channel = CHANNELS[thread_chanel_id]
    except KeyError:
        return
    
    clients = filter_clients(thread_channel.clients, INTENT_MASK_GUILDS)
    if clients.send(None) is not client:
        clients.close()
        return
    
    old_attributes = thread_user_update(thread_channel, client, data)
    if (old_attributes is None):
        clients.close()
        return
    
    for client_ in clients:
        event_handler = client_.user_thread_profile_edit
        if (event_handler is not DEFAULT_EVENT_HANDLER):
            Task(event_handler(client_, thread_channel, client, old_attributes), KOKORO)


def THREAD_MEMBER_UPDATE__OPT(client, data):
    thread_chanel_id = int(data['id'])
    try:
        thread_channel = CHANNELS[thread_chanel_id]
    except KeyError:
        return
    
    thread_user_create(thread_channel, client, data)


add_parser(
    'THREAD_MEMBER_UPDATE',
    THREAD_MEMBER_UPDATE__CAL_SC,
    THREAD_MEMBER_UPDATE__CAL_MC,
    THREAD_MEMBER_UPDATE__OPT,
    THREAD_MEMBER_UPDATE__OPT)
del THREAD_MEMBER_UPDATE__CAL_SC, \
    THREAD_MEMBER_UPDATE__CAL_MC, \
    THREAD_MEMBER_UPDATE__OPT


def THREAD_MEMBERS_UPDATE__CAL_SC(client, data):
    thread_chanel_id = int(data['id'])
    try:
        thread_channel = CHANNELS[thread_chanel_id]
    except KeyError:
        return
    
    removed_user_ids = data.get('removed_member_ids', None)
    if (removed_user_ids is not None) and removed_user_ids:
        for user_id in removed_user_ids:
            user_id = int(user_id)
            
            thread_user_deletion = thread_user_pop(thread_channel, user_id, client)
            if (thread_user_deletion is not None):
                event_handler = client.events.thread_user_delete
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client, thread_channel, *thread_user_deletion), KOKORO)
    
    thread_user_datas = data.get('added_members', None)
    if (thread_user_datas is not None) and thread_user_datas:
        for thread_user_data in thread_user_datas:
            user_id = int(thread_user_data['user_id'])
            user = create_partial_user_from_id(user_id)
            
            created = thread_user_create(thread_channel, user, thread_user_data)
            if created:
                event_handler = client.events.thread_user_add
                if (event_handler is not DEFAULT_EVENT_HANDLER):
                    Task(event_handler(client, thread_channel, user), KOKORO)


def THREAD_MEMBERS_UPDATE__CAL_MC(client, data):
    thread_chanel_id = int(data['id'])
    try:
        thread_channel = CHANNELS[thread_chanel_id]
    except KeyError:
        return
    
    if client.intents&INTENT_MASK_GUILD_USERS:
        clients = filter_clients(thread_channel.clients, INTENT_MASK_GUILD_USERS)
    
        if clients.send(None) is not client:
            return
        
        just_me = False
    else:
        clients = filter_just_me(client)
        just_me = True
    
    
    thread_user_deletions = None
    removed_user_ids = data.get('removed_member_ids', None)
    if (removed_user_ids is not None) and removed_user_ids:
        for user_id in removed_user_ids:
            user_id = int(user_id)
            
            thread_user_deletion = thread_user_pop(thread_channel, user_id, client)
            if (thread_user_deletion is not None):
                if thread_user_deletions is None:
                    thread_user_deletions = []
                
                thread_user_deletions.append(thread_user_deletion)
    
    
    thread_user_additions = None
    
    thread_user_datas = data.get('added_members', None)
    if (thread_user_datas is not None) and thread_user_datas:
        for thread_user_data in thread_user_datas:
            user_id = int(thread_user_data['user_id'])
            user = create_partial_user_from_id(user_id)
            
            created = thread_user_create(thread_channel, user, thread_user_data)
            if created or just_me:
                if thread_user_additions is None:
                    thread_user_additions = []
                
                thread_user_additions.append(user)
    
    
    for client_ in clients:
        if (thread_user_deletions is not None):
            event_handler = client_.events.thread_user_delete
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                for thread_user_deletion in thread_user_deletions:
                    Task(event_handler(client_, thread_channel, *thread_user_deletion), KOKORO)
        
        if (thread_user_additions is not None):
            event_handler = client_.events.thread_user_add
            if (event_handler is not DEFAULT_EVENT_HANDLER):
                for user in thread_user_additions:
                    Task(event_handler(client_, thread_channel, user), KOKORO)


def THREAD_MEMBERS_UPDATE__OPT_SC(client, data):
    thread_chanel_id = int(data['id'])
    try:
        thread_channel = CHANNELS[thread_chanel_id]
    except KeyError:
        return
    
    removed_user_ids = data.get('removed_member_ids', None)
    if (removed_user_ids is not None) and removed_user_ids:
        for user_id in removed_user_ids:
            user_id = int(user_id)
            
            thread_user_delete(thread_channel, user_id)
    
    thread_user_datas = data.get('added_members', None)
    if (thread_user_datas is not None) and thread_user_datas:
        for thread_user_data in thread_user_datas:
            user_id = int(thread_user_data['user_id'])
            user = create_partial_user_from_id(user_id)
            
            thread_user_create(thread_channel, user, thread_user_data)


def THREAD_MEMBERS_UPDATE__OPT_MC(client, data):
    thread_chanel_id = int(data['id'])
    try:
        thread_channel = CHANNELS[thread_chanel_id]
    except KeyError:
        return
    
    if first_client_or_me(thread_channel.clients, INTENT_MASK_GUILD_USERS, client) is not client:
        return
    
    removed_user_ids = data.get('removed_member_ids', None)
    if (removed_user_ids is not None) and removed_user_ids:
        for user_id in removed_user_ids:
            user_id = int(user_id)
            
            thread_user_delete(thread_channel, user_id)
    
    thread_user_datas = data.get('added_members', None)
    if (thread_user_datas is not None) and thread_user_datas:
        for thread_user_data in thread_user_datas:
            user_id = int(thread_user_data['user_id'])
            user = create_partial_user_from_id(user_id)
            
            thread_user_create(thread_channel, user, thread_user_data)

add_parser(
    'THREAD_MEMBERS_UPDATE',
    THREAD_MEMBERS_UPDATE__CAL_SC,
    THREAD_MEMBERS_UPDATE__CAL_MC,
    THREAD_MEMBERS_UPDATE__OPT_SC,
    THREAD_MEMBERS_UPDATE__OPT_MC)
del THREAD_MEMBERS_UPDATE__CAL_SC, \
    THREAD_MEMBERS_UPDATE__CAL_MC, \
    THREAD_MEMBERS_UPDATE__OPT_SC, \
    THREAD_MEMBERS_UPDATE__OPT_MC


def GUILD_APPLICATION_COMMAND_COUNTS_UPDATE(client, data):
    pass

add_parser(
    'GUILD_APPLICATION_COMMAND_COUNTS_UPDATE',
    GUILD_APPLICATION_COMMAND_COUNTS_UPDATE,
    GUILD_APPLICATION_COMMAND_COUNTS_UPDATE,
    GUILD_APPLICATION_COMMAND_COUNTS_UPDATE,
    GUILD_APPLICATION_COMMAND_COUNTS_UPDATE)
del GUILD_APPLICATION_COMMAND_COUNTS_UPDATE
