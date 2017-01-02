"""
Support for custom shell commands to turn a switch on/off.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/switch.command_line/
"""
import logging
import subprocess

import voluptuous as vol

from homeassistant.components.switch import (SwitchDevice, PLATFORM_SCHEMA,
                                             ENTITY_ID_FORMAT)
from homeassistant.const import (
    CONF_ANY_USER, CONF_COMMAND_OFF, CONF_COMMAND_ON, CONF_COMMAND_STATE,
    CONF_FRIENDLY_NAME, CONF_PERMISSIONS, CONF_SWITCHES, CONF_VALUE_TEMPLATE )
from homeassistant.exceptions import PermissionDenied
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

SWITCH_SCHEMA = vol.Schema({
    vol.Optional(CONF_COMMAND_OFF, default='true'): cv.string,
    vol.Optional(CONF_COMMAND_ON, default='true'): cv.string,
    vol.Optional(CONF_COMMAND_STATE): cv.string,
    vol.Optional(CONF_FRIENDLY_NAME): cv.string,
    vol.Optional(CONF_VALUE_TEMPLATE): cv.template,
    vol.Optional(CONF_PERMISSIONS, default=None): dict,
})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_SWITCHES): vol.Schema({cv.slug: SWITCH_SCHEMA}),
})


# pylint: disable=unused-argument
def setup_platform(hass, config, add_devices, discovery_info=None):
    """Find and return switches controlled by shell commands."""
    devices = config.get(CONF_SWITCHES, {})
    switches = []

    for object_id, device_config in devices.items():
        value_template = device_config.get(CONF_VALUE_TEMPLATE)

        if value_template is not None:
            value_template.hass = hass

        switches.append(
            CommandSwitch(
                hass,
                object_id,
                device_config.get(CONF_FRIENDLY_NAME, object_id),
                device_config.get(CONF_COMMAND_ON),
                device_config.get(CONF_COMMAND_OFF),
                device_config.get(CONF_COMMAND_STATE),
                value_template,
                device_config.get(CONF_PERMISSIONS)
            )
        )

    if not switches:
        _LOGGER.error("No switches added")
        return False

    add_devices(switches)


class CommandSwitch(SwitchDevice):
    """Representation of a switch that can be toggled using shell commands."""

    def __init__(self, hass, object_id, friendly_name, command_on,
                 command_off, command_state, value_template, permissions):
        """Initialize the switch."""
        self._hass = hass
        self.entity_id = ENTITY_ID_FORMAT.format(object_id)
        self._name = friendly_name
        self._state = False
        self._command_on = command_on
        self._command_off = command_off
        self._command_state = command_state
        self._value_template = value_template
        self._permissions = permissions

    @staticmethod
    def _switch(command):
        """Execute the actual commands."""
        _LOGGER.info('Running command: %s', command)

        success = (subprocess.call(command, shell=True) == 0)

        if not success:
            _LOGGER.error('Command failed: %s', command)

        return success

    @staticmethod
    def _query_state_value(command):
        """Execute state command for return value."""
        _LOGGER.info('Running state command: %s', command)

        try:
            return_value = subprocess.check_output(command, shell=True)
            return return_value.strip().decode('utf-8')
        except subprocess.CalledProcessError:
            _LOGGER.error('Command failed: %s', command)

    @staticmethod
    def _query_state_code(command):
        """Execute state command for return code."""
        _LOGGER.info('Running state command: %s', command)
        return subprocess.call(command, shell=True) == 0

    @property
    def should_poll(self):
        """Only poll if we have state command."""
        return self._command_state is not None

    @property
    def name(self):
        """Return the name of the switch."""
        return self._name

    @property
    def is_on(self):
        """Return true if device is on."""
        return self._state

    @property
    def permissions(self):
        """
        Return the permission dictionary of the current entity,
        is None if no special permissions are set for current entity.
        """
        return self._permissions

    @property
    def assumed_state(self):
        """Return true if we do optimistic updates."""
        return self._command_state is False

    def _query_state(self):
        """Query for state."""
        if not self._command_state:
            _LOGGER.error('No state command specified')
            return
        if self.has_perm(perm='r') is False:
            _LOGGER.error("current user does not have permission to query "
                          "state of %s" % self._name)
            return
        if self._value_template:
            return CommandSwitch._query_state_value(self._command_state)
        return CommandSwitch._query_state_code(self._command_state)

    def update(self):
        """Update device state."""
        _LOGGER.debug("update() of %s: command_state %s" % (self._name, self._command_state))
        if self.has_perm(perm='w') and self._command_state:
            payload = str(self._query_state())
            if self._value_template:
                payload = self._value_template.render_with_possible_json_value(
                    payload)
            self._state = (payload.lower() == "true")

    def turn_on(self, **kwargs):
        """Turn the device on, if user is permitted to."""
        if (self.has_perm(perm='w') and
                CommandSwitch._switch(self._command_on) and
                not self._command_state):
            self._state = True
            self.schedule_update_ha_state()

    def turn_off(self, **kwargs):
        """Turn the device off, if user is permitted to."""
        if (self.has_perm(perm='w') and
                CommandSwitch._switch(self._command_off) and
                not self._command_state):
            self._state = False
            self.schedule_update_ha_state()

    def has_perm(self, perm='r'):
        """Return if currently logged in api_user has permission 'perm'."""
        user = None
        try:
            user = self._hass.http.api_user
        except AttributeError:  # no http object exists or no api_user set
            pass
        if user is None:
            user = CONF_ANY_USER
        if self._permissions is None:
            user_perm = 'rwx'   # no restrictions set for current entity
        else:
            user_perm = self.permissions.get(user, '')
        if not contains_perm(user_perm, perm):
            msg = "User '%s' does not have '%s' permission for '%s', only " \
                  "has '%s'." % (user, perm, self._name, user_perm)
            _LOGGER.error(msg)
            raise PermissionDenied(msg)
        return True


def contains_perm(perm, requested_perm='r'):
    """
    Return true if user has permission to access the component, else false.
    perm 'r' means user has read access, i.e. sees the component,
    perm 'w' means that user can write to the component (change its state)
    If multiple permissions are mentioned then only return true if user has all.
    """
    if perm is None:
        return False
    if perm.find(requested_perm) >= 0:
        # TODO: maybe using find() is too easy, if permissions are written
        # without using same order (rxw instead of rwx) - that won't match
        return True
    else:
        return False
