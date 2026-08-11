"""Shared helpers: JSONC, quaternion/tf composition, OpenDRIVE geometry evaluation, bag IO."""
from __future__ import annotations

import json
import math
import re
from typing import Iterator

import numpy as np


# ---------------- JSON with // and /* */ comments (glim config files) ----------------
def load_jsonc(path: str) -> dict:
    src = open(path).read()
    out = []
    i, n = 0, len(src)
    in_str = esc = False
    while i < n:
        ch = src[i]
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
        elif ch == '"':
            in_str = True
            out.append(ch)
            i += 1
        elif ch == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
        elif ch == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i += 2
        else:
            out.append(ch)
            i += 1
    txt = "".join(out)
    txt = re.sub(r",\s*([}\]])", r"\1", txt)   # tolerate trailing commas
    return json.loads(txt)


# ---------------- quaternions (x, y, z, w) ----------------
def quat_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def quat_conj(q):
    return (-q[0], -q[1], -q[2], q[3])


def quat_rotate(q, v):
    p = (v[0], v[1], v[2], 0.0)
    r = quat_mul(quat_mul(q, p), quat_conj(q))
    return (r[0], r[1], r[2])


class TfTree:
    """Static-transform graph. Edge parent->child stores T_parent_child
    (p_parent = R * p_child + t)."""

    def __init__(self):
        self.edges: dict[tuple[str, str], tuple] = {}
        self.adj: dict[str, set[str]] = {}

    def add(self, parent: str, child: str, t, q):
        self.edges[(parent, child)] = (tuple(t), tuple(q))
        self.adj.setdefault(parent, set()).add(child)
        self.adj.setdefault(child, set()).add(parent)

    def transform(self, src: str, dst: str):
        """T such that p_dst = R p_src + t  (i.e. T_dst_src)."""
        # BFS path src..dst
        prev: dict[str, str] = {src: src}
        queue = [src]
        while queue:
            n = queue.pop(0)
            if n == dst:
                break
            for m in self.adj.get(n, ()):
                if m not in prev:
                    prev[m] = n
                    queue.append(m)
        if dst not in prev:
            raise KeyError(f"no tf path {src} -> {dst}")
        path = [dst]
        while path[-1] != src:
            path.append(prev[path[-1]])
        path.reverse()  # src ... dst
        # accumulate p_dst = T(dst<-src) p_src walking the chain
        t_acc, q_acc = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)  # identity: dst<-dst
        # walk from dst side back to src: build T_dst_src by composing edges
        # T_a_c = T_a_b * T_b_c ; edges stored as T_parent_child
        def compose(t1, q1, t2, q2):  # T1 * T2
            t = tuple(np.add(t1, quat_rotate(q1, t2)))
            return t, quat_mul(q1, q2)

        # build T_src_dst first (walk forward), then invert
        t_sd, q_sd = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)
        for a, b in zip(path[:-1], path[1:]):
            if (a, b) in self.edges:
                te, qe = self.edges[(a, b)]           # T_a_b
            else:
                te, qe = self.edges[(b, a)]           # T_b_a -> invert
                qe_i = quat_conj(qe)
                te = tuple(np.negative(quat_rotate(qe_i, te)))
                qe = qe_i
            t_sd, q_sd = compose(t_sd, q_sd, te, qe)  # now T_src_b
        # invert T_src_dst -> T_dst_src
        q_inv = quat_conj(q_sd)
        t_inv = tuple(np.negative(quat_rotate(q_inv, t_sd)))
        return t_inv, q_inv


# ---------------- OpenDRIVE geometry evaluation ----------------
def eval_geometry(gtype: str, x0: float, y0: float, hdg: float, length: float,
                  ds: np.ndarray, curv: float = 0.0, curv0: float = 0.0,
                  curv1: float = 0.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Evaluate a planView geometry at local arclengths ds -> (x, y, heading)."""
    if gtype == "line":
        return x0 + ds * math.cos(hdg), y0 + ds * math.sin(hdg), np.full_like(ds, hdg)
    if gtype == "arc":
        k = curv
        h = hdg + k * ds
        return (x0 + (np.sin(h) - math.sin(hdg)) / k,
                y0 - (np.cos(h) - math.cos(hdg)) / k, h)
    if gtype == "spiral":
        kd = (curv1 - curv0) / length
        if abs(kd) < 1e-12:
            if abs(curv0) < 1e-12:
                return eval_geometry("line", x0, y0, hdg, length, ds)
            return eval_geometry("arc", x0, y0, hdg, length, ds, curv=curv0)
        from scipy.special import fresnel
        a = math.sqrt(math.pi / abs(kd))
        sgn = 1.0 if kd > 0 else -1.0
        s0 = curv0 / kd                       # arclength offset where curvature = 0
        u = ds + s0
        S1, C1 = fresnel(u / a)
        S0, C0 = fresnel(np.array([s0 / a]))
        dx = a * (C1 - C0[0])
        dy = a * (S1 - S0[0]) * sgn
        rot = hdg - 0.5 * kd * s0 * s0        # align base-clothoid tangent at ds=0 to hdg
        cr, sr = math.cos(rot), math.sin(rot)
        h = rot + 0.5 * kd * u * u            # = hdg + curv0*ds + kd/2*ds^2
        return x0 + dx * cr - dy * sr, y0 + dx * sr + dy * cr, h
    raise ValueError(f"unsupported geometry {gtype}")


# ---------------- rosbag2 helpers (imported lazily; only exist in container) ----------------
def open_bag_reader(uri: str, topics: list[str] | None = None):
    from rosbag2_py import ConverterOptions, SequentialReader, StorageFilter, StorageOptions
    r = SequentialReader()
    r.open(StorageOptions(uri=uri, storage_id="sqlite3"), ConverterOptions("cdr", "cdr"))
    if topics:
        r.set_filter(StorageFilter(topics=topics))
    return r


def iter_messages(uri: str, topics: list[str], deserialize: bool = True) -> Iterator:
    """Yield (topic, msg_or_bytes, t_ns) for the given topics."""
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message
    r = open_bag_reader(uri, topics)
    types = {t.name: t.type for t in r.get_all_topics_and_types()}
    cache: dict[str, object] = {}
    while r.has_next():
        topic, data, t_ns = r.read_next()
        if deserialize:
            if topic not in cache:
                cache[topic] = get_message(types[topic])
            yield topic, deserialize_message(data, cache[topic]), t_ns
        else:
            yield topic, data, t_ns
