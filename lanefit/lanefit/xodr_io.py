"""OpenDRIVE IO: parsing, initial-measurement statistics, reference-line sampling,
and the surgical lane-width writer (with geoReference CDATA restoration + verification)."""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from .util import eval_geometry

log = logging.getLogger("lanefit")


@dataclass
class Geometry:
    s: float
    x: float
    y: float
    hdg: float
    length: float
    gtype: str
    curv: float = 0.0
    curv0: float = 0.0
    curv1: float = 0.0


@dataclass
class LaneSection:
    s: float
    driving: list[int] = field(default_factory=list)   # signed lane ids of type driving

    @property
    def n_left(self) -> int:
        return sum(1 for i in self.driving if i > 0)

    @property
    def n_right(self) -> int:
        return sum(1 for i in self.driving if i < 0)


@dataclass
class Road:
    id: str
    length: float
    junction: str
    geoms: list[Geometry] = field(default_factory=list)
    sections: list[LaneSection] = field(default_factory=list)
    pred: tuple | None = None   # (elementType, elementId) from <link><predecessor>
    succ: tuple | None = None
    lane_offsets: list[tuple] = field(default_factory=list)  # (s, a, b, c, d)

    def lane_offset_at(self, s: float) -> float:
        rec = None
        for r in self.lane_offsets:
            if r[0] <= s:
                rec = r
            else:
                break
        if rec is None:
            return 0.0
        ds = s - rec[0]
        return rec[1] + rec[2] * ds + rec[3] * ds * ds + rec[4] * ds ** 3

    def sample(self, step: float) -> np.ndarray:
        """Sample the reference line -> array of (x, y, hdg, s_road)."""
        rows = []
        for g in self.geoms:
            n = max(2, int(np.ceil(g.length / step)))
            ds = np.linspace(0.0, g.length, n)
            xs, ys, hs = eval_geometry(g.gtype, g.x, g.y, g.hdg, g.length, ds,
                                       curv=g.curv, curv0=g.curv0, curv1=g.curv1)
            rows.append(np.column_stack([xs, ys, hs, g.s + ds]))
        return np.concatenate(rows) if rows else np.zeros((0, 4))


def parse_xodr(path: str, junction_roads: bool = False) -> tuple[dict, dict[str, Road]]:
    """Return (header_info, roads). Roads keyed by id; junction-internal excluded by default."""
    tree = ET.parse(path)
    root = tree.getroot()
    hdr_el = root.find("header")
    geo_el = hdr_el.find("geoReference") if hdr_el is not None else None
    header = {
        "attrib": dict(hdr_el.attrib) if hdr_el is not None else {},
        "geo_reference": (geo_el.text or "").strip() if geo_el is not None else "",
        "has_offset": hdr_el.find("offset") is not None if hdr_el is not None else False,
    }
    roads: dict[str, Road] = {}
    for r in root.findall("road"):
        if not junction_roads and r.get("junction") != "-1":
            continue
        road = Road(id=r.get("id"), length=float(r.get("length")), junction=r.get("junction"))
        link = r.find("link")
        if link is not None:
            pr, su = link.find("predecessor"), link.find("successor")
            if pr is not None:
                road.pred = (pr.get("elementType"), pr.get("elementId"))
            if su is not None:
                road.succ = (su.get("elementType"), su.get("elementId"))
        pv = r.find("planView")
        if pv is not None:
            for g in pv.findall("geometry"):
                base = dict(s=float(g.get("s")), x=float(g.get("x")), y=float(g.get("y")),
                            hdg=float(g.get("hdg")), length=float(g.get("length")))
                if g.find("line") is not None:
                    road.geoms.append(Geometry(**base, gtype="line"))
                elif g.find("arc") is not None:
                    road.geoms.append(Geometry(**base, gtype="arc",
                                               curv=float(g.find("arc").get("curvature"))))
                elif g.find("spiral") is not None:
                    sp = g.find("spiral")
                    road.geoms.append(Geometry(**base, gtype="spiral",
                                               curv0=float(sp.get("curvStart")),
                                               curv1=float(sp.get("curvEnd"))))
        lanes = r.find("lanes")
        if lanes is not None:
            for lo in lanes.findall("laneOffset"):
                road.lane_offsets.append((float(lo.get("s")), float(lo.get("a")),
                                          float(lo.get("b")), float(lo.get("c")),
                                          float(lo.get("d"))))
            road.lane_offsets.sort(key=lambda q: q[0])
            for ls in lanes.findall(".//laneSection"):
                sec = LaneSection(s=float(ls.get("s")))
                for side in ("left", "right"):
                    se = ls.find(side)
                    if se is None:
                        continue
                    for lane in se.findall("lane"):
                        if lane.get("type") == "driving":
                            sec.driving.append(int(lane.get("id")))
                road.sections.append(sec)
            road.sections.sort(key=lambda q: q.s)
        roads[road.id] = road
    return header, roads


