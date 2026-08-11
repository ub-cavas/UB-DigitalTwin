"""extract_trajectory stage: RTK-filtered GNSS trajectory projected into the xodr CRS."""
from __future__ import annotations

import csv
import logging

from .config import Config
from .runctx import RunContext
from .util import iter_messages
from .xodr_io import parse_xodr

log = logging.getLogger("lanefit")


def run(ctx: RunContext, cfg: Config) -> dict:
    header, _ = parse_xodr(ctx.xodr)
    proj = header["geo_reference"]
    if not proj:
        raise RuntimeError("xodr has no geoReference")
    from pyproj import Transformer
    tf = Transformer.from_crs("EPSG:4326", proj, always_xy=True)

    want_type = cfg("extract_trajectory.rtk_pos_type")
    want_status = cfg("extract_trajectory.ins_status_good")

    rows, n_total = [], 0
    for _, m, _ in iter_messages(ctx.bag, [cfg("topics.gnss")]):
        n_total += 1
        if m.pos_type.type != want_type or m.ins_status.status != want_status:
            continue
        x, y = tf.transform(m.longitude, m.latitude)
        stamp_ns = m.header.stamp.sec * 1_000_000_000 + m.header.stamp.nanosec
        rows.append([stamp_ns, m.latitude, m.longitude, m.height, x, y,
                     m.longitude_stdev, m.latitude_stdev, m.height_stdev,
                     m.roll, m.pitch, m.azimuth])
    rows.sort(key=lambda r: r[0])
    if len(rows) < 10:
        raise RuntimeError(f"only {len(rows)}/{n_total} RTK-fixed epochs — cannot georeference")

    out = ctx.path("extract_trajectory", "gnss_trajectory.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        # note: x_std pairs with longitude (east), y_std with latitude (north)
        w.writerow(["stamp_ns", "lat", "lon", "height_msl", "x_xodr", "y_xodr",
                    "x_stdev", "y_stdev", "height_stdev", "roll", "pitch", "azimuth"])
        w.writerows(rows)

    span = (rows[-1][0] - rows[0][0]) / 1e9
    xs = [r[4] for r in rows]
    ys = [r[5] for r in rows]
    log.info("trajectory: %d/%d RTK epochs, %.1f s, x[%.1f, %.1f] y[%.1f, %.1f]",
             len(rows), n_total, span, min(xs), max(xs), min(ys), max(ys))
    return {"epochs_total": n_total, "epochs_rtk": len(rows), "span_s": round(span, 1),
            "csv": out, "crs": proj}
