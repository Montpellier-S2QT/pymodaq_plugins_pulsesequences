import signal


class IntUtils:
    '''
        Class to provide some utilities about integer:
            * random16bytes(): gives a randomly generated 16 Bytes integer
            * next(): gives the next integer (starts at 1)
    '''
    __counter : int = 0

    @staticmethod
    def random16bytes() -> int:
        from secrets import token_bytes
        return int.from_bytes(token_bytes(16), byteorder='big')


    @staticmethod
    def current() -> int:
        return IntUtils.__counter
        
    @staticmethod
    def next() -> int:
        IntUtils.__counter+= 1
        return IntUtils.__counter


class ExitFlag:
    '''
        A way to handle proper termination with CTRL+C
        by checking a flag
    '''
    def __init__(self):
        self._state = True

    def __enter__(self):
        self._state = False
        signal.signal(signal.SIGINT, self._set_state)
        return self

    def __exit__(self, _type, _value, _tb):
        signal.signal(signal.SIGINT, signal.SIG_DFL)

    def _set_state(self, _sig, _frame):
        self._state = True

    def is_set(self) -> bool:
        '''
            Check if the flag was set, i.e. if the signal
            was triggered
        '''
        return self._state


