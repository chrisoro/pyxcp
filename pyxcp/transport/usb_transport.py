#!/usr/bin/env python
# -*- coding: utf-8 -*-
import struct
import threading
from array import array
from collections import deque
from pyxcp.transport.base import BaseTransport
from time import perf_counter
from time import sleep
from time import time

import usb.core
import usb.util

RECV_SIZE = 16384


class Usb(BaseTransport):
    """"""

    PARAMETER_MAP = {
        #                            Type    Req'd   Default
        "serial_number": (str, True, ""),
        "configuration_number": (int, True, 1),
        "interface_number": (int, True, 2),
        "command_endpoint_number": (int, True, 0),
        "reply_endpoint_number": (int, True, 1),
    }
    HEADER = struct.Struct("<2H")
    HEADER_SIZE = HEADER.size

    def __init__(self, config=None):
        super(Usb, self).__init__(config)
        self.loadConfig(config)
        self.serial_number = self.config.get("serial_number").strip()
        self.configuration_number = self.config.get("configuration_number")
        self.interface_number = self.config.get("interface_number")
        self.command_endpoint_number = self.config.get("command_endpoint_number")
        self.reply_endpoint_number = self.config.get("reply_endpoint_number")
        self.device = None

        self.status = 0

        self._packet_listener = threading.Thread(
            target=self._packet_listen,
            args=(),
            kwargs={},
        )
        self._packets = deque()

    def connect(self):
        for device in usb.core.find(find_all=True):
            try:
                if device.serial_number.strip().strip("\0").lower() == self.serial_number.lower():
                    self.device = device
                    break
                else:
                    print(
                        device.serial_number.strip().strip("\0").lower(),
                        self.serial_number.lower(),
                    )
            except BaseException:
                continue
        else:
            raise Exception("Device with serial {} not found".format(self.serial_number))

        current_configuration = self.device.get_active_configuration()
        if current_configuration.bConfigurationValue != self.configuration_number:
            self.device.set_configuration(self.configuration_number)
        cfg = self.device.get_active_configuration()

        interface = cfg[(self.interface_number, 0)]

        self.command_endpoint = interface[self.command_endpoint_number]
        self.reply_endpoint = interface[self.reply_endpoint_number]

        self.startListener()
        self.status = 1  # connected

    def startListener(self):
        self._packet_listener.start()
        self.listener.start()

    def close(self):
        """Close the transport-layer connection and event-loop."""
        self.finishListener()
        if self.listener.is_alive():
            self.listener.join()
        if self._packet_listener.is_alive():
            self._packet_listener.join()
        self.closeConnection()

    def _packet_listen(self):

        close_event_set = self.closeEvent.isSet

        high_resolution_time = self.perf_counter_origin < 0
        timestamp_origin = self.timestamp_origin
        perf_counter_origin = self.perf_counter_origin

        _packets = self._packets
        read = self.reply_endpoint.read

        buffer = array("B", bytes(RECV_SIZE))
        buffer_view = memoryview(buffer)

        while True:
            try:
                if close_event_set():
                    return

                try:
                    if high_resolution_time:
                        recv_timestamp = time()
                    else:
                        recv_timestamp = timestamp_origin + perf_counter() - perf_counter_origin
                    read_count = read(buffer, 100)  # 100ms timeout
                    if read_count != RECV_SIZE:
                        _packets.append((buffer_view[:read_count].tobytes(), recv_timestamp))
                    else:
                        _packets.append((buffer.tobytes(), recv_timestamp))
                except BaseException:
                    # print(format_exc())
                    sleep(0.001)
                    continue

            except BaseException:
                self.status = 0  # disconnected
                break

    def listen(self):
        HEADER_UNPACK_FROM = self.HEADER.unpack_from
        HEADER_SIZE = self.HEADER_SIZE

        popleft = self._packets.popleft

        processResponse = self.processResponse
        close_event_set = self.closeEvent.isSet

        _packets = self._packets
        length, counter = None, None

        data = bytearray(b"")

        last_sleep = perf_counter()

        while True:
            if close_event_set():
                return

            count = len(_packets)

            if not count:
                sleep(0.001)
                last_sleep = perf_counter()
                continue

            for _ in range(count):
                bts, timestamp = popleft()

                data += bts
                current_size = len(data)
                current_position = 0

                data_view = memoryview(data)

                while True:
                    if perf_counter() - last_sleep >= 0.005:
                        sleep(0.001)
                        last_sleep = perf_counter()

                    if length is None:
                        if current_size >= HEADER_SIZE:
                            length, counter = HEADER_UNPACK_FROM(data_view, current_position)
                            current_position += HEADER_SIZE
                            current_size -= HEADER_SIZE
                        else:
                            data = data[current_position:]
                            break
                    else:
                        if current_size >= length:
                            response = data_view[current_position : current_position + length]
                            processResponse(response, length, counter, timestamp)

                            current_size -= length
                            current_position += length

                            length = None

                        else:

                            data = data[current_position:]
                            break

    def send(self, frame):
        if self.perf_counter_origin < 0:
            self.pre_send_timestamp = time()
            try:
                self.command_endpoint.write(frame)
            except BaseException:
                # sometimes usb.core.USBError: [Errno 5] Input/Output Error is raised
                # even though the command is send and a reply is received from the device.
                # Ignore this here since a Timeout error will be raised anyway if
                # the device does not respond
                pass
            self.post_send_timestamp = time()
        else:
            pre_send_timestamp = perf_counter()
            try:
                self.command_endpoint.write(frame)
            except BaseException:
                # sometimes usb.core.USBError: [Errno 5] Input/Output Error is raised
                # even though the command is send and a reply is received from the device.
                # Ignore this here since a Timeout error will be raised anyway if
                # the device does not respond
                pass
            post_send_timestamp = perf_counter()
            self.pre_send_timestamp = self.timestamp_origin + pre_send_timestamp - self.perf_counter_origin
            self.post_send_timestamp = self.timestamp_origin + post_send_timestamp - self.perf_counter_origin

    def closeConnection(self):
        if self.device is not None:
            usb.util.dispose_resources(self.device)
