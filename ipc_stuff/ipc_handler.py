import json
import socket
import select
import re
import random
from time import sleep
from threading import RLock
from numpy import array as np_array, float32 as np_float32, ndarray as np_ndarray
from time import perf_counter


class IpcHandler:
    HOST = '127.0.0.1'
    PORT = 27182
    RECV_SIZE = 8192
    EXPECTED_RESPONSE_TIME = 0.02  # waits this much before attempting to read response
    EXPECTED_DISK_WRITE_TIME = 0.02  # waits this much before attempting to read from disk
    MAX_FAIL_COUNT = 10
    MAGIC_STR = "magic"
    MAGIC_RE = re.compile(MAGIC_STR + r"(?P<num>\d*)")

    def __debug_print(self, *args, **kwargs) -> None:
        if self.debug:
            print(*args, **kwargs)

    # if log_file_name is None, then log file reading is ignored
    def __init__(self, log_file_name: str = None, debug: bool = True) -> None:
        self.log_file_name = log_file_name
        self.debug = debug
        self.last_magic = None
        self.log_file = None
        self.lock = RLock()
        self.closed = True
        self.saved_line = None

    def __enter__(self):
        with self.lock:
            if not self.closed:
                raise Exception("handler is already connected")
            self.__debug_print("Starting connection...")
            self.cl_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.cl_socket.__enter__()
            self.closed = False
            self.cl_socket.connect((self.HOST, self.PORT))
            self.game_dir = self.send_cmd_and_get_response('y_spt_ipc_gamedir; echo ""')[0]['path']
            if self.log_file_name:
                fail_count = 0
                while True:
                    self.send_cmd_and_get_response("con_logfile " + self.log_file_name + "; echo MAKE THE FILE DAMMIT")
                    sleep(self.EXPECTED_DISK_WRITE_TIME)
                    try:
                        self.log_file = open(self.game_dir + '/' + self.log_file_name, 'rt')
                        self.jump_to_file_end()
                        break
                    except FileNotFoundError:
                        fail_count += 1
                        self.__debug_print("%i failed attempts at creating log file" % fail_count)
                        self.log_file = None  # don't spam with magic strings
                    if fail_count == self.MAX_FAIL_COUNT:
                        raise Exception("Max fail count reached while creating log file")
            self.__debug_print("Connection established")
            self.closed = False
            return self

    def send_cmd_and_get_response(self, cmd: str, expecting_console_response: bool = True) -> list:
        """
        Sends a command to spt, and returns the responses received via ipc if there are any.

        :param cmd: The command to send.
        :param expecting_console_response: Whether or not you expect the cmd to output anything to console. Leaving
            this at the default value should work even if nothing is printed to console.
        :return: Returns a list of any and all responses that spt sent back via spt_ipc commands.
        """
        if self.closed:
            raise Exception("Handler is closed")
        with self.lock:
            self.last_magic = random.randint(1, 1000000)
            # these magic numbers tell us when to stop reading a ipc response and the console log file
            cmd += '; y_spt_ipc_echo %s%i' % (self.MAGIC_STR, self.last_magic)
            if self.log_file and expecting_console_response:
                cmd += '; echo %s%i' % (self.MAGIC_STR, self.last_magic)
            send_str = json.dumps({'type': 'cmd', 'cmd': cmd}) + '\0'
            self.cl_socket.sendall(send_str.encode())
            self.__debug_print('%i sent command "%s"' % (self.last_magic, cmd.replace('"', r'\"')))
            fail_count = 0
            magic_ack = None
            spt_responses = []
            while True:
                if fail_count >= self.MAX_FAIL_COUNT:
                    raise Exception('Max fail count reached while sending command "' + cmd + '"')
                # wait at most EXPECTED time to see if a response exists
                read_valid, _, _ = select.select([self.cl_socket], [], [], self.EXPECTED_RESPONSE_TIME)
                if not read_valid:
                    fail_count += 1
                    self.__debug_print(str(self.last_magic) + " no response yet")
                    continue  # no response yet, wait again
                self.__debug_print(str(self.last_magic) + " response received")
                response = self.cl_socket.recv(self.RECV_SIZE)
                for msg in response.split(b'\x00'):
                    if not msg:
                        continue  # split gives an empty string since message ends on null separator
                    j = json.loads(msg.decode())
                    # TODO - I'm now using magic echo instead of the built-in ack, but maybe I should switch back?
                    if j['type'] == 'ack':
                        continue  # I don't actually care about this ack, the real ack I want is the one from y_ipc_echo
                    elif j['type'] == 'echo':
                        magic_match = self.MAGIC_RE.match(j['text'])
                        if magic_match:
                            magic_ack = int(magic_match.groupdict()['num'])
                            if self.last_magic != magic_ack:
                                print("magic (%i) doesn't match received magic (%i)" % (self.last_magic, magic_ack))
                                magic_ack = None
                            else:
                                self.__debug_print(str(self.last_magic) + " got ack through ipc")
                        else:
                            spt_responses.append(j)  # user sent an ipc_echo cmd
                    else:
                        spt_responses.append(j)
                if magic_ack:
                    break
                self.__debug_print(str(self.last_magic) + " didn't get ack yet, awaiting response")
            # If we're not gonna get a console response, then in the case where the user reads from the log file we
            # don't want the handler to get stuck waiting for the magic str.
            if not expecting_console_response:
                self.last_magic = None
            return spt_responses

    def jump_to_file_end(self) -> None:
        """Updates the file pointer to point to the end of the log file."""
        if not self.log_file:
            raise Exception("Reading from log file is not enabled")
        self.log_file.seek(0, 2)

    # reads everything from the last time this method or jump was called
    def read_lines_from_log_file(self) -> list:
        if not self.log_file:
            raise Exception("Reading from log file is not enabled")
        response = []
        with self.lock:
            magic_ack = False
            fail_count = 0
            while True:
                if fail_count >= self.MAX_FAIL_COUNT:
                    raise Exception("Max fail count reached while reading from file")
                sleep(self.EXPECTED_DISK_WRITE_TIME)
                while True:
                    if self.saved_line:
                        line = self.saved_line
                        self.saved_line = None
                    else:
                        line = next(self.log_file, None)
                    if line is None:  # EOF
                        break
                    if line == '' or line.isspace():
                        continue
                    line = line.replace('\n', '')
                    m = re.search(self.MAGIC_RE, line)
                    if m:
                        magic_ack = int(m.groupdict()['num'])
                        if not self.last_magic or self.last_magic != magic_ack:
                            self.__debug_print('ignoring magic %i in log file, (expecting %s)'
                                               % (magic_ack, str(self.last_magic)))
                            magic_ack = None
                        else:
                            self.__debug_print("%i got ack through log file" % magic_ack)
                        # Cut out the magic stuff, this will not be visible to the user. We might get something like
                        # magic001 magic002 on the same line because newlines are drunk in source, so save the part
                        # after the magic match for later, (possibly even for when this method gets called next).
                        sp = m.span()
                        line, self.saved_line = line[:sp[0]], line[sp[1]:]
                    if not (line == '' or line.isspace()):
                        response.append(line)
                    if magic_ack:
                        break
                # if we got the ack or we're not expecting one and reached EOF, we're done
                if magic_ack or (not self.last_magic and line is None):
                    break
                self.__debug_print(str(self.last_magic) + "didn't get magic number in file yet, waiting")
                fail_count += 1
            self.last_magic = None
            return response

    def close(self) -> None:
        self.__exit__()

    def send_and_await_response_from_console(self, cmd: str) -> list:
        """Sends a command to spt, then reads any and all console output."""
        with self.lock:
            self.jump_to_file_end()
            self.send_cmd_and_get_response(cmd)
            return self.read_lines_from_log_file()

    @staticmethod
    def get_vec_as_arr(props: dict, prop_name: str) -> np_ndarray:
        return np_array((
            props[prop_name + "[0]"],
            props[prop_name + "[1]"],
            props[prop_name + "[2]"]
        ), dtype=np_float32)

    def __exit__(self, *args) -> None:
        if self.closed:
            return
        self.closed = True
        self.__debug_print("exiting, args: " + str(args))
        self.cl_socket.__exit__()
        self.log_file.close()
