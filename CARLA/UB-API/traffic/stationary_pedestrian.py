#!/usr/bin/env python3
import carla
import random
import time
import sys

def main():
    client = carla.Client("localhost", 2000)
    client.set_timeout(10.0)
    world = client.get_world()
    blueprints = world.get_blueprint_library()

    walker = None

    try:
        # --- Spawn pedestrian ---
        walker_bp = random.choice(blueprints.filter("walker.pedestrian.*"))
        if walker_bp.has_attribute("is_invincible"):
            walker_bp.set_attribute("is_invincible", "true")

        spawn_point = carla.Transform(
            carla.Location(x=-155.0, y=2.0, z=1.0),
            carla.Rotation(yaw=0)
        )

        walker = world.try_spawn_actor(walker_bp, spawn_point)
        if walker is None:
            print("❌ Could not spawn pedestrian at that location.")
            return

        print(f"✅ Spawned pedestrian ID {walker.id} at {spawn_point.location}")

        # Make pedestrian stationary
        walker.set_simulate_physics(True)
        walker.apply_control(carla.WalkerControl())

        print("🚶 Pedestrian spawned and stationary.")
        print("🎥 You can now freely move the spectator camera in the simulator.")
        print("▶️ Press Ctrl+C to stop and clean up.")

        # --- Handle sync/async modes ---
        settings = world.get_settings()
        synchronous = settings.synchronous_mode
        print(f"⏱️ Synchronous mode: {synchronous}")

        # --- Keep alive until Ctrl+C ---
        while True:
            if synchronous:
                # In synchronous mode, just wait for next tick (no manual tick)
                world.wait_for_tick()
            else:
                # Async mode: also wait_for_tick, small sleep for CPU efficiency
                world.wait_for_tick()
                time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n👋 Interrupted by user.")
    finally:
        if walker is not None:
            try:
                walker.destroy()
                print("🧹 Pedestrian destroyed. Done!")
            except Exception as e:
                print(f"⚠️ Could not destroy walker: {e}")
        sys.exit(0)


if __name__ == "__main__":
    main()