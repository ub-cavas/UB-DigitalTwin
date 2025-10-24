# scenario_clock.py
import time, json, redis

r = redis.Redis()
DT = float(r.hget("sim:config","tick_dt") or 0.05)
t0 = time.time()
n = 0

while True:
    t = n * DT
    r.hset("sim:tick", mapping={"t": t, "n": n})
    r.publish("chan:tick", json.dumps({"t": t, "n": n}))
    time.sleep(max(0.0, t0 + (n+1)*DT - time.time()))
    n += 1

