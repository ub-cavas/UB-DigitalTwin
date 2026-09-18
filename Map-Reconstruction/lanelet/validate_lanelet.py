#!/usr/bin/env python3
"""Check local Lanelet geometry, Lanelet2 loading, and routing preservation.

Requires the refitter's dependencies plus lanelet2, Shapely, and Matplotlib.
No server is started. Outputs JSON evidence and an overview PNG.
"""

import argparse
import json
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

import lanelet2 as ll
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pyproj import Transformer
from shapely.geometry import LineString, Polygon
from shapely.validation import explain_validity

from refit_lanelet import read_map, tags


def load_local(path, georef):
    """Give vanilla Lanelet2 geographic coordinates for Autoware Local maps."""
    root = ET.parse(path).getroot()
    transform = Transformer.from_crs(georef, "EPSG:4326", always_xy=True)
    for n in root.findall("node"):
        values = tags(n)
        lon, lat = transform.transform(float(values["local_x"]), float(values["local_y"]))
        n.set("lat", str(lat))
        n.set("lon", str(lon))
    lon, lat = transform.transform(0, 0)
    projector = ll.projection.UtmProjector(ll.io.Origin(lat, lon))
    with tempfile.TemporaryDirectory() as directory:
        normalized = Path(directory) / "map.osm"
        ET.ElementTree(root).write(normalized, encoding="utf-8", xml_declaration=True)
        road_map, errors = ll.io.loadRobust(str(normalized), projector)
    # Check geometry in the actual local metric coordinates, after the parser
    # has determined the orientation of each shared boundary.
    for point in road_map.pointLayer:
        point.x = float(point.attributes["local_x"])
        point.y = float(point.attributes["local_y"])
    rules = ll.traffic_rules.create(ll.traffic_rules.Locations.Germany,
                                   ll.traffic_rules.Participants.Vehicle)
    graph = ll.routing.RoutingGraph(road_map, rules)
    edges = {(lane.id, following.id) for lane in road_map.laneletLayer
             for following in graph.following(lane)}
    return road_map, graph, errors, edges


