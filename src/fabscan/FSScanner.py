__author__ = "Mario Lukas"
__copyright__ = "Copyright 2017"
__license__ = "GPL v2"
__maintainer__ = "Mario Lukas"
__email__ = "info@mariolukas.de"

import time
import threading
import logging
import multiprocessing

from fabscan.FSVersion import __version__
from fabscan.FSEvents import FSEventManagerInterface, FSEvents
from fabscan.vision.FSMeshlab import FSMeshlabTask
from fabscan.FSSettings import SettingsInterface
from fabscan.FSConfig import ConfigInterface
from fabscan.scanner.interfaces.FSScanProcessor import FSScanProcessorCommand, FSScanProcessorInterface
from fabscan.util.FSInject import inject, singleton
from fabscan.util.FSUpdate import upgrade_is_available, do_upgrade

class FSState(object):
    IDLE = "IDLE"
    SCANNING = "SCANNING"
    SETTINGS = "SETTINGS"
    CALIBRATING = "CALIBRATING"
    UPGRADING = "UPGRADING"

class FSCommand(object):
    SCAN = "SCAN"
    START = "START"
    STOP = "STOP"
    CALIBRATE = "CALIBRATE"
    HARDWARE_TEST_FUNCTION = "HARDWARE_TEST_FUNCTION"
    MESHING = "MESHING"
    COMPLETE = "COMPLETE"
    SCANNER_ERROR = "SCANNER_ERROR"
    UPGRADE_SERVER = "UPGRADE_SERVER"
    RESTART_SERVER = "RESTART_SERVER"
    REBOOT_SYSTEM = "REBOOT_SYSTEM"
    SHUTDOWN_SYSTEM = "SHUTDOWN_SYSTEM"
    CALIBRATION_COMPLETE = "CALIBRATION_COMPLETE"
    NETCONNECT = "NETCONNECT"
    GET_SETTINGS = "GET_SETTINGS"
    UPDATE_SETTINGS = "UPDATE_SETTINGS"
    GET_CONFIG = "GET_CONFIG"
    UPDATE_CONFIG = "UPDATE_CONFIG"


