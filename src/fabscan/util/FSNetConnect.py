__author__ = 'mariolukas'

import json
import logging
import socket
from fabscan.FSEvents import FSEventManagerSingleton, FSEvents
from fabscan.util.FSInject import inject
from fabscan.util.FSUtil import json2obj

@inject(
    eventmanager=FSEventManagerSingleton
)
class FSNetConnect(object):
    def __init__(self, eventmanager):


        self.eventManager = eventmanager.instance

        self.netconnecd_commands = {
            "GET_WIFI_LIST": self._get_wifi_list,
            "GET_STATUS": self._get_status,
            "FORGET_WIFI": self._forget_wifi,
            "START_AP": self._start_ap,
            "STOP_AP": self._stop_ap,
            "CONFIGURE_WIFI": self._configure_and_select_wifi,
            "RESET": self._reset,
            "GET_STATUS": self._get_status
        }

        self._logger = logging.getLogger(__name__)

    def call_netconnectd_command(self, event, data=None, client=None):
        try:
            output = self.netconnecd_commands[event.function](data)

            message = {
                "client": client,
                "response": output,
                "command": event.function
            }

            self.eventManager.send_client_message(FSEvents.ON_NET_CONNECT, message)

        except Exception as e:
            output = "Error while calling netconnectd function: {}".format(e.message)
            self._logger.warn(output)
            return False, output


    def _get_wifi_list(self, force=False):
        payload = dict()
        if force:
            self._logger.info("Forcing wifi refresh...")
            payload["force"] = True

        flag, content = self._send_netconnect_message("list_wifi", payload)
        if not flag:
            raise RuntimeError("Error while listing wifi: " + content)

        result = []
        for wifi in content:
            result.append(
                dict(ssid=wifi["ssid"], address=wifi["address"], quality=wifi["signal"], encrypted=wifi["encrypted"]))
        return result

    def _get_status(self, args=None):
        payload = dict()

        flag, content = self._send_netconnect_message("status", payload)
        if not flag:
            raise RuntimeError("Error while querying status: " + content)

        return content

    def _configure_and_select_wifi(self, data):
        payload = dict(
            ssid=data['ssid'],
            psk=data['psk'],
            force=data['force']
        )

        flag, content = self._send_netconnect_message("config_wifi", payload)
        if not flag:
            raise RuntimeError("Error while configuring wifi: " + content)

        flag, content = self._send_netconnect_message("start_wifi", dict())
        if not flag:
            raise RuntimeError("Error while selecting wifi: " + content)

    def _forget_wifi(self, args=None):
        payload = dict()
        flag, content = self._send_netconnect_message("forget_wifi", payload)
        if not flag:
            raise RuntimeError("Error while forgetting wifi: " + content)

    def _reset(self):
        payload = dict()
        flag, content = self._send_netconnect_message("reset", payload)
        if not flag:
            raise RuntimeError("Error while factory resetting netconnectd: " + content)

    def _start_ap(self):
        payload = dict()
        flag, content = self._send_netconnect_message("start_ap", payload)
        if not flag:
            raise RuntimeError("Error while starting ap: " + content)

    def _stop_ap(self):
        payload = dict()
        flag, content = self._send_netconnect_message("stop_ap", payload)
        if not flag:
            raise RuntimeError("Error while stopping ap: " + content)

    def _send_netconnect_message(self, message, data):
        obj = dict()
        obj[message] = data

        js = json.dumps(obj, encoding="utf8", separators=(",", ":"))


        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(10)
        try:
            sock.connect("/var/run/netconnectd.sock")
            sock.sendall(js + '\x00')

            buffer = []
            while True:
                chunk = sock.recv(16)
                if chunk:
                    buffer.append(chunk)
                    if chunk.endswith('\x00'):
                        break

            data = ''.join(buffer).strip()[:-1]

            response = json.loads(data.strip())
            if "result" in response:
                self._logger.debug(response["result"])
                return True, response["result"]

            elif "error" in response:
                # something went wrong
                self._logger.warn("Request to netconnectd went wrong: " + response["error"])
                return False, response["error"]

            else:
                output = "Unknown response from netconnectd: {response!r}".format(response=response)
                self._logger.warn(output)
                return False, output

        except Exception as e:
            output = "Error while talking to netconnectd: {}".format(e.message)
            self._logger.warn(output)
            return False, output

        finally:
            sock.close()

