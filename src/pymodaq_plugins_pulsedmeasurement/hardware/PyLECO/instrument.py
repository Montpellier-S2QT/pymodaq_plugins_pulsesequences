import threading
import time
from enum import StrEnum, auto
from typing import Iterable, Optional, Union

#from driver import (ActuatorDriver, Bounds, DetectorDriver,
#                    Dimension, SLMDriver)

from pymodaq_plugins_pulsedmeasurement.extensions.pulsed_measurement_extension import PulsedMeasurementExtension

from network import Communicator, JSONRPCMessage, LECOTrame, RPCMethod
from utils import ExitFlag


class Axis:
    '''

        Representation of an axis. Its constructor is not implemented so
        it should be instanciated with the `from_*` static methods:
        
        - from_data(data, units) that takes a `data` array which is a list
          of points alongside the axis (int ascending order) and an optional
          `unit` parameter
        
        - from_size(size, units) that takes a `size` argument which is the number
          of points alongside the axis to generate. Points will be generated from 
          0 to `size` - 1. `unit` is an optional parameter.
        
        - It also provides a `to_dict` method returning the dictionnary 
          representation of the object e.g.: {'data' : [0,1,3,5], 'units' : 'mm'}

    '''


    def __init__(self):        
        self.data  : list[float] = []
        self.units : str = ''
        self.label : str = ''

        raise NotImplementedError

    @staticmethod
    def from_data(data : Iterable[float], units : Optional[str] = None, label : Optional[str] = None) -> 'Axis':
        axis = Axis.__new__(Axis)
        axis.data = list(data)
        if units:
            axis.units = units
        if label:
            axis.label = label
        return axis
        
    @staticmethod
    def from_size(len_ : int, units :  Optional[str] = None, label : Optional[str] = None) -> 'Axis':
        return Axis.from_data([i for i in range(len_)], units, label)

    def to_dict(self) -> dict:
        return vars(self)

    def __len__(self) -> int:
        return len(self.data)

class LECOState(StrEnum):
    SIGNED_IN = auto()
    SIGNED_OUT = auto()
    REMOTE_NAME_SET = auto()

    GRABBING = auto() # Detector only State