@inject(
        settings=SettingsInterface,
        config=ConfigInterface,
        eventmanager=FSEventManagerInterface,
        scanprocessor=FSScanProcessorInterface
)
class FSScanner(threading.Thread):
    def __init__(self, settings, config, eventmanager, scanprocessor):
        threading.Thread.__init__(self)

        self._logger = logging.getLogger(__name__)
        self.settings = settings
        self.config = config
        self.eventManager = eventmanager.instance
        self.scanProcessor = scanprocessor.instance

        self._state = FSState.IDLE
        self._exit_requested = False
        self.meshingTaskRunning = False

        self._upgrade_available = False
        self._update_version = None

        self.eventManager.subscribe(FSEvents.ON_CLIENT_CONNECTED, self.on_client_connected)
        self.eventManager.subscribe(FSEvents.COMMAND, self.on_command)

        self._logger.info("Scanner initialized...")
        self._logger.info("Number of cpu cores: " + str(multiprocessing.cpu_count()))


    def run(self):

        while not self._exit_requested:
            self.eventManager.handle_event_q()

            time.sleep(0.05)

    def request_exit(self):
        self._exit_requested = True

    def on_command(self, mgr, event, client):

        command = event.command

        ## Start Scan and goto Settings Mode
        if command == FSCommand.SCAN:
            if self._state is FSState.IDLE:
                self.set_state(FSState.SETTINGS)
                self.scanProcessor.tell({FSEvents.COMMAND: FSScanProcessorCommand.SETTINGS_MODE_ON})

        ## Update Settings in Settings Mode
        elif command == FSCommand.UPDATE_SETTINGS:
            if self._state is FSState.SETTINGS:
                self.scanProcessor.tell(
                        {FSEvents.COMMAND: FSScanProcessorCommand.UPDATE_SETTINGS, 'SETTINGS': event.settings}
                )

        elif command == FSCommand.UPDATE_CONFIG:
            self.scanProcessor.tell(
                {FSEvents.COMMAND: FSScanProcessorCommand.UPDATE_CONFIG, 'CONFIG': event.config}
            )

        ## Start Scan Process
        elif command == FSCommand.START:
            if self._state is FSState.SETTINGS:
                self._logger.info("Start command received...")
                self.set_state(FSState.SCANNING)
                self.scanProcessor.tell({FSEvents.COMMAND: FSScanProcessorCommand.START})

        ## Stop Scan Process or Stop Settings Mode
        elif command == FSCommand.STOP:

            if self._state is FSState.SCANNING:
                self.scanProcessor.ask({FSEvents.COMMAND: FSScanProcessorCommand.STOP})

            if self._state is FSState.SETTINGS:
                self._logger.debug("Close Settings")
                self.scanProcessor.tell({FSEvents.COMMAND: FSScanProcessorCommand.SETTINGS_MODE_OFF})

            if self._state is FSState.CALIBRATING:
                self.scanProcessor.ask({FSEvents.COMMAND: FSScanProcessorCommand.STOP_CALIBRATION})

            self.set_state(FSState.IDLE)

        elif command == FSCommand.HARDWARE_TEST_FUNCTION:
            self._logger.debug("Hardware Device Function called...")
            self.scanProcessor.ask({FSEvents.COMMAND: FSScanProcessorCommand.CALL_HARDWARE_TEST_FUNCTION, 'DEVICE_TEST': event.device})

        # Start calibration
        elif command == FSCommand.CALIBRATE:
            self._logger.debug("Calibration started....")
            self.set_state(FSState.CALIBRATING)
            self.scanProcessor.tell({FSEvents.COMMAND: FSScanProcessorCommand.START_CALIBRATION})

        elif command == FSCommand.CALIBRATION_COMPLETE:
            self.set_state(FSState.IDLE)

        # Scan is complete
        elif command == FSCommand.COMPLETE:
            self.set_state(FSState.IDLE)
            self._logger.info("Scan complete")

        # Internal error occured
        elif command == FSCommand.SCANNER_ERROR:
            self._logger.info("Internal Scanner Error.")
            self.set_state(FSState.SETTINGS)

        # Meshing
        elif command == FSCommand.MESHING:
            meshlab_task = FSMeshlabTask(event.scan_id, event.filter, event.format)
            meshlab_task.start()

        # Upgrade server
        elif command == FSCommand.UPGRADE_SERVER:
            if self._upgrade_available:
                self._logger.info("Upgrade server")
                self.set_state(FSState.UPGRADING)

        elif command == FSCommand.GET_CONFIG:
            message = {
                "client": client,
                "config": self.config.todict(self.config)
            }
            self.eventManager.send_client_message(FSEvents.ON_GET_CONFIG, message)

        elif command == FSCommand.GET_SETTINGS:
            message = {
                "client": client,
                "settings": self.settings.todict(self.settings)
            }
            self.eventManager.send_client_message(FSEvents.ON_GET_SETTINGS, message)


    # new client conneted
    def on_client_connected(self, eventManager, event, client):
        try:
            try:
                hardware_info = self.scanProcessor.ask({FSEvents.COMMAND: FSScanProcessorCommand.GET_HARDWARE_INFO})
            except:
                hardware_info = "undefined"

            self._upgrade_available, self._upgrade_version = upgrade_is_available(__version__)
            self._logger.debug("Upgrade available: "+str(self._upgrade_available)+" "+self._upgrade_version)

            message = {
                "client": client,
                "state": self.get_state(),
                "server_version": 'v.'+__version__,
                "firmware_version": str(hardware_info),
                "upgrade": {
                    "available": self._upgrade_available,
                    "version": self._upgrade_version

                }
            }

            eventManager.send_client_message(FSEvents.ON_CLIENT_INIT, message)
            self.scanProcessor.tell({FSEvents.COMMAND: FSScanProcessorCommand.NOTIFY_HARDWARE_STATE})
            self.scanProcessor.tell({FSEvents.COMMAND: FSScanProcessorCommand.NOTIFY_IF_NOT_CALIBRATED})

        except StandardError, e:
            self._logger.error(e)

    def set_state(self, state):
        self._state = state
        self.eventManager.broadcast_client_message(FSEvents.ON_STATE_CHANGED, {'state': state})

    def get_state(self):
        return self._state