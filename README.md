# Portal 1 utility scripts
This is a collection of python scripts that I've been using for Portal 1 related stuff. The most important part of this is the [IPC handler python file](ipc_stuff/ipc_handler.py). This can be used to establish a connection to the [spt plugin](https://github.com/YaLTeR/SourcePauseTool) when it is loaded in-game. I will possibly add/change all of this functionality in the near future, this is all very much a work in progress.

## How to establish a connection to spt
First, load the plugin in-game by following the instructions on the spt repo, then type  `y_spt_ipc 1` in the console. Here is an example of how to use the IPC handler:

```python
from ipc_stuff.ipc_handler import IpcHandler
from pprint import pprint  # pretty print

with IpcHandler(log_file_name="console-log-file.log") as h:
    # optional, prevents lots of debug messages
    h.debug = False

    h.send_cmd_and_get_response("sv_cheats 1; setpos 2000 2000 2000")

    # gets some player properties via a direct connection to spt and prints them
    props = [
        "m_vecOrigin",
        "m_vecViewOffset[2]",
        "m_bHeldObjectOnOppositeSideOfPortal"
    ]
    pprint(h.send_cmd_and_get_response("y_spt_ipc_properties 0 " + ' '.join(props))[0])

    # gets the portal locations by reading the console output file
    pprint(h.send_and_await_response_from_console("y_spt_find_portals"))
```
```
{'entity': {'m_bHeldObjectOnOppositeSideOfPortal': 0,
            'm_vecOrigin[0]': 2000.0,
            'm_vecOrigin[1]': 2000.0,
            'm_vecOrigin[2]': 2000.0,
            'm_vecViewOffset[2]': 64.0},
 'exists': True,
 'type': 'ent'}
["SPT: There's a portal with index 47 at -127.96875000 -191.24299622 "
 '182.03125000.',
 "SPT: There's a portal with index 164 at -62.14271545 558.64904785 "
 '272.03125000.']
```
Note that by providing a `log_file_name` when intializing the handler, the console output will be written to that file so the handler can read it, so it may or may not be good practice to clear this after using this handler.

There are a couple of values like the expected response time via ipc and the expected disk write time that may be adjusted; I set them to values that happened to work for me.

## Using the VAG searcher
The VagSearcher class is inherited from the IPC handler, but it provides the additional functionality of trying a vertical angle glitch (VAG) on a set of portals. When you use it, the assumption is that you are crouched and noclipping, otherwise it may not work on weird portal orientations. The way I've been using it has been like this:
```python
from ipc_stuff.vag_searcher import VagSearcher
from time import sleep
import keyboard

with VagSearcher("conlog") as v:
    v.debug = False
    keyboard.on_press_key('o', lambda _: v.close())
    keyboard.on_press_key('i', lambda _: v.try_vag_on_color("orange"))
    while not v.closed:
        sleep(0.1)
```
There are still some edge cases left to sort out - this doesn't seem to work on all portal orientations yet. In addition, since this is so great at finding VAGs, it is also fantastic at crashing your game :p.