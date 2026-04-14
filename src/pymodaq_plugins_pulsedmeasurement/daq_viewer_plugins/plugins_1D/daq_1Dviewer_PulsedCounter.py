import numpy as np
import time
import matplotlib.pyplot as plt

from pymodaq_utils.utils import ThreadCommand
from pymodaq_data.data import DataToExport, Axis
from pymodaq_gui.parameter import Parameter

from pymodaq.control_modules.viewer_utility_classes import (
    DAQ_Viewer_base,
    comon_parameters,
    main,
)
from pymodaq.utils.data import DataFromPlugins
from pymodaq_plugins_pulsedmeasurement.hardware.pulsed_controller import (
    PulsedController,
)
from pymodaq_plugins_pulsedmeasurement.hardware._spinapi import SpinAPI


class DAQ_1DViewer_PulsedCounter(DAQ_Viewer_base):
    """Plugin for the general pusle sequence measurements that controls:
        - SpinCore PulseBlaster USB ESR-Pro
        - FastComTec MCS8
    This object inherits all functionality to communicate with PyMoDAQ Module
    through inheritance via DAQ_Move_base.
    It then implements the particular communication with the instrument.

    Attributes:
    -----------
    controller: PulsedController
        Instance of the class defined to communicate with both devices.

    controller.pulseblaster: PulseBlaster
        Instance of the class defined to communicate with the SpinCore device.

    controller.counter: MCS8
        Instance of the class defined to communicate with the FastComTec device.
    """

    params = comon_parameters + [
        {
            "title": "Sequence Name",
            "name": "name",
            "type": "str",
            "value": "Template",
        },
        {
            "title": "Sequence Length (ns)",
            "name": "length",
            "type": "float",
            "value": 5e3,
        },
        {
            "title": "Final Wait (ns)",
            "name": "final_wait",
            "type": "float",
            "value": 1e3,
        },
        {
            "title": "Board Number",
            "name": "board_num",
            "type": "int",
            "value": 0,
        },
        {
            "title": "Clock Frequency",
            "name": "clock_freq",
            "type": "list",
            "limits": [500],
        },
    ]

    hardware_averaging = True

    def ini_attributes(self):
        self.controller: PulsedController = None
        self.x_axis = None
        self.iteration_count: int = None

    def commit_settings(self, param: Parameter):
        """Apply the consequences of a change of value in the detector settings.
        When a parameter change also changes the total length of the pulse sequence we update
        this value in the FastComTec device.
        When a parameter change also changes the timestamps of the x axis of the detector
        we update the x axis accordingly.

        Parameters
        ----------
        param: Parameter
            A given parameter (within detector_settings) whose value has been changed by the user
        """
        if param.name() == "board_num":
            self.controller.pulseblaster.board_number = param.value()

    def ini_detector(self, controller=None):
        """Detector communication initialization

        Parameters
        ----------
        controller: (object)
            custom object of a PyMoDAQ plugin (Slave case). None if only one actuator/detector by controller
            (Master case)

        Returns
        -------
        info: str
        initialized: bool
            False if initialization failed otherwise True
        """
        if self.is_master:
            self.controller = PulsedController()
            try:
                self.controller.init_counter()
                initialized = True
            except:
                initialized = False
                self.emit_status(
                    ThreadCommand(
                        "Update_Status",
                        ["Cannot connect to fastcomtec"],
                    )
                )
            try:
                self.controller.init_pulseblaster(
                    self.settings.child("clock_freq").value(),
                )
                initialized = True
            except:
                initialized = False
                self.emit_status(
                    ThreadCommand(
                        "Update_Status",
                        ["Cannot connect to pulseblaster"],
                    )
                )
        else:
            self.controller = controller
            initialized = True

        self.iteration_count = 0  # reinitialize the iteration counter
        self.controller.counter.set_length(
            (
                self.settings.child("length").value()
                - self.settings.child("final_wait").value()
            )
            * 1e-9
        )
        data_x_axis = self.controller.counter.get_timestamps()
        self.x_axis = Axis(data=data_x_axis, label="Time", units="s", index=0)

        self.dte_signal_temp.emit(
            DataToExport(
                name=f"temp_{self.settings.child('name').value()}",
                data=[
                    DataFromPlugins(
                        name=self.settings.child("name").value(),
                        data=[np.zeros_like(data_x_axis)],
                        dim="Data1D",
                        labels=[f"Events ({self.iteration_count} sweeps)"],
                        axes=[self.x_axis],
                    )
                ],
            )
        )
        info = "Detector and Viewer Initialized"
        return info, initialized

    def close(self):
        """Terminate the communication protocol"""
        if self.is_master:
            self.controller.counter.stop_measure()
            self.controller.pulseblaster.shutdown()
            self.iteration_count = 0

    def grab_data(self, Naverage=1, **kwargs):
        """Start a grab from the detector

        Parameters
        ----------
        Naverage: int
            Number of hardware averaging (if hardware averaging is possible, self.hardware_averaging should be set to
            True in class preamble and you should code this implementation)
        kwargs: dict
            others optionals arguments
        """
        # Updatefct length and viewer x axis and start the fct measurement on the first iteration
        if self.iteration_count == 0:
            self.controller.counter.set_length(
                (
                    self.settings.child("length").value()
                    - self.settings.child("final_wait").value()
                )
                * 1e-9
            )
            data_x_axis = self.controller.counter.get_timestamps()
            self.x_axis = Axis(data=data_x_axis, label="Time", units="s", index=0)
            self.controller.counter.start_measure()

        self.controller.pulseblaster.reset()
        self.controller.pulseblaster.start()
        time.sleep(self.settings.child("length").value() * 1e-9)
        self.controller.pulseblaster.stop()
        # Get data from FCT
        self.iteration_count += 1
        self.dte_signal.emit(
            DataToExport(
                self.settings.child("name").value(),
                data=[
                    DataFromPlugins(
                        name=self.settings.child("name").value(),
                        data=self.controller.counter.get_data(),
                        dim="Data1D",
                        # labels=[f"Events ({self.iteration_count} sweeps)"],
                        labels=[f"Events"],
                        axes=[self.x_axis],
                    )
                ],
            )
        )
        # If the viewer cannot support the actualisation rate add a sleep time
        # time.sleep(
        #     0.5
        # )

    def stop(self):
        """Stop the current grab hardware wise if necessary"""
        self.iteration_count = 0  # reinitilaize the number of sweeps
        self.controller.counter.stop_measure()
        self.emit_status(
            ThreadCommand("Update_Status", ["FastComTec stopped counting"])
        )
        self.controller.pulseblaster.stop()
        self.emit_status(ThreadCommand("Update_Status", ["Pulse Sequence Stopped"]))


if __name__ == "__main__":
    main(__file__)
