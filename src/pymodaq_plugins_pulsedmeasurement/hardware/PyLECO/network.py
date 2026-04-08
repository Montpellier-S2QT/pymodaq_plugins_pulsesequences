import json
import threading
import time
from enum import Enum
from queue import Empty, Queue
from typing import Any, Optional, Tuple, Union

import zmq
from zmq import NOBLOCK, ZMQError

from utils import IntUtils


class JSONRPCMessage:
    '''
        Builds JSON-RPC Messages
    '''

    _data : dict = {}

    def __init__(self, *args, **kwargs):
        raise NotImplementedError("This class cannot be instantiated using its constructor.")


    def is_error(self) -> bool:
        return 'error' in self._data

    def is_response(self) -> bool:
        return 'result' in self._data


    def is_request(self) -> bool:
        return 'method' in self._data

    def error(self) -> Tuple[int, str]:
        return (self._data['error']['code'], self._data['error']['message']) if self.is_error() else (0, '')

    def to_json(self) -> str:
        return json.dumps(self._data)

    def to_dict(self) -> dict:
        return self._data.copy()

    def to_response(self, result : Any = None) -> 'JSONRPCMessage':
        return JSONRPCMessage.build_response(self._data['id'], result)

    @staticmethod
    def build_request(method_name : Union[str, Enum], **kwargs) -> 'JSONRPCMessage':
        json_rpc_message = JSONRPCMessage.__new__(JSONRPCMessage)
        
        json_rpc_message._data =  {
            "id" : IntUtils.next(),
            "method": str(method_name),
            "jsonrpc": "2.0",
            "params" : {
                **kwargs
            }
        }
        return json_rpc_message


    @staticmethod
    def build_error(code : int, message : str) -> 'JSONRPCMessage':
        json_rpc_message = JSONRPCMessage.__new__(JSONRPCMessage)
        
        json_rpc_message._data =  {
            "id" : None,
            "jsonrpc": "2.0",
            "error" : {
                "code" : code,
                "message" : message 
            }
        }

        return json_rpc_message

    @staticmethod
    def build_response(id_ : int, result : Any) -> 'JSONRPCMessage':
        json_rpc_message = JSONRPCMessage.__new__(JSONRPCMessage)
        
        json_rpc_message._data =  {
            "id" : id_,
            "jsonrpc": "2.0",
            "result" : result
        }

        return json_rpc_message

    @staticmethod
    def from_json(jstr : str) -> 'JSONRPCMessage':
        json_rpc_message = JSONRPCMessage.__new__(JSONRPCMessage)
        json_rpc_message._data = json.loads(jstr)

        return json_rpc_message

class RPCMethod(Enum):
    '''
        A class to represent common LECO method names for JSON-RPC:
            - SIGNIN: the signin method
            - SIGNOUT: the signout method

    '''
    # common payloads
    SIGNIN = "sign_in"
    SIGNOUT = "sign_out"
    SET_REMOTE_NAME = "set_remote_name"
    PONG = "pong"
    DISCOVER = "rpc.discover"
    GET_SETTINGS = "get_settings"

    # actuator specific
    MOVE_ABS = "move_abs"
    MOVE_REL = "move_rel"
    MOVE_HOME = "move_home"
    SET_MOVE_DONE = "set_move_done"
    STOP_MOTION = "stop_motion"
    SEND_POSITION = "send_position"
    GET_ACTUATOR_VALUE = "get_actuator_value"
    SET_UNITS = "set_units"
    SET_POSITION = "set_position"
    
    #viewer specific
    SEND_DATA_GRAB = "send_data_grab"
    SEND_DATA_SNAP = "send_data_snap"
    STOP_GRAB = "stop_grab"
    SET_DATA = "set_data"



    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:
        return self.value

    def to_jsonrpc(self, **kwargs) -> JSONRPCMessage:
        # TODO: Pass str(self) and change JSONRPC to accept
        # TODO: string only
        return JSONRPCMessage.build_request(self, **kwargs)

    def to_json(self, **kwargs) -> str:
        return self.to_jsonrpc(**kwargs).to_json()

    def to_dict(self, **kwargs) -> dict:
        return self.to_jsonrpc(**kwargs).to_dict()


