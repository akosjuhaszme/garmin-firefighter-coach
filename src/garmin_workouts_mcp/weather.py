"""
Weather forecast tool for Garmin MCP Server

Not a Garmin API - uses OpenWeatherMap's free "5 day / 3-hour forecast"
endpoint to flag outdoor-training hazards (ice, extreme heat, possible
storm/hail) for the days a weekly plan is about to schedule sessions on.
Requires OPENWEATHER_API_KEY to be set as an environment variable.
"""
import json
import os
from collections import defaultdict

import requests

FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"

# OpenWeatherMap condition code groups: https://openweathermap.org/weather-conditions
_THUNDERSTORM_CODE_RANGE = range(200, 233)


def register_tools(app):
    """Register weather tools with the MCP server app"""

    @app.tool()
    async def get_weather_forecast(
        location: str = "Isaszeg,HU",
        days: int = 5,
        heat_threshold_c: float = 28.0,
        ice_threshold_c: float = 2.0,
    ) -> str:
        """Get a daily weather forecast with outdoor-training hazard flags

        Aggregates OpenWeatherMap's 3-hour forecast slices into per-day summaries
        (min/max temp, precipitation, conditions) and flags:
        - ICE_RISK: day's minimum temperature at or below ice_threshold_c (slip
          hazard for outdoor sessions, especially before sunrise/after sunset)
        - EXTREME_HEAT: day's maximum temperature at or above heat_threshold_c
        - POSSIBLE_STORM_HAIL: a thunderstorm is forecast that day. This is an
          approximation - OpenWeatherMap's free tier has no dedicated hail code,
          so any thunderstorm (which can produce hail) is flagged rather than
          hail specifically.

        Covers up to 5 days ahead (the limit of OpenWeatherMap's free forecast
        endpoint - the paid One Call API would be needed for longer range).

        Args:
            location: City name and ISO country code, e.g. "Isaszeg,HU" (default)
            days: How many days ahead to summarize, 1-5 (default 5)
            heat_threshold_c: Max-temp threshold in Celsius for the EXTREME_HEAT flag (default 28.0)
            ice_threshold_c: Min-temp threshold in Celsius for the ICE_RISK flag (default 2.0)
        """
        api_key = os.environ.get("OPENWEATHER_API_KEY")
        if not api_key:
            return (
                "No OpenWeatherMap API key configured. Set the OPENWEATHER_API_KEY "
                "environment variable (get a free key at https://openweathermap.org/api) "
                "and restart this MCP server."
            )

        days = max(1, min(days, 5))

        try:
            response = requests.get(
                FORECAST_URL,
                params={"q": location, "appid": api_key, "units": "metric"},
                timeout=10,
            )
        except requests.exceptions.RequestException as e:
            return f"Error contacting OpenWeatherMap: {str(e)}"

        if response.status_code == 401:
            return "OpenWeatherMap rejected the API key (401 Unauthorized) - check OPENWEATHER_API_KEY."
        if response.status_code == 404:
            return f"Location '{location}' not found by OpenWeatherMap - check spelling/format (e.g. 'City,CountryCode')."
        if response.status_code != 200:
            return f"OpenWeatherMap request failed: HTTP {response.status_code} - {response.text[:200]}"

        data = response.json()
        by_date = defaultdict(list)
        for slice_ in data.get("list", []):
            date = slice_.get("dt_txt", "")[:10]
            if date:
                by_date[date].append(slice_)

        daily = []
        for date in sorted(by_date.keys())[:days]:
            slices = by_date[date]
            temps = [s["main"]["temp"] for s in slices if "main" in s]
            conditions = sorted({
                s["weather"][0]["main"]
                for s in slices if s.get("weather")
            })
            weather_ids = [
                s["weather"][0]["id"]
                for s in slices if s.get("weather")
            ]
            rain_mm = sum(s.get("rain", {}).get("3h", 0.0) for s in slices)
            snow_mm = sum(s.get("snow", {}).get("3h", 0.0) for s in slices)
            min_temp = min(temps) if temps else None
            max_temp = max(temps) if temps else None

            hazards = []
            if min_temp is not None and min_temp <= ice_threshold_c:
                hazards.append("ICE_RISK")
            if max_temp is not None and max_temp >= heat_threshold_c:
                hazards.append("EXTREME_HEAT")
            if any(wid in _THUNDERSTORM_CODE_RANGE for wid in weather_ids):
                hazards.append("POSSIBLE_STORM_HAIL")

            daily.append({
                "date": date,
                "min_temp_c": round(min_temp, 1) if min_temp is not None else None,
                "max_temp_c": round(max_temp, 1) if max_temp is not None else None,
                "conditions": conditions,
                "rain_mm": round(rain_mm, 1),
                "snow_mm": round(snow_mm, 1),
                "hazards": hazards,
            })

        return json.dumps({
            "location": data.get("city", {}).get("name", location),
            "days": daily,
        }, indent=2, default=str)

    return app
