"""Run the server with `python -m garmin_workouts_mcp`.

Same entry point as the garmin-workouts-mcp launcher. Handy where the generated, unsigned
launcher .exe is blocked (for example by Windows Smart App Control), because the signed
python.exe can still run it.
"""
from garmin_workouts_mcp import main

if __name__ == "__main__":
    main()
