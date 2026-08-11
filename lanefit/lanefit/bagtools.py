"""Bag utilities: trim parked periods out of a rosbag (raw serialized copy)."""
from __future__ import annotations

import logging
import math
import os

import yaml

from .config import Config
from .util import iter_messages, open_bag_reader

log = logging.getLogger("lanefit")


def trim_parked(bag: str, out_bag: str, cfg: Config, gnss_topic: str | None = None) -> dict:
    """Copy `bag` to `out_bag` without parked (long-stationary) periods.

    Keeps a stationary pre-roll before motion resumes (SLAM IMU init) and always
    copies latched/one-shot topics (tf_static, robot_description, <=N-msg topics).
    """
    gnss_topic = gnss_topic or cfg("topics.gnss")
    move_eps = float(cfg("trim_bag.move_eps"))
    min_park = float(cfg("trim_bag.min_park"))
    pre_roll = float(cfg("trim_bag.pre_roll"))
    keep_all_max = int(cfg("trim_bag.keep_all_max"))

    # pass 1: parked intervals from GNSS
    epochs = []
    lat0 = None
    for _, m, t_ns in iter_messages(bag, [gnss_topic]):
        if lat0 is None:
            lat0 = m.latitude
        epochs.append((t_ns,
                       math.radians(m.longitude) * 6378137.0 * math.cos(math.radians(lat0)),
                       math.radians(m.latitude) * 6356752.0))
    if len(epochs) < 10:
        raise RuntimeError(f"too few GNSS epochs on {gnss_topic}")

    cuts = []
    run_start = None
    prev = epochs[0]
    for cur in epochs[1:]:
        d = math.hypot(cur[1] - prev[1], cur[2] - prev[2])
        if d < move_eps:
            if run_start is None:
                run_start = prev[0]
        elif run_start is not None:
            if (prev[0] - run_start) / 1e9 >= min_park:
                cuts.append([run_start, prev[0]])
            run_start = None
        prev = cur
    if run_start is not None and (prev[0] - run_start) / 1e9 >= min_park:
        cuts.append([run_start, prev[0]])
    first = epochs[0][0]
    for c in cuts:
        if abs(c[0] - first) < 2e9:
            c[0] = 0                                   # parked from bag start
        c[1] = int(c[1] - pre_roll * 1e9)              # keep pre-roll before motion
    cuts = [c for c in cuts if c[1] > c[0]]
    if not cuts:
        log.info("no parked intervals >= %.0f s — nothing to trim", min_park)
        return {"cuts": 0}
    for c in cuts:
        log.info("cut [%s .. %+.1f s from first GNSS]",
                 "bag-start" if c[0] == 0 else f"{(c[0]-first)/1e9:+.1f}s",
                 (c[1] - first) / 1e9)

    def is_cut(t_ns: int) -> bool:
        return any(a <= t_ns < b for a, b in cuts)

    # pass 2: raw filtered copy
    from rosbag2_py import ConverterOptions, SequentialWriter, StorageOptions
    meta = yaml.safe_load(open(os.path.join(bag, "metadata.yaml")))
    counts = {t["topic_metadata"]["name"]: t["message_count"]
              for t in meta["rosbag2_bagfile_information"]["topics_with_message_count"]}
    keep_all = {"/tf_static", "/robot_description"} | \
               {n for n, c in counts.items() if c <= keep_all_max}

    if os.path.exists(out_bag):
        raise RuntimeError(f"{out_bag} already exists — remove it first")
    reader = open_bag_reader(bag)
    writer = SequentialWriter()
    writer.open(StorageOptions(uri=out_bag, storage_id="sqlite3"),
                ConverterOptions("cdr", "cdr"))
    for tm in reader.get_all_topics_and_types():
        writer.create_topic(tm)
    n_in = n_out = 0
    while reader.has_next():
        topic, data, t_ns = reader.read_next()
        n_in += 1
        if topic in keep_all or not is_cut(t_ns):
            writer.write(topic, data, t_ns)
            n_out += 1
        if n_in % 500_000 == 0:
            log.info("  %s read / %s kept", f"{n_in:,}", f"{n_out:,}")
    del writer
    log.info("trim done: %s -> %s messages (%.1f%%)", f"{n_in:,}", f"{n_out:,}",
             100 * n_out / max(n_in, 1))
    return {"cuts": len(cuts), "messages_in": n_in, "messages_out": n_out,
            "out_bag": out_bag}
