"""skeleton: bones with parent-child transforms, pivots, rest angles, FK and 2-bone IK (y is DOWN, like the screen)

Sides are named by the SCREEN: 'a' = the limb on the screen's left when the character faces the camera, 'b' = right.
A positive turn means the character turns to face screen-right (then side 'a' is the near side)."""
import math

import cairo

BONES = ["root", "spine", "neck", "head",
         "uarm_a", "farm_a", "hand_a", "uarm_b", "farm_b", "hand_b",
         "thigh_a", "shin_a", "foot_a", "thigh_b", "shin_b", "foot_b"]


class Skeleton:
    def __init__(self, P):
        """P = proportions (character units, y down). Builds bones: name -> (parent, offset, length, rest_angle)"""
        self.P = P
        T, N = P["torso"], P["neck"]
        self.bones = {
            "root": (None, (0.0, 0.0), 0.0, 0.0),
            "spine": ("root", (0.0, -P["pelvis_up"]), T, 0.0),
            "neck": ("spine", (0.0, -T), N, 0.0),
            "head": ("neck", (0.0, -N), P["head_h"], 0.0),
            "uarm_a": ("spine", (-P["shoulder"] * 0.80, -T + P["shoulder_drop"]), P["uarm"], math.radians(11)),
            "farm_a": ("uarm_a", (0.0, P["uarm"]), P["farm"], math.radians(-7)),
            "hand_a": ("farm_a", (0.0, P["farm"]), P["hand"], 0.0),
            "uarm_b": ("spine", (P["shoulder"] * 0.80, -T + P["shoulder_drop"]), P["uarm"], math.radians(-11)),
            "farm_b": ("uarm_b", (0.0, P["uarm"]), P["farm"], math.radians(7)),
            "hand_b": ("farm_b", (0.0, P["farm"]), P["hand"], 0.0),
            "thigh_a": ("root", (-P["hip"] * 0.55, 0.0), P["thigh"], math.radians(1.5)),
            "shin_a": ("thigh_a", (0.0, P["thigh"]), P["shin"], 0.0),
            "foot_a": ("shin_a", (0.0, P["shin"]), P["foot_h"], 0.0),
            "thigh_b": ("root", (P["hip"] * 0.55, 0.0), P["thigh"], math.radians(-1.5)),
            "shin_b": ("thigh_b", (0.0, P["thigh"]), P["shin"], 0.0),
            "foot_b": ("shin_b", (0.0, P["shin"]), P["foot_h"], 0.0),
        }

    def solve(self, pose, x, y, scale=1.0, flip=1.0):
        """world matrices for a pose. pose['rot'][bone] = radians added to the rest angle; pose['len'][bone] = length
        factor (foreshortening, e.g. thighs seen from the front when sitting); pose['root'] = (dx, dy)."""
        rot = pose.get("rot", {})
        lens = pose.get("len", {})
        W = {}
        base = cairo.Matrix()
        base.translate(x, y)
        base.scale(scale, scale)
        rx, ry = pose.get("root", (0.0, 0.0))
        base.translate(rx, ry)
        for b in BONES:
            par, off, ln, rest = self.bones[b]
            m = cairo.Matrix()
            if par is not None:
                pl = lens.get(par, 1.0)
                m.translate(off[0], off[1] * pl if self.bones[par][2] else off[1])
            m.rotate(rest + rot.get(b, 0.0))
            W[b] = m.multiply(W[par]) if par is not None else m.multiply(base)
        return W

    def joint(self, W, b, along=0.0):
        """world point of a bone: its pivot (along=0) or a fraction along its length"""
        ln = self.bones[b][2]
        sign = -1.0 if b in ("spine", "neck", "head") else 1.0
        return W[b].transform_point(0.0, sign * ln * along)


def two_bone_ik(hip, target, l1, l2, knee_x=1.0):
    """angles (world, from +y) of the upper and lower bone so the chain end reaches the target; the middle joint
    (knee / elbow) points toward +x when knee_x=+1, toward -x when -1"""
    bend = -knee_x
    dx, dy = target[0] - hip[0], target[1] - hip[1]
    d = max(1e-6, min(l1 + l2 - 1e-4, math.hypot(dx, dy)))
    base = math.atan2(-dx, dy)                          # angle from +y (clockwise positive, like cairo rotate)
    c = (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)
    a1 = math.acos(max(-1.0, min(1.0, c)))
    c2 = (l1 * l1 + l2 * l2 - d * d) / (2 * l1 * l2)
    a2 = math.pi - math.acos(max(-1.0, min(1.0, c2)))
    up = base + bend * a1                               # a positive angle swings the end toward -x
    low = up - bend * a2
    return up, low


def world_angle(m):
    """angle of a matrix's +y axis from +y (clockwise positive)"""
    x, y = m.transform_distance(0.0, 1.0)
    return math.atan2(-x, y)