def xodr_statistics(path: str) -> dict:
    """Initial-measurement audit of the map: censuses that drive pipeline decisions."""
    txt = open(path, encoding="utf-8", errors="ignore").read()
    geom_census = {g: len(re.findall(f"<{g}[ />]", txt))
                   for g in ("line", "arc", "spiral", "paramPoly3", "poly3")}
    lane_types = Counter(re.findall(r'<lane id="[^"]+" type="([^"]+)"', txt))
    width_a = Counter(round(float(a), 3)
                      for a in re.findall(r'<width sOffset="[^"]+" a="([^"]+)"', txt))
    roads = re.findall(r'<road [^>]*junction="([^"]+)"', txt)
    n_junction = sum(1 for j in roads if j != "-1")
    elev_a = re.findall(r'<elevation s="[^"]+" a="([^"]+)"', txt)
    elev_nonzero = sum(1 for a in elev_a if abs(float(a)) > 1e-6)
    top_widths = width_a.most_common(6)
    total_w = sum(width_a.values())
    return {
        "roads_total": len(roads),
        "roads_normal": len(roads) - n_junction,
        "roads_junction": n_junction,
        "geometry_census": geom_census,
        "lane_type_census": dict(lane_types),
        "width_records_total": total_w,
        "width_top_values": [{"a_m": a, "count": c, "share": round(c / total_w, 4)}
                             for a, c in top_widths],
        "elevation_records": len(elev_a),
        "elevation_nonzero": elev_nonzero,
    }


# ---------------- writer ----------------
def apply_lane_widths(in_path: str, updates: list[dict], out_path: str) -> dict:
    """Replace the <width> records of exactly the given (road, laneSection, driving lane)
    triples with a single constant record. Aborts on any mismatch. Restores geoReference
    CDATA after serialization. Returns a verification summary."""
    want = {(u["road_id"], float(u["lane_section_s"]), int(u["lane_id"])): float(u["width_m"])
            for u in updates}
    tree = ET.parse(in_path)
    root = tree.getroot()

    applied: dict = {}
    for road in root.findall("road"):
        rid = road.get("id")
        if not any(k[0] == rid for k in want):
            continue
        for ls in road.find("lanes").findall(".//laneSection"):
            s_sec = float(ls.get("s"))
            for side in ("left", "right"):
                se = ls.find(side)
                if se is None:
                    continue
                for lane in se.findall("lane"):
                    lid = int(lane.get("id"))
                    key = next((k for k in want
                                if k[0] == rid and k[2] == lid and abs(k[1] - s_sec) < 1e-3),
                               None)
                    if key is None:
                        continue
                    if lane.get("type") != "driving":
                        raise RuntimeError(
                            f"refusing to touch non-driving lane road={rid} s={s_sec} id={lid} "
                            f"(type={lane.get('type')!r})")
                    widths = lane.findall("width")
                    if not widths:
                        raise RuntimeError(f"no <width> on road={rid} s={s_sec} lane={lid}")
                    pos = list(lane).index(widths[0])
                    for w in widths:
                        lane.remove(w)
                    lane.insert(pos, ET.Element("width", {
                        "sOffset": "0.0000000000000000e+00",
                        "a": f"{want[key]:.16e}",
                        "b": "0.0000000000000000e+00",
                        "c": "0.0000000000000000e+00",
                        "d": "0.0000000000000000e+00",
                    }))
                    applied[key] = len(widths)
    missing = set(want) - set(applied)
    if missing:
        raise RuntimeError(f"{len(missing)} updates not found in xodr: {sorted(missing)[:5]}")

    tree.write(out_path, encoding="UTF-8", xml_declaration=True)

    # restore CDATA wrapper (ElementTree writes escaped text)
    txt = open(out_path, encoding="utf-8").read()

    def _cdata(m):
        inner = m.group(1).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        if inner.startswith("<![CDATA["):
            return m.group(0)
        return f"<geoReference><![CDATA[{inner}]]></geoReference>"

    txt, nsub = re.subn(r"<geoReference>(.*?)</geoReference>", _cdata, txt, flags=re.S)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(txt)

    # verification pass
    root2 = ET.parse(out_path).getroot()
    ok = bad = 0
    for road in root2.findall("road"):
        rid = road.get("id")
        for ls in road.find("lanes").findall(".//laneSection"):
            s_sec = float(ls.get("s"))
            for side in ("left", "right"):
                se = ls.find(side)
                if se is None:
                    continue
                for lane in se.findall("lane"):
                    key = next((k for k in want
                                if k[0] == rid and k[2] == int(lane.get("id"))
                                and abs(k[1] - s_sec) < 1e-3), None)
                    if key is None:
                        continue
                    ws = lane.findall("width")
                    good = (len(ws) == 1
                            and abs(float(ws[0].get("a")) - want[key]) < 1e-9
                            and all(abs(float(ws[0].get(c))) < 1e-12 for c in "bcd"))
                    ok += good
                    bad += not good
    if bad:
        raise RuntimeError(f"verification failed on {bad} lanes")
    log.info("apply_lane_widths: %d lanes updated and verified (replaced %d width records)",
             ok, sum(applied.values()))
    return {"lanes_updated": ok, "width_records_replaced": sum(applied.values()),
            "cdata_restored": nsub}

