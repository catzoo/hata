__all__ = ()

REQUEST_TIMEOUT = 15.0

RECONNECT_INTERVAL = 5.0
RECONNECT_RATE_LIMITED_INTERVAL = 60.0

IPC_VERSION = 1

OPERATION_HANDSHAKE = 0
OPERATION_FRAME = 1
OPERATION_CLOSE = 2
OPERATION_PING = 3
OPERATION_PONG = 4

CLOSE_PAYLOAD_KEY_CODE = 'code'
CLOSE_PAYLOAD_KEY_MESSAGE = 'message'


OPERATION_VALUE_TO_NAME = {
    OPERATION_HANDSHAKE: 'handshake',
    OPERATION_FRAME: 'frame',
    OPERATION_CLOSE: 'close',
    OPERATION_PING: 'ping',
    OPERATION_PONG: 'pong',
}

DEFAULT_OPERATION_NAME = 'unknown_operation',

PAYLOAD_COMMAND_DISPATCH = 'DISPATCH'
PAYLOAD_COMMAND_AUTHORIZE = 'AUTHORIZE'
PAYLOAD_COMMAND_AUTHENTICATE = 'AUTHENTICATE'
PAYLOAD_COMMAND_GUILD_GET = 'GET_GUILD'
PAYLOAD_COMMAND_GUILD_GET_ALL = 'GET_GUILDS'
PAYLOAD_COMMAND_CHANNEL_GET = 'GET_CHANNEL'
PAYLOAD_COMMAND_GUILD_CHANNEL_GET_ALL = 'GET_CHANNELS'
PAYLOAD_COMMAND_SUBSCRIBE = 'SUBSCRIBE'
PAYLOAD_COMMAND_UNSUBSCRIBE = 'UNSUBSCRIBE'
PAYLOAD_COMMAND_USER_VOICE_SETTINGS_SET = 'SET_USER_VOICE_SETTINGS'
PAYLOAD_COMMAND_CHANNEL_VOICE_SELECT = 'SELECT_VOICE_CHANNEL'
PAYLOAD_COMMAND_CHANNEL_VOICE_GET = 'GET_SELECTED_VOICE_CHANNEL'
PAYLOAD_COMMAND_CHANNEL_TEXT_SELECT = 'SELECT_TEXT_CHANNEL'
PAYLOAD_COMMAND_VOICE_SETTINGS_GET = 'GET_VOICE_SETTINGS'
PAYLOAD_COMMAND_VOICE_SETTINGS_SET = 'SET_VOICE_SETTINGS'
PAYLOAD_COMMAND_CERTIFIED_DEVICES_SET = 'SET_CERTIFIED_DEVICES'
PAYLOAD_COMMAND_ACTIVITY_SET = 'SET_ACTIVITY'
PAYLOAD_COMMAND_ACTIVITY_JOIN_ACCEPT = 'SEND_ACTIVITY_JOIN_INVITE'
PAYLOAD_COMMAND_ACTIVITY_JOIN_REJECT = 'CLOSE_ACTIVITY_REQUEST'


PAYLOAD_KEY_COMMAND = 'cmd'
PAYLOAD_KEY_NONCE = 'nonce'
PAYLOAD_KEY_EVENT = 'evt'
PAYLOAD_KEY_DATA = 'data'
PAYLOAD_KEY_PARAMETERS = 'args'

EVENT_ERROR = 'ERROR'

CLOSE_CODE_NORMAL = 1000
CLOSE_CODE_UNSUPPORTED = 1003
CLOSE_CODE_ABNORMAL = 1006
CLOSE_CODE_INVALID_APPLICATION_ID = 4000
CLOSE_CODE_INVALID_ORIGIN = 4001
CLOSE_CODE_RATE_LIMITED = 4002
CLOSE_CODE_TOKEN_REVOKED = 4003
CLOSE_CODE_INVALID_VERSION = 4004
CLOSE_CODE_INVALID_ENCODING = 4005

CLOSE_CODES_RECONNECT = frozenset((
    CLOSE_CODE_RATE_LIMITED,
    CLOSE_CODE_NORMAL,
    CLOSE_CODE_UNSUPPORTED,
    CLOSE_CODE_ABNORMAL,
))

CLOSE_CODES_FATAL = frozenset((
    CLOSE_CODE_INVALID_APPLICATION_ID,
    CLOSE_CODE_INVALID_ORIGIN,
    CLOSE_CODE_TOKEN_REVOKED,
    CLOSE_CODE_INVALID_VERSION,
    CLOSE_CODE_INVALID_ENCODING,
))
