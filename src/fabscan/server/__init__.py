__author__ = "Mario Lukas"
__copyright__ = "Copyright 2017"
__license__ = "GPL v2"
__maintainer__ = "Mario Lukas"
__email__ = "info@mariolukas.de"

import time
import logging
import sys
import os

from WebServer import FSWebServer
from fabscan.FSVersion import __version__
from fabscan.util.FSInject import injector
from fabscan.util.FSUtil import FSSystem
from fabscan.server.websockets import FSWebSocketServer, FSWebSocketServerInterface
from fabscan.FSScanner import FSScanner, FSCommand
from fabscan.FSEvents import FSEventManagerSingleton, FSEventManagerInterface, FSEvents
from fabscan.FSConfig import ConfigInterface, ConfigSingleton, Config
from fabscan.FSSettings import SettingsInterface, SettingsSingleton, Settings
from fabscan.scanner.interfaces import FSScannerFactory
from fabscan.util.FSUpdate import do_upgrade
from fabscan.util.FSNetConnect import FSNetConnect



class FSServer(object):
    def __init__(self,config_file, settings_file):

        self.config_file = config_file
        self.settings_file = settings_file
        self.exit = False
        self.restart = False
        self.upgrade = False
        self.reboot = False
        self.shutdown = False
        self.netconnect = FSNetConnect()
        self._logger = logging.getLogger(__name__)

    def on_server_command(self, mgr, event, client):
        command = event.command

        if command == FSCommand.UPGRADE_SERVER:
            self.exit = True
            self.upgrade = True

        if command == FSCommand.RESTART_SERVER:
            self.exit = True
            self.restart = True

        if command == FSCommand.REBOOT_SYSTEM:
            self.exit = True
            self.reboot = True

        if command == FSCommand.SHUTDOWN_SYSTEM:
            self.exit = True
            self.shutdown = True

        if command == FSCommand.NETCONNECT:
            self._logger.debug(event)
            self.netconnect.call_netconnectd_command(event, data=None, client=client)

    def reboot_system(self):
        try:
            FSSystem.run_command("reboot", blocking=True)
        except StandardError, e:
            self._logger.error(e)

    def shutdown_system(self):
        try:
            FSSystem.run_command("shutdown -h now", blocking=True)
        except StandardError, e:
            self._logger.error(e)

    def restart_server(self):
        try:
            FSSystem.run_command("/etc/init.d/fabscanpi-server restart", blocking=True)
        except StandardError, e:
            self._logger.error(e)

    def update_server(self):
         try:
             do_upgrade()
         except StandardError, e:
            self._logger.error(e)

    def run(self):
        self._logger.info("FabScanPi-Server "+str(__version__))

        try:
            injector.provide(FSEventManagerInterface, FSEventManagerSingleton)
            injector.provide_instance(FSWebSocketServerInterface, FSWebSocketServer())
            injector.provide_instance(ConfigInterface, Config(self.config_file, True))
            injector.provide_instance(SettingsInterface, Settings(self.settings_file, True))

            # inject "dynamic" classes
            self.config = injector.get_instance(ConfigInterface)
            FSScannerFactory.injectScannerType(self.config.scanner_type)

            # start server services
            websocket_server = injector.get_instance(FSWebSocketServerInterface)
            websocket_server.start()

            FSScanner().start()

            webserver = FSWebServer()
            webserver.start()

            FSEventManagerSingleton().instance.subscribe(FSEvents.COMMAND, self.on_server_command)

            while not self.exit:
                try:
                    time.sleep(0.3)

                except KeyboardInterrupt:
                    raise

            if self.upgrade:
                self._logger.info("Upgrading FabScanPi Server")
                self.update_server()
                self.restart = True

            if self.restart:
                self._logger.info("Restarting FabScanPi Server")
                self.restart_server()
                self.exit = True

            if self.reboot:
                self._logger.info("Rebooting System")
                self.reboot_system()
                self.exit = True

            if self.shutdown:
                self._logger.info("Shutting down System")
                self.shutdown_system()
                self.exit = True

            self._logger.info("FabScan Server Exit. Bye!")
            os._exit(1)

        except (KeyboardInterrupt, SystemExit):
            sys.exit(0)