# ---------------- piecewise-profile writer + junction tapering ----------------
def _set_lane_widths(lane, recs: list[dict]) -> int:
    """Replace a lane's <width> records with the given list. Returns #removed."""
    widths = lane.findall("width")
    if not widths:
        raise RuntimeError("lane has no <width> to replace")
    pos = list(lane).index(widths[0])
    for w in widths:
        lane.remove(w)
    for i, r in enumerate(sorted(recs, key=lambda q: q["sOffset"])):
        lane.insert(pos + i, ET.Element("width", {
            "sOffset": f"{r['sOffset']:.16e}", "a": f"{r['a']:.16e}",
            "b": f"{r['b']:.16e}", "c": f"{r['c']:.16e}", "d": f"{r['d']:.16e}"}))
    return len(widths)


def _restore_cdata(out_path: str) -> None:
    txt = open(out_path, encoding="utf-8").read()

    def _cdata(m):
        inner = m.group(1).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        if inner.startswith("<![CDATA["):
            return m.group(0)
        return f"<geoReference><![CDATA[{inner}]]></geoReference>"

    txt, _ = re.subn(r"<geoReference>(.*?)</geoReference>", _cdata, txt, flags=re.S)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(txt)


def _add_cubic_to_records(lanes_el, poly: tuple, length: float) -> None:
    """Add cubic P(s)=A+Bs+Cs^2+Ds^3 (road arclength) to <laneOffset> records."""
    A, B, C, D = poly
    recs = lanes_el.findall("laneOffset")
    if not recs:
        el = ET.Element("laneOffset", {"s": "0.0", "a": f"{A:.16e}", "b": f"{B:.16e}",
                                       "c": f"{C:.16e}", "d": f"{D:.16e}"})
        lanes_el.insert(0, el)
        return
    for r in recs:
        s0 = float(r.get("s"))
        r.set("a", f"{float(r.get('a')) + A + B*s0 + C*s0*s0 + D*s0**3:.16e}")
        r.set("b", f"{float(r.get('b')) + B + 2*C*s0 + 3*D*s0*s0:.16e}")
        r.set("c", f"{float(r.get('c')) + C + 3*D*s0:.16e}")
        r.set("d", f"{float(r.get('d')) + D:.16e}")


