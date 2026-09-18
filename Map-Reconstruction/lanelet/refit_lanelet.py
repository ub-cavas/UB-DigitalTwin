#!/usr/bin/env python3
"""Refit an existing local-coordinate Lanelet map to a newer CARLA OpenDRIVE.

Retains the manually authored routes and regulations. Straight lanelets are
matched to same-direction non-junction CARLA lanes; tangent cubic turns join
the updated roads. This is not a general OpenDRIVE converter.
Requires CARLA, NumPy, SciPy, pyproj; operates offline without a CARLA server.
"""

import argparse
from collections import defaultdict
import copy
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import carla
import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree


def tags(element):
    return {t.get("k"): t.get("v") for t in element.findall("tag")}


def parameter(points):
    distances = np.r_[0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    if distances[-1] <= 0:
        raise ValueError("Zero-length boundary")
    return distances / distances[-1], distances[-1]


def interpolate(points, fractions):
    t, _ = parameter(points)
    return np.column_stack([np.interp(fractions, t, points[:, i]) for i in range(2)])


def read_map(path):
    root = ET.parse(path).getroot()
    nodes = {n.get("id"): n for n in root.findall("node")}
    xy = {i: np.array([float(tags(n)["local_x"]), float(tags(n)["local_y"])])
          for i, n in nodes.items()}
    ways = {w.get("id"): w for w in root.findall("way")}
    refs = {i: [n.get("ref") for n in w.findall("nd")] for i, w in ways.items()}
    points = {i: np.array([xy[n] for n in ns]) for i, ns in refs.items()}
    return root, nodes, xy, ways, refs, points


def refit(source, xodr, output, spacing=1.0):
    root, nodes, old_xy, ways, refs, points = read_map(source)
    lanelets = [r for r in root.findall("relation") if tags(r).get("type") == "lanelet"]
    all_xy = np.array(list(old_xy.values()))
    lower, upper = all_xy.min(axis=0) - 20, all_xy.max(axis=0) + 20
    road_map = carla.Map("UB-refit", Path(xodr).read_text())
    georef = ET.parse(xodr).getroot().findtext("header/geoReference")
    to_wgs84 = Transformer.from_crs(georef, "EPSG:4326", always_xy=True)
    samples = []
    for wp in road_map.generate_waypoints(0.25):
        p = np.array([wp.transform.location.x, -wp.transform.location.y])
        if not wp.is_junction and np.all(p >= lower) and np.all(p <= upper):
            samples.append(wp)
    if not samples:
        raise ValueError("No OpenDRIVE lanes within the source map extent")
    positions = np.array([[w.transform.location.x, -w.transform.location.y] for w in samples])
    yaw = np.deg2rad([w.transform.rotation.yaw for w in samples])
    headings = np.column_stack([np.cos(yaw), -np.sin(yaw)])
    widths = np.array([w.lane_width for w in samples])
    tree = cKDTree(positions)
    targets = defaultdict(list)
    matches = []

    for rel in lanelets:
        turn = tags(rel).get("turn_direction", "straight")
        if turn in ("left", "right"):
            continue
        members = {m.get("role"): m.get("ref") for m in rel.findall("member")}
        left_id, right_id = members["left"], members["right"]
        left, right = points[left_id], points[right_id]
        direction = left[-1] - left[0]
        direction /= np.linalg.norm(direction)
        reverse = np.cross(direction, right.mean(axis=0) - left.mean(axis=0)) > 0
        if reverse:
            left, right, direction = left[::-1], right[::-1], -direction
        count = max(2, int(np.ceil(max(parameter(left)[1], parameter(right)[1]) / spacing)) + 1)
        t = np.linspace(0, 1, count)
        center = (interpolate(left, t) + interpolate(right, t)) / 2
        distances, candidates = tree.query(center, k=min(300, len(samples)))
        alignment = headings[candidates] @ direction
        score = distances + 100 * (1 - alignment)
        chosen = candidates[np.arange(count), score.argmin(axis=1)]
        if np.min(headings[chosen] @ direction) < 0.97:
            raise ValueError(f"Cannot match lanelet {rel.get('id')} to a parallel road")
        tangents = headings[chosen]
        offsets = center - positions[chosen]
        along = np.sum(offsets * tangents, axis=1)
        # Extend the adjacent straight road through gaps occupied by junctions.
        fitted_center = positions[chosen] + along[:, None] * tangents
        lateral_error = np.linalg.norm(center - fitted_center, axis=1)
        if lateral_error.max() > 6 or np.abs(along).max() > 25:
            raise ValueError(f"Ambiguous road match for lanelet {rel.get('id')}")
        normals = np.column_stack([-tangents[:, 1], tangents[:, 0]])
        half_width = widths[chosen, None] / 2
        for wid, new in ((left_id, fitted_center + normals * half_width),
                         (right_id, fitted_center - normals * half_width)):
            targets[wid].append((t, new[::-1] if reverse else new))
        matches.append({"lanelet": int(rel.get("id")),
                        "opendrive_lanes": sorted({(samples[i].road_id, samples[i].lane_id) for i in chosen}),
                        "width_min_m": float(widths[chosen].min()),
                        "width_max_m": float(widths[chosen].max()),
                        "max_center_shift_m": float(lateral_error.max())})

    fitted = {}
    endpoint_targets = defaultdict(list)
    for wid, proposals in targets.items():
        count = max(2, int(np.ceil(parameter(points[wid])[1] / spacing)) + 1)
        t = np.linspace(0, 1, count)
        fitted[wid] = np.mean([np.column_stack([np.interp(t, ft, p[:, j]) for j in range(2)])
                               for ft, p in proposals], axis=0)
        endpoint_targets[refs[wid][0]].append(fitted[wid][0])
        endpoint_targets[refs[wid][-1]].append(fitted[wid][-1])
    new_endpoints = {nid: np.mean(values, axis=0) for nid, values in endpoint_targets.items()}
    endpoint_tangents = defaultdict(list)
    for wid, p in fitted.items():
        for nid, d in ((refs[wid][0], p[1] - p[0]), (refs[wid][-1], p[-1] - p[-2])):
            endpoint_tangents[nid].append(d / np.linalg.norm(d))

    def turn_tangents(wid):
        p = points[wid]
        directions = []
        for nid, d in ((refs[wid][0], p[1] - p[0]), (refs[wid][-1], p[-1] - p[-2])):
            d = d / np.linalg.norm(d)
            candidates = endpoint_tangents[nid]
            if not candidates:
                raise ValueError(f"Turn boundary {wid} lacks a straight-road endpoint")
            best = max(candidates, key=lambda v: abs(np.dot(v, d)))
            directions.append(best if np.dot(best, d) > 0 else -best)
        return directions

    turns = [r for r in lanelets if tags(r).get("turn_direction") in ("left", "right")]
    setbacks = []
    # Widening a road can consume a formerly valid inside corner. Extend the
    # intersection by moving its shared cross-sections along the approach lanes.
    # Keep both ellipse axes large enough to avoid high endpoint curvature.
    for _ in range(20):
        changed = False
        for rel in turns:
            ids = [m.get("ref") for m in rel.findall("member") if m.get("role") in ("left", "right")]
            shifts = [0.0, 0.0]
            for wid in ids:
                d0, d1 = turn_tangents(wid)
                p0, p1 = (new_endpoints[nid] for nid in (refs[wid][0], refs[wid][-1]))
                a, b = np.linalg.solve(np.column_stack([d0, d1]), p1 - p0)
                required_a = max(3.0, np.sqrt(2.7 * max(b, 0)))
                required_b = max(3.0, np.sqrt(2.7 * max(a, 0)))
                shifts = np.maximum(shifts, [required_a - a, required_b - b])
            if max(shifts) > 1e-5:
                changed = True
                setbacks.append({"lanelet": int(rel.get("id")), "entry_m": float(shifts[0]), "exit_m": float(shifts[1])})
                for wid in ids:
                    d0, d1 = turn_tangents(wid)
                    new_endpoints[refs[wid][0]] -= shifts[0] * d0
                    new_endpoints[refs[wid][-1]] += shifts[1] * d1
        if not changed:
            break
    else:
        raise ValueError("Intersection setback adjustments did not converge")

    boundary_ids = {m.get("ref") for r in lanelets for m in r.findall("member")
                    if m.get("role") in ("left", "right")}
    for wid in sorted(boundary_ids, key=int):
        start, end = refs[wid][0], refs[wid][-1]
        if wid not in fitted:
            count = max(len(points[wid]), int(np.ceil(parameter(points[wid])[1] / spacing)) + 1)
            t = np.linspace(0, 1, count)
            d0, d1 = turn_tangents(wid)
            p0, p3 = new_endpoints[start], new_endpoints[end]
            a, b = np.linalg.solve(np.column_stack([d0, d1]), p3 - p0)
            # Cubic approximation of a quarter ellipse, tangent to both roads.
            factor = 4 * (np.sqrt(2) - 1) / 3
            p1, p2 = p0 + factor * a * d0, p3 - factor * b * d1
            t = t[:, None]
            fitted[wid] = (1-t)**3*p0 + 3*(1-t)**2*t*p1 + 3*(1-t)*t**2*p2 + t**3*p3
        else:
            # Reconcile boundaries shared by more than one lanelet.
            t = np.linspace(0, 1, len(fitted[wid]))[:, None]
            delta0 = new_endpoints[start] - fitted[wid][0]
            delta1 = new_endpoints[end] - fitted[wid][-1]
            fitted[wid] += (1 - t) * delta0 + t * delta1

    for wid in sorted(boundary_ids, key=int):
        _, length = parameter(fitted[wid])
        fitted[wid] = interpolate(fitted[wid], np.linspace(0, 1, max(2, int(np.ceil(length / spacing)) + 1)))

    # Refit stop lines and signs using the same lane cross-section transform.
    for rel in lanelets:
        members = {m.get("role"): m.get("ref") for m in rel.findall("member")}
        if "regulatory_element" not in members:
            continue
        regulation = root.find(f"relation[@id='{members['regulatory_element']}']")
        lid, rid = members["left"], members["right"]
        for member in regulation.findall("member"):
            wid = member.get("ref")
            new = []
            for p in points[wid]:
                ts = np.linspace(0, 1, 1001)
                old_left, old_right = interpolate(points[lid], ts), interpolate(points[rid], ts)
                centers = (old_left + old_right) / 2
                ix = np.argmin(np.linalg.norm(centers - p, axis=1))
                lateral = old_right[ix] - old_left[ix]
                fraction = np.dot(p - old_left[ix], lateral) / np.dot(lateral, lateral)
                new_left = interpolate(fitted[lid], [ts[ix]])[0]
                new_right = interpolate(fitted[rid], [ts[ix]])[0]
                old_cross = old_left[ix] + fraction * lateral
                new.append(new_left + fraction * (new_right - new_left) + p - old_cross)
            fitted[wid] = np.array(new)

    next_id = max(int(e.get("id")) for e in root if e.get("id")) + 1
    new_nodes = {}

    def make_node(nid, p, original=None):
        node = copy.deepcopy(original) if original is not None else ET.Element("node", id=nid, lat="0", lon="0")
        lon, lat = to_wgs84.transform(*p)
        node.set("lat", f"{lat:.11f}")
        node.set("lon", f"{lon:.11f}")
        for key, value in (("local_x", p[0]), ("local_y", p[1])):
            tag = node.find(f"tag[@k='{key}']")
            if tag is None:
                tag = ET.SubElement(node, "tag", k=key)
            tag.set("v", f"{value:.6f}")
        if node.find("tag[@k='ele']") is None:
            ET.SubElement(node, "tag", k="ele", v="0")
        return node

    # Existing endpoint IDs encode routing connectivity and must stay shared.
    for wid, way in ways.items():
        if wid not in fitted:
            for nid in refs[wid]:
                new_nodes[nid] = make_node(nid, old_xy[nid], nodes[nid])
            continue
        new_refs = []
        for i, p in enumerate(fitted[wid]):
            if i == 0:
                nid = refs[wid][0]
            elif i == len(fitted[wid]) - 1:
                nid = refs[wid][-1]
            else:
                nid = str(next_id)
                next_id += 1
            if nid in new_endpoints:
                p = new_endpoints[nid]
            if nid in new_nodes:
                previous = np.array([float(tags(new_nodes[nid])[k]) for k in ("local_x", "local_y")])
                if np.linalg.norm(previous - p) > 1e-4:
                    raise ValueError(f"Conflicting shared node {nid}")
            new_nodes[nid] = make_node(nid, p, nodes.get(nid))
            new_refs.append(nid)
        for nd in list(way.findall("nd")):
            way.remove(nd)
        for index, nid in enumerate(new_refs):
            way.insert(index, ET.Element("nd", ref=nid))

    result = ET.Element("osm", version="0.6", generator="UB-DigitalTwin lanelet refit")
    ET.SubElement(result, "MetaInfo", format_version="1", map_version="v1.1.0-refit")
    result.extend(new_nodes[k] for k in sorted(new_nodes, key=int))
    result.extend(ways.values())
    result.extend(root.findall("relation"))
    ET.indent(result, space="  ")
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(result).write(output, encoding="utf-8", xml_declaration=True)
    report = {"source_lanelet": str(source), "source_sha256": hashlib.sha256(Path(source).read_bytes()).hexdigest(),
              "opendrive": str(xodr), "opendrive_sha256": hashlib.sha256(Path(xodr).read_bytes()).hexdigest(),
              "output": str(output), "lanelets": len(lanelets), "sample_spacing_m": spacing,
              "matched_straight_lanelets": matches, "intersection_setbacks": setbacks,
              "method": "Straight boundaries fitted to OpenDRIVE; tangent cubic turn boundaries with shared intersection setbacks; original routing and regulatory memberships retained."}
    Path(output).with_suffix(".refit.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--opendrive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--spacing", type=float, default=1.0)
    args = parser.parse_args()
    if args.spacing <= 0:
        parser.error("--spacing must be positive")
    if args.output.resolve() == args.source.resolve():
        parser.error("Output must differ from source")
    report = refit(args.source, args.opendrive, args.output, args.spacing)
    print(f"Wrote {report['lanelets']} lanelets to {args.output}")


if __name__ == "__main__":
    main()