class JSONDetector:
    def __init_states_and_transitions(self):
        # stuff to do when entering/exiting the state:
        #  { new-state : action }
        self.background_state_actions = {
            LECOState.GRABBING : self._start_grabbing
        }
        self.post_state_actions = {
            LECOState.GRABBING : self._stop_grabbing
        }

        # Represent a state transition matrix : 
        # { current_state : { leco-method : (new-state, action)}}
        # so transitions[current_state][leco-method] gives the new-state
        # and the action to execute
        self.transitions = {
            LECOState.SIGNED_OUT : {
                RPCMethod.SIGNIN          : (LECOState.SIGNED_IN,       self._on_signin),
                RPCMethod.PONG            : (LECOState.SIGNED_OUT,      self._on_pong),
            },
            LECOState.SIGNED_IN : {
                RPCMethod.SIGNOUT         : (LECOState.SIGNED_OUT,      self._on_signout),
                RPCMethod.SET_REMOTE_NAME : (LECOState.REMOTE_NAME_SET, self._on_set_receiver),
                RPCMethod.PONG            : (LECOState.SIGNED_IN,       self._on_pong),
            },
            LECOState.REMOTE_NAME_SET : {
                RPCMethod.SIGNOUT         : (LECOState.SIGNED_OUT,      self._on_signout),
                RPCMethod.SET_REMOTE_NAME : (LECOState.REMOTE_NAME_SET, self._on_set_receiver),
                RPCMethod.SEND_DATA_GRAB  : (LECOState.GRABBING,        self._on_start_grab),
                RPCMethod.SEND_DATA_SNAP  : (LECOState.REMOTE_NAME_SET, self._on_snap_data),
                RPCMethod.STOP_GRAB       : (LECOState.REMOTE_NAME_SET, self._on_stop_grab),
                RPCMethod.DISCOVER        : (LECOState.REMOTE_NAME_SET, self._on_discover),
                RPCMethod.GET_SETTINGS    : (LECOState.REMOTE_NAME_SET, self._on_get_settings),
                RPCMethod.PONG            : (LECOState.REMOTE_NAME_SET, self._on_pong),
            },
            LECOState.GRABBING : {
                RPCMethod.STOP_GRAB       : (LECOState.REMOTE_NAME_SET, self._on_stop_grab),
                RPCMethod.SEND_DATA_SNAP  : (LECOState.REMOTE_NAME_SET, self._on_snap_data),
                RPCMethod.SET_REMOTE_NAME : (LECOState.REMOTE_NAME_SET, self._on_set_receiver),
                RPCMethod.PONG            : (LECOState.GRABBING,        self._on_pong),
            }
        }

    def __init__(self, name : str, dimension : Dimension, x_axis_len : int = 0, y_axis_len : int = 0,
        axes : list[Axis] = [], labels : list[str] = [], channels : int = 1, protocol : str = 'tcp',
        host : str = 'localhost', port : str = '12300'
    ):        
        self.__init_states_and_transitions()
        if axes:
            if x_axis_len == 0 and dimension >= 1 and len(axes) >= 1:
                x_axis_len = len(axes[0])
            if y_axis_len == 0 and dimension >= 2 and len(axes) >= 2:
                y_axis_len = len(axes[1])

        self._name = name
        self._driver = PulsedMeasurementExtension
            DetectorDriver(dimension=dimension, x_axis_len=x_axis_len, y_axis_len=y_axis_len, labels=labels, channels=channels)

        self._axes = axes
        self._communicator = Communicator(name, protocol=protocol, host=host, port=port)
        self.state = LECOState.SIGNED_OUT
        self.signin_id : Union[int, None] = None


    def run(self):
        now = time.time()
        self.signin_id = self._communicator.signin()
        with ExitFlag() as ef:
            delta = time.time() - now
            while not ef.is_set() and delta < 6000:
                delta = time.time() - now
                trame = self.wait_for_trame(timeout=0.1)
                if trame:
                    self.handle_trame(trame)
        self._communicator.stop()

    def wait_for_trame(self, timeout=None) -> Union[LECOTrame, None]:
        trame = self._communicator.recv(timeout=timeout)
        if trame:
            return LECOTrame.from_bytes(trame)
        return None

    def handle_trame(self, trame : LECOTrame):
        payload = trame.payload.decode()
        json_rpc_msg = JSONRPCMessage.from_json(payload)
        if json_rpc_msg.is_error():
            print(json_rpc_msg.error())
        else:
            # If it's a response, we check if it's from SIGNIN
            # otherwise we don't need to handle it
            if json_rpc_msg.is_response() and json_rpc_msg.to_dict()['id'] == self.signin_id:
                method = RPCMethod.SIGNIN
            else:
                try:
                    method = RPCMethod(json_rpc_msg.to_dict()['method'])
                except (KeyError, ValueError):
                    method = RPCMethod.UNKNOWN
                
            if method in self.transitions[self.state]:
                new_state, on_transition_action = self.transitions[self.state][method]
                print(f"Current State: {self.state}, Received Message: {method.name}, Transitioning to {new_state}")

                new_state_is_different = new_state != self.state

                # if the current state has a post state action defined
                # it is executed 
                if self.state in self.post_state_actions:
                    self.post_state_actions[self.state]()
                
                #  action to execute during transition
                on_transition_action(trame)  

                # if the new state has an action it is executed
                # (probably in a new thread, otherwise it would be a transition action)
                if new_state in self.background_state_actions:
                    self.background_state_actions[new_state]()
                self.state = new_state
                # If new state has an entry action, perform it
            else:
                if json_rpc_msg.is_request():
                    self._communicator.send(trame.to_error(-100, "Request received is invalid in current state."))
                print(f"Current State: {self.state}, Received Message: {method.name}")
    # === background actions ===
    def _start_grabbing(self):
        def __grab_and_send(self):
            while not self._grabbing_thread_stop_event.is_set():
                self._communicator.set_data({
                    'data'   : self._driver.acquire(),
                    'axes'   : [axis.to_dict() for axis in self._axes],
                    'labels' : self._driver.labels,
                    'multichannel' : self._driver.is_multichannel()
                })
                time.sleep(0.04)

        if not (hasattr(self, '_grabbing_thread') and self._grabbing_thread.is_alive()):
            self._grabbing_thread_stop_event : threading.Event = threading.Event()
            self._grabbing_thread : threading.Thread = threading.Thread(target=__grab_and_send, args=(self,))
            self._grabbing_thread.start()

    # ===  cleaning actions  ===
    def _stop_grabbing(self):
        if hasattr(self, '_grabbing_thread'):
            self._grabbing_thread_stop_event.set()
            self._grabbing_thread.join()

    # === transition actions ===
    def _on_signin(self, trame : LECOTrame):
        self._communicator.set_fullname(f'{trame.sender.split(".")[0]}.{self._name}')
        #self._communicator.send(trame.to_response())

    def _on_signout(self, trame : LECOTrame):
        pass

    def _on_set_receiver(self, trame : LECOTrame):
        message = JSONRPCMessage.from_json(trame.payload.decode()).to_dict()
        self._communicator.set_remote_name(message["params"]["name"])
        self._communicator.send(trame.to_response())

    def _on_start_grab(self, trame : LECOTrame):
        self._communicator.send(trame.to_response())

    def _on_snap_data(self, trame : LECOTrame):
        self._communicator.send(trame.to_response())
        self._communicator.set_data({
            'data'   : self._driver.acquire(), 
            'axes'   : [axis.to_dict() for axis in self._axes],
            'labels' : self._driver.labels,
            'multichannel' : self._driver.is_multichannel()
        })

    def _on_stop_grab(self, trame : LECOTrame):
        self._communicator.send(trame.to_response())

    def _on_discover(self, trame : LECOTrame):
        raise NotImplementedError

    def _on_get_settings(self, trame : LECOTrame):
        settings : dict = {}
        self._communicator.send(trame.to_response(result=settings))

    def _on_pong(self, trame : LECOTrame):
        self._communicator.send(trame.to_response())