def apply_lane_profiles(in_path: str, updates: list[dict], out_path: str,
                        taper_junctions: bool = True, default_lane_w: float = 3.5) -> dict:
    """Write piecewise width profiles onto driving lanes, then blend junction
    connecting-roads between their endpoint roads' profile values (smoothstep).

    updates rows: road_id, lane_section_s, lane_section_end, lane_id,
                  knots (JSON [[s_road, w_per_lane], ...]).
    """
    import json as _json

    from .profiles import eval_knots, knots_to_records, smoothstep_taper

    prof: dict[str, list] = {}
    deltas: dict[str, float] = {}
    per_sec: dict[tuple, dict] = {}
    for u in updates:
        knots = [(float(a), float(b)) for a, b in _json.loads(u["knots"])]
        prof[u["road_id"]] = knots
        deltas[u["road_id"]] = float(u.get("center_delta", 0.0) or 0.0)
        per_sec[(u["road_id"], round(float(u["lane_section_s"]), 3), int(u["lane_id"]))] = {
            "sec_s": float(u["lane_section_s"]), "sec_end": float(u["lane_section_end"]),
            "knots": knots}

    tree = ET.parse(in_path)
    root = tree.getroot()

    n_lanes = n_recs = n_shift = 0
    for road in root.findall("road"):
        rid = road.get("id")
        if rid not in prof:
            continue
        # lateral registration: shift the whole lane stack onto the measured centerline
        d = deltas.get(rid, 0.0)
        if abs(d) > 0.02:
            _add_cubic_to_records(road.find("lanes"), (d, 0.0, 0.0, 0.0),
                                  float(road.get("length")))
            n_shift += 1
        for ls in road.find("lanes").findall(".//laneSection"):
            s_sec = round(float(ls.get("s")), 3)
            for side in ("left", "right"):
                se = ls.find(side)
                if se is None:
                    continue
                for lane in se.findall("lane"):
                    key = (rid, s_sec, int(lane.get("id")))
                    if key not in per_sec:
                        continue
                    if lane.get("type") != "driving":
                        raise RuntimeError(f"non-driving lane targeted: {key}")
                    info = per_sec[key]
                    recs = knots_to_records(info["knots"], info["sec_s"], info["sec_end"])
                    _set_lane_widths(lane, recs)
                    n_lanes += 1
                    n_recs += len(recs)
    if n_lanes < len(per_sec):
        raise RuntimeError(f"only {n_lanes}/{len(per_sec)} lane targets found in xodr")

    # ---- junction connector tapering ----
    n_taper = 0
    if taper_junctions:
        # width of a road's driving lane at one of its ends
        def end_width(el_id: str, contact: str) -> float | None:
            if el_id in prof:
                road_len = max(k[0] for k in prof[el_id])
                return eval_knots(prof[el_id], 0.0 if contact == "start" else road_len)
            return None

        for road in root.findall("road"):
            if road.get("junction") == "-1":
                continue
            link = road.find("link")
            if link is None:
                continue
            pr, su = link.find("predecessor"), link.find("successor")
            if pr is None or su is None:
                continue
            if pr.get("elementType") != "road" or su.get("elementType") != "road":
                continue
            w_in = end_width(pr.get("elementId"), pr.get("contactPoint") or "end")
            w_out = end_width(su.get("elementId"), su.get("contactPoint") or "start")
            if w_in is None and w_out is None:
                continue                       # neither endpoint was corrected
            # nearest-known-width through the junction: an unknown endpoint
            # inherits the measured one (never blend down to the map default)
            w_in = w_in if w_in is not None else w_out
            w_out = w_out if w_out is not None else w_in
            length = float(road.get("length"))
            if length < 0.5:
                continue
            # blend the lateral registration through the connector as well
            sgn_p = 1.0 if (pr.get("contactPoint") or "end") == "end" else -1.0
            sgn_s = 1.0 if (su.get("contactPoint") or "start") == "start" else -1.0
            dp_ = deltas.get(pr.get("elementId"))
            ds_ = deltas.get(su.get("elementId"))
            d_in = sgn_p * (dp_ if dp_ is not None else (ds_ or 0.0))
            d_out = sgn_s * (ds_ if ds_ is not None else (dp_ or 0.0))
            if abs(d_in) > 0.02 or abs(d_out) > 0.02:
                dd = d_out - d_in
                _add_cubic_to_records(road.find("lanes"),
                                      (d_in, 0.0, 3 * dd / length ** 2,
                                       -2 * dd / length ** 3), length)
            for ls in road.find("lanes").findall(".//laneSection"):
                for side in ("left", "right"):
                    se = ls.find(side)
                    if se is None:
                        continue
                    for lane in se.findall("lane"):
                        if lane.get("type") != "driving":
                            continue
                        if not lane.findall("width"):
                            continue
                        _set_lane_widths(lane, [smoothstep_taper(w_in, w_out, length)])
                        n_taper += 1

    tree.write(out_path, encoding="UTF-8", xml_declaration=True)
    _restore_cdata(out_path)
    log.info("apply_lane_profiles: %d road lanes -> %d width records; %d roads "
             "laterally registered; %d junction connector lanes tapered",
             n_lanes, n_recs, n_shift, n_taper)
    return {"lanes_updated": n_lanes, "width_records_written": n_recs,
            "roads_registered": n_shift, "connector_lanes_tapered": n_taper}