def validate(source, candidate, xodr, report_path):
    georef = ET.parse(xodr).getroot().findtext("header/geoReference")
    before, graph_before, errors_before, edges_before = load_local(source, georef)
    after, graph, errors, edges = load_local(candidate, georef)
    root, nodes, xy, ways, refs, points = read_map(candidate)
    problems = []
    polygons = {}
    max_spacing = 0.0
    widths = []
    for lane in after.laneletLayer:
        left = np.array([[p.x, p.y] for p in lane.leftBound])
        right = np.array([[p.x, p.y] for p in lane.rightBound])
        polygon = Polygon(np.r_[left, right[::-1]])
        polygons[lane.id] = polygon
        if not polygon.is_valid or polygon.area <= 0:
            problems.append(f"Lanelet {lane.id}: {explain_validity(polygon)}")
        for boundary in (left, right):
            max_spacing = max(max_spacing, float(np.linalg.norm(np.diff(boundary, axis=0), axis=1).max()))
        widths.append(LineString(left).distance(LineString(right)))
        center = LineString([(p.x, p.y) for p in lane.centerline])
        if not polygon.buffer(1e-5).covers(center):
            problems.append(f"Lanelet {lane.id}: centerline leaves its polygon")
    source_root = ET.parse(source).getroot()
    original_relations = {r.get("id"): r for r in source_root.findall("relation")}
    current_relations = {r.get("id"): r for r in root.findall("relation")}
    semantics_equal = (original_relations.keys() == current_relations.keys() and all(
        tags(original_relations[i]) == tags(current_relations[i]) and
        [m.attrib for m in original_relations[i].findall("member")] ==
        [m.attrib for m in current_relations[i].findall("member")]
        for i in original_relations))
    if not semantics_equal:
        problems.append("Original lanelet/regulatory memberships or tags changed")
    if edges != edges_before:
        problems.append("Routing edges differ from the source map")
    if max_spacing > 1.001:
        problems.append("Boundary point spacing exceeds 1 m")
    stop_lines = []
    for r in root.findall("relation"):
        if tags(r).get("type") != "lanelet":
            continue
        for member in r.findall("member[@role='regulatory_element']"):
            rule = current_relations[member.get("ref")]
            for line in rule.findall("member[@role='ref_line']"):
                ls = LineString(points[line.get("ref")])
                intersection = polygons[int(r.get("id"))].intersection(ls)
                if intersection.length < 0.9 * ls.length:
                    problems.append(f"Stop line {line.get('ref')} does not lie across its lanelet")
                stop_lines.append(int(line.get("ref")))
    for issue in list(errors) + list(graph.checkValidity(False)):
        problems.append(str(issue))
    report = {
        "passed": not problems, "problems": problems,
        "lanelets": len(after.laneletLayer), "regulatory_elements": len(after.regulatoryElementLayer),
        "nodes": len(nodes), "ways": len(ways), "routing_edges": len(edges),
        "routing_edges_preserved": edges == edges_before,
        "relations_and_tags_preserved": semantics_equal,
        "load_errors": list(errors), "baseline_load_errors": list(errors_before),
        "routing_errors": list(graph.checkValidity(False)),
        "valid_polygons": sum(p.is_valid for p in polygons.values()),
        "max_boundary_sample_spacing_m": max_spacing,
        "minimum_boundary_separation_m": float(min(widths)),
        "stop_lines_checked": sorted(stop_lines),
        "entry_lanelets": sorted(l.id for l in after.laneletLayer if not graph.previous(l)),
        "exit_lanelets": sorted(l.id for l in after.laneletLayer if not graph.following(l)),
        "scope": "Offline geometry and routing checks; not an Autoware driving test.",
        "routing_rules": "Lanelet2 Germany/Vehicle (available upstream rule set), compared identically before and after.",
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    fig = plt.figure(figsize=(16, 9), facecolor="#f8fafb")
    grid = fig.add_gridspec(2, 3, width_ratios=[1.35, 1.35, 1])
    overview = fig.add_subplot(grid[:, :2])
    details = [fig.add_subplot(grid[0, 2]), fig.add_subplot(grid[1, 2])]
    for ax in [overview, *details]:
        for lane in before.laneletLayer:
            for bound in [lane.leftBound, lane.rightBound]:
                ax.plot([p.x for p in bound], [p.y for p in bound], color="#aeb8c0", lw=0.8)
        for polygon in polygons.values():
            ax.fill(*polygon.exterior.xy, color="#008da0", alpha=0.06)
            ax.plot(*polygon.exterior.xy, color="#007f8b", lw=0.85)
        for wid in stop_lines:
            p = points[str(wid)]
            ax.plot(p[:, 0], p[:, 1], color="#d55336", lw=1.7)
        ax.set_aspect("equal")
        ax.set_facecolor("white")
        ax.grid(alpha=0.15)
        ax.set_xlabel("Local x (m)")
        ax.set_ylabel("Local y (m)")
    overview.set_title("Full proving-ground coverage", loc="left", fontsize=13)
    details[0].set(xlim=(-327, -291), ylim=(-14, 21), title="Central junction")
    details[1].set(xlim=(-238, -182), ylim=(-14, 22), title="Widened one-way approaches")
    fig.suptitle("UB v1.1.0 • Lanelet refit", fontsize=21, x=0.06, ha="left")
    fig.text(0.06, 0.925, "Teal: updated map    Gray: v1.0.0    Orange: stop lines", fontsize=11)
    fig.text(0.06, 0.025, f"{len(after.laneletLayer)} lanelets · {len(stop_lines)} stop lines · {len(edges)} preserved route connections · Offline validation", fontsize=11)
    fig.subplots_adjust(left=0.06, right=0.97, bottom=0.09, top=0.89, wspace=0.28, hspace=0.38)
    fig.savefig(report_path.with_suffix(".png"), dpi=150)
    plt.close(fig)
    print(json.dumps(report, indent=2))
    if problems:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--opendrive", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    validate(args.source, args.candidate, args.opendrive, args.report)
