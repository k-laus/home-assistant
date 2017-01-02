"""Authentication for HTTP component."""
import asyncio
import binascii
import hashlib
import hmac
import logging
import os

from homeassistant.const import HTTP_HEADER_HA_AUTH
from .util import get_real_ip
from .const import KEY_TRUSTED_NETWORKS, KEY_AUTHENTICATED

DATA_API_PASSWORD = 'api_password'

_LOGGER = logging.getLogger(__name__)


@asyncio.coroutine
def auth_middleware(app, handler):
    """Authentication middleware."""
    # If no password set, just always set authenticated=True
    if app['hass'].http.api_password is None:
        @asyncio.coroutine
        def no_auth_middleware_handler(request):
            """Auth middleware to approve all requests."""
            request[KEY_AUTHENTICATED] = True
            return handler(request)

        return no_auth_middleware_handler

    @asyncio.coroutine
    def auth_middleware_handler(request):
        """Auth middleware to check authentication."""
        # Auth code verbose on purpose
        authenticated = False

        if (HTTP_HEADER_HA_AUTH in request.headers and
                validate_password(request,
                                  request.headers[HTTP_HEADER_HA_AUTH])):
            # A valid auth header has been set
            authenticated = True

        elif (DATA_API_PASSWORD in request.GET and
              validate_password(request, request.GET[DATA_API_PASSWORD])):
            authenticated = True

        elif is_trusted_ip(request):
            authenticated = True

        request[KEY_AUTHENTICATED] = authenticated

        return handler(request)

    return auth_middleware_handler


def is_trusted_ip(request):
    """Test if request is from a trusted ip."""
    ip_addr = get_real_ip(request)

    return ip_addr and any(
        ip_addr in trusted_network for trusted_network
        in request.app[KEY_TRUSTED_NETWORKS])

def hash_password(password, salt=None):
    """Create hash from password"""
    # TODO: randomize salt per installation and store it in configuration
    salt = b'\x02O\xc0P?\x16\xc4\xdb\xbe\x96\xba\xb4\xa9r\x87\xe0'
    iterations = 100000
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt,
                             iterations)
    hashed_passwd = binascii.hexlify(dk)
    return hashed_passwd

def validate_password(request, api_password):
    """
    Test if one of the passwords is valid: first try the http.api_password, then
    all the http.api_users' api_passwords.
    """
    # first, try old-style, only one api password
    validated = hmac.compare_digest(api_password,
                                    request.app['hass'].http.api_password)
    if validated:
        _LOGGER.debug("validation with old-style api_password was successful.")
        return validated
    if request.app['hass'].http.api_users is not None:
        hashed_passwd = hash_password(api_password)
        for api_user in request.app['hass'].http.api_users:
            pw_hash = request.app['hass'].http.api_users[api_user]\
                ['password_hash'].encode('utf-8')
            validated = hmac.compare_digest(hashed_passwd, pw_hash)
            if validated:
                _LOGGER.debug("api password_hash matched for user '%s'" % api_user)
                # remember current api username
                request.app['hass'].http.api_user = api_user
                break
    return validated