# -*- coding: utf-8 -*-

"""This file contains the Python Class wrapper the DAQ viewer controller
which contains both the wrapper for the PulseBlaster and the FastComTec"""

from .pulseblaster import PulseBlaster
from .mcs8_wrapper import MCS8


class PulsedController:
    def __init__(self):
        self.pulseblaster = None
        self.counter = None

    def init_pulseblaster(
        self,
        clock: int = 500,
    ):
        self.pulseblaster = PulseBlaster(clock)

    def init_counter(
        self,
        device: int = 0,
        dll_path: str = "C:\Windows\System32\DMCS6.dll",
        min_binwidth: float = 200e-12,
        max_sweep_length=6.8,  # it can go up to 8.3 days
        trigger_safety: float = 0,
    ):
        self.counter = MCS8(
            device, dll_path, min_binwidth, max_sweep_length, trigger_safety
        )
        try:
            self.counter.get_status()
        except:
            raise ConnectionError("Cannot connect to FastComTec")
