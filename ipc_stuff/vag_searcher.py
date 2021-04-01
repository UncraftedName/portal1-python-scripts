from ipc_handler import IpcHandler
from portal_utils import *
from time import sleep
from numpy import \
    argmax as np_argmax, \
    float32 as np_float32, \
    linalg as np_linalg, \
    nextafter as np_nextafter, \
    abs as np_abs
from math import inf
import re
from enum import Enum


class VagSearcher(IpcHandler):

    class VagSearchResult(Enum):
        SUCCESS = 1
        FAIL = 2
        MAX_ITERATIONS = 3
        WOULD_CAUSE_CRASH = 4

    def try_vag(self, entry_portal: dict, exit_portal: dict) -> VagSearchResult:
        """
        Tries to setpos to the correct location to do a VAG with the specified portals.

        Teleports the player at the entry portal using setpos. Suppose that places the player in front of the entry
        portal. The next iteration will change the setpos command in the smallest significant way possible by only
        moving along the axis for which the entry portal normal has the greatest magnitude. In this example, on the next
        iteration the setpos command will teleport the player further into the portal. This will repeat until either the
        player is not in either of the portal bubbles (which implies an AG has happened), or the player gets
        teleported to the other portal, which implies that an AG is not possible in the spot where the setpos command is
        being tried. The opposite is done if the first setpos command places the player near the exit portal.

        The example above a bit more visually:
        suppose the right portal is the entry portal facing right.
                    V - first setpos command places player here
        <--|      |-->
        The player is closer (and close) to the entry portal, so the next iteration will setpos the player further into
        the hole of the entry portal.


        This approach has a few shortcomings:

        - If the distance between the portals is small, the algorithm could get confused to which portal the player
        teleported to. TODO - trying comparing the player distance to where the AG will teleport them instead?

        - Since this script is fantastic at finding VAGs, it is equally as fantastic at crashing your game.

        - It seems that it in some cases it is possible for a VAG to work in only some parts of a portal. This script
        does not take that into account - it only tries to teleport the player center to the portal center.

        :param entry_portal: A dict gotten with y_spt_ipc_ent for the entry portal.
        :param exit_portal: A dict gotten with y_spt_ipc_ent for the exit portal.
        """

        class SearchResult(Enum):
            NEXT_TO_ENTRY = 1
            NEXT_TO_EXIT = 2
            BEHIND_ENTRY_PLANE = 3

        entry_xyz = self.get_vec_as_arr(entry_portal["entity"], "m_vecOrigin")
        player = self.send_cmd_and_get_response("y_spt_ipc_properties 0 m_fFlags m_bAnimatedEveryTick", False)[0]
        is_crouched = player["entity"]["m_fFlags"] & 2 != 0
        if not is_crouched:
            print("Warning: player is fully crouched, probably won't work for non-vertical entry portals")
        if player["entity"]["m_bAnimatedEveryTick"] != 0:
            print("Warning: player is probably not noclipping")
        it = 0
        player_setpos = np_array(entry_xyz)
        # change z pos so player center is where the portal center is
        player_half_height = 18 if is_crouched else 36
        player_setpos[2] -= player_half_height
        entry_norm = angles_to_vec(self.get_vec_as_arr(entry_portal["entity"], "m_angRotation"))
        # save only component of the portal normal with the largest magnitude, we'll be moving along in that axis
        no_idx = np_argmax(np_abs(entry_norm))
        first_result = None
        while True:
            print('iteration %i' % (it + 1))
            setpos_command = "setpos %f %f %f" % tuple(player_setpos)
            print("trying: " + setpos_command)
            # set expected response to false since the nudge message appears after magic
            self.send_cmd_and_get_response(setpos_command, False)
            if any('spt: nudging entity' in line for line in self.read_lines_from_log_file()):
                print('this vag would normally cause a crash, not possible here')
                return VagSearcher.VagSearchResult.WOULD_CAUSE_CRASH
            # the player position is wacky - it doesn't seem to be valid right away; sleep
            sleep(0.02)
            p_info = self.send_cmd_and_get_response("y_spt_ipc_properties 0 m_vecOrigin m_hPortalEnvironment", False)[0]
            new_player_pos = self.get_vec_as_arr(p_info["entity"], "m_vecOrigin")
            new_player_pos[2] += player_half_height
            print("player pos: %s %s %s" % (str(new_player_pos[0]), str(new_player_pos[1]), str(new_player_pos[2])))
            dist_to_entry = np_linalg.norm(new_player_pos - entry_xyz)

            player_portal_idx = h_to_i(p_info["entity"]["m_hPortalEnvironment"])

            if player_portal_idx == entry_portal["index"]:
                result = SearchResult.NEXT_TO_ENTRY
            elif player_portal_idx == exit_portal["index"]:
                result = SearchResult.NEXT_TO_EXIT
            elif dist_to_entry < 1:
                result = SearchResult.BEHIND_ENTRY_PLANE  # behind portal but didn't teleport
            else:
                print("vag probably worked: " + setpos_command)
                return VagSearcher.VagSearchResult.SUCCESS

            if first_result is None and result != SearchResult.BEHIND_ENTRY_PLANE:
                first_result = result

            if result == SearchResult.NEXT_TO_ENTRY:
                if first_result == SearchResult.NEXT_TO_EXIT:
                    print("no vag found")
                    return VagSearcher.VagSearchResult.FAIL
                print("trying setpos closer to portal")
                player_setpos[no_idx] = np_nextafter(player_setpos[no_idx], entry_norm[no_idx] * -inf, dtype=np_float32)
            elif result == SearchResult.NEXT_TO_EXIT:
                if first_result == SearchResult.NEXT_TO_ENTRY:
                    print("no vag found")
                    return VagSearcher.VagSearchResult.FAIL
                print("trying setpos further from portal")
                player_setpos[no_idx] = np_nextafter(player_setpos[no_idx], entry_norm[no_idx] * inf, dtype=np_float32)
            else:
                print("behind portal plane, trying setpos further from portal")
                player_setpos[no_idx] = np_nextafter(player_setpos[no_idx], entry_norm[no_idx] * inf, dtype=np_float32)

            it += 1
            if it >= 35:
                print("Maximum iterations reached")
                return VagSearcher.VagSearchResult.MAX_ITERATIONS

    # returns a list of open portal pairs: [(blue1, orange1), (blue2, orange2), ...]
    def get_valid_portal_pairs(self) -> list:
        portals = []
        for line in self.send_and_await_response_from_console("y_spt_find_portals"):
            for m in re.finditer(r"portal with index (?P<index>\d+) at", line):
                idx = int(m.groupdict()["index"]) - 1
                props = self.send_cmd_and_get_response("y_spt_ipc_ent %i" % idx, False)[0]
                props["index"] = idx
                portals.append(props)
        pairs = []
        included = set()
        for p in portals:
            if p["index"] in included:
                continue
            if p["entity"]["m_bActivated"] == 0:
                continue
            included.add(p["index"])
            linked = p["entity"].get("m_hLinkedPortal")
            if linked == -1:
                linked = None
            else:
                linked = next(pair for pair in portals if pair["index"] == h_to_i(linked))
                included.add(linked["index"])
                if linked["entity"]["m_bActivated"] == 0:  # is this ever true?
                    linked = None
            if p["entity"]["m_bIsPortal2"] == 1:
                pairs.append((linked, p))
            else:
                pairs.append((p, linked))
        return pairs

    def try_vag_on_color(self, color: str) -> VagSearchResult:
        pairs = self.get_valid_portal_pairs()
        if len(pairs) == 0:
            raise Exception("no valid portal pairs")
        if len(pairs) > 1:
            raise Exception("not sure which portal pair to try vag on")
        if color.lower() == "blue":
            return self.try_vag(pairs[0][0], pairs[0][1])
        elif color.lower() == "orange":
            return self.try_vag(pairs[0][1], pairs[0][0])
        else:
            raise Exception("invalid portal color")

    def try_vag_on_portal_ent_index(self, idx: int) -> VagSearchResult:
        pairs = self.get_valid_portal_pairs()
        pair = next((p for p in pairs if p[0]["index"] == idx), None)
        if pair is None:
            pair = next((p for p in pairs if p[1]["index"] == idx), None)
            if pair is None:
                raise Exception("no valid portal with index %i found" % idx)
            return self.try_vag(pair[1], pair[0])
        else:
            return self.try_vag(pair[0], pair[1])


if __name__ == '__main__':
    import keyboard
    with VagSearcher("conlog") as v:
        v.debug = False
        keyboard.on_press_key('o', lambda _: v.close())
        keyboard.on_press_key('i', lambda _: v.try_vag_on_color("orange"))
        while not v.closed:
            sleep(0.1)
