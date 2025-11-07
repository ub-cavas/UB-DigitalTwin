#!/usr/bin/env python3
import carla
import sys

# --- Weather presets from carla.WeatherParameters ---
PRESETS = {
    "ClearNoon": carla.WeatherParameters.ClearNoon,
    "ClearSunset": carla.WeatherParameters.ClearSunset,
    "CloudyNoon": carla.WeatherParameters.CloudyNoon,
    "CloudySunset": carla.WeatherParameters.CloudySunset,
    "WetNoon": carla.WeatherParameters.WetNoon,
    "WetSunset": carla.WeatherParameters.WetSunset,
    "MidRainyNoon": carla.WeatherParameters.MidRainyNoon,
    "MidRainSunset": carla.WeatherParameters.MidRainSunset,
    "WetCloudyNoon": carla.WeatherParameters.WetCloudyNoon,
    "WetCloudySunset": carla.WeatherParameters.WetCloudySunset,
    "SoftRainNoon": carla.WeatherParameters.SoftRainNoon,
    "SoftRainSunset": carla.WeatherParameters.SoftRainSunset,
    "HardRainNoon": carla.WeatherParameters.HardRainNoon,
    "HardRainSunset": carla.WeatherParameters.HardRainSunset,
    "Default": carla.WeatherParameters.Default
}

def main():
    if len(sys.argv) < 2:
        print("Usage: python set_weather.py <WeatherName>")
        print("Available presets:")
        for name in PRESETS.keys():
            print("  -", name)
        sys.exit(1)

    weather_name = sys.argv[1]
    weather = PRESETS.get(weather_name, None)

    if weather is None:
        print(f"Unknown weather preset '{weather_name}'.")
        print("Valid options are:", ", ".join(PRESETS.keys()))
        sys.exit(1)

    try:
        client = carla.Client("localhost", 2000)
        client.set_timeout(5.0)
        world = client.get_world()

        world.set_weather(weather)
        print(f"✅ Weather set to: {weather_name}")

    except RuntimeError as e:
        print("❌ Error connecting to CARLA:", e)

if __name__ == "__main__":
    main()