class LECOTrame:
    '''

    '''
    version         : bytes              = b'\x00'
    receiver        : str 
    sender          : str
    conversation_id : int
    message_id      : int
    message_type    : int                = 1
    payload         : bytes 
    remaining       : Union[bytes, None]

    def __init__(self,
            receiver        : str, 
            sender          : str,
            payload         : Union[None, str, bytes] = None,
            conversation_id : Union[None, int] = None,
            message_id      : Union[None, int] = None):

        self.receiver = receiver
        self.sender =   sender

        self.payload = payload.encode() if isinstance(payload, str)   else \
                       payload          if isinstance(payload, bytes) else \
                       bytes()

        self.message_id = message_id if message_id else 0
        self.conversation_id = conversation_id if conversation_id else IntUtils.random16bytes()
        

    def to_bytes(self) -> list[bytes]:
    
        header = self.conversation_id.to_bytes(16, byteorder="big")
        header+= self.message_id.to_bytes(3, byteorder="big")
        header+= self.message_type.to_bytes(1, byteorder="big")

        payload = []
        if self.payload:
            payload = [self.payload]

        return [self.version, self.receiver.encode(), self.sender.encode(), header] + payload

    @staticmethod
    def from_bytes(raw : list[bytes]) -> 'LECOTrame':
        trame = LECOTrame.__new__(LECOTrame)
        trame.version = raw[0]
        trame.receiver = raw[1].decode()
        trame.sender = raw[2].decode()

        header = raw[3]

        trame.conversation_id = int.from_bytes(header[ 0:16], byteorder='big')
        trame.message_id      = int.from_bytes(header[16:19], byteorder='big')
        trame.message_type    = int.from_bytes(header[19:20], byteorder='big')

        trame.payload = raw[4]

        if len(raw) > 5:
            trame.remaining = raw[5]

        return trame

    def to_response(self, receiver : Optional[str] = None, result : Any = None) -> 'LECOTrame':
        if not receiver:
            receiver = self.receiver
        payload = JSONRPCMessage.from_json(self.payload.decode()).to_response(result).to_json()
        return LECOTrame(self.sender, receiver, payload, self.conversation_id, self.message_id) 

    def to_error(self, code : int, message : str, receiver : Optional[str] = None) -> 'LECOTrame':
        if not receiver:
            receiver = self.receiver
        payload = JSONRPCMessage.build_error(code, message).to_json()
        return LECOTrame(self.sender, receiver, payload, self.conversation_id, self.message_id) 

    def __str__(self) -> str:
        payload = ''
        try:
            payload = self.payload.decode()
        except:
            payload = self.payload.hex()

        return f'[ v{self.version.hex().zfill(2)} |' \
               f' "{self.sender}" -> "{self.receiver}" ||' \
               f' 0x{self.conversation_id.to_bytes(16).hex().zfill(32)} |' \
               f' 0x{self.message_id.to_bytes(3).hex().zfill(6)} |' \
               f' {self.message_type} ||' \
               f' {payload}' \
               f' + {str(self.remaining)}' if self.remaining else '' \
            ']'

class Communicator:
    def __run(self, send_queue : Queue, receive_queue : Queue, protocol = 'tcp', host = 'localhost', port = '12300'):
        socket = zmq.Context.instance().socket(zmq.DEALER) # Could be zmq.REQ if synchronous mode
        socket.connect(f"{protocol}://{host}:{port}")
        while not self.__socket_thread_stop_event.is_set():
            try:
                message = send_queue.get_nowait()
                socket.send_multipart(message)
            except Empty:
                pass

            try:
                message = socket.recv_multipart(flags=NOBLOCK)
                receive_queue.put(message)
            except ZMQError:
                pass
            time.sleep(0.01)

        socket.close()

    def __init__(self, name : str, protocol = 'tcp', host = 'localhost', port = '12300'):
        self._fullname = name
        self._protocol = protocol
        self._name = name
        self._host = host
        self._port = port
        self._receiver = ''
        
        self._send_queue : Queue = Queue()
        self._receive_queue : Queue = Queue()

        self.__socket_thread_stop_event : threading.Event = threading.Event()
        self.__socket_thread : threading.Thread = threading.Thread(target=self.__run, args=(self._send_queue, self._receive_queue, protocol, host, port))
        self.__socket_thread.start()

        

    def stop(self):
        self.signout()
        self.__socket_thread_stop_event.set()
        self.__socket_thread.join()
    
    def signin(self) -> int:
        payload = RPCMethod.SIGNIN.to_dict()
        self.send(LECOTrame("COORDINATOR", self._fullname, json.dumps(payload)))
        return payload['id']

    def send(self, msg : LECOTrame):
        self._send_queue.put(msg.to_bytes())

    def recv(self, timeout=None) -> Union[list[bytes], None]:
        received = None
        try:
            received = self._receive_queue.get(timeout=timeout)
        except Empty:
            pass
        return received

    def ask(self, receiver : str, payload) -> Tuple[str, JSONRPCMessage]:
        msg = LECOTrame(receiver, self._fullname, payload)
        self.send(msg)
        data = self.recv()
        if data is not None:
            rsp = LECOTrame.from_bytes(data)
            return rsp.sender, JSONRPCMessage.from_json(rsp.payload.decode())
        return '', JSONRPCMessage.from_json("{}")

    def set_units(self, units : str):
        trame = LECOTrame(self._receiver, self._fullname, RPCMethod.SET_UNITS.to_json(units=units))
        self.send(trame)

    def send_position(self, data : dict):
        trame = LECOTrame(self._receiver, self._fullname, RPCMethod.SEND_POSITION.to_json(data=data))
        self.send(trame)
    
    def set_data(self, data : dict):
        trame = LECOTrame(self._receiver, self._fullname, RPCMethod.SET_DATA.to_json(data=data))
        self.send(trame)
   
    def send_grab_data(self, data : dict):
        trame = LECOTrame(self._receiver, self._fullname, RPCMethod.SET_DATA.to_json(data=data))
        self.send(trame)
    
    def set_move_done(self, data : dict):
        trame = LECOTrame(self._receiver, self._fullname, RPCMethod.SET_MOVE_DONE.to_json(data=data))
        self.send(trame)

    def set_remote_name(self, receiver : str):
        self._receiver = receiver

    def set_fullname(self, fullname : str):
        self._fullname = fullname

    def signout(self) -> Union[list[bytes], None]:
        self.send(LECOTrame("COORDINATOR", self._fullname, RPCMethod.SIGNOUT.to_json()))
        return self.recv(timeout=5)
