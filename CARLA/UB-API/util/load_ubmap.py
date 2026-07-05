#!/usr/bin/env python

"""
Configure and load the UB map.

"""

import carla

def main():
    client = carla.Client('localhost', 2000)
    client.set_timeout(10.0)

    print("Load map 'UBAutonomousProvingGrounds'")
    world = client.load_world('UBAutonomousProvingGrounds')

    spectator = world.get_spectator()

    transform = carla.Transform(
        carla.Location(
            x = 0,
            y = -73,
            z = 123.0
        ),
        carla.Rotation(
            pitch = -45,
            yaw = -180,
            roll = 0
        )
    )

    spectator.set_transform(transform)

if __name__ == '__main__':
    try:
        main()

    except KeyboardInterrupt:
        print('\nCancelled by user. Bye!')
