"""
Recovery / wellness read-only tools for Garmin Connect MCP Server

Adds the metrics garmin-workouts-mcp deliberately left out (it scopes itself to
activities + workouts): training readiness, HRV, body battery, sleep, stress,
resting heart rate, training status and race predictions. Read-only, same
garth/garminconnect client and token store as the rest of the server - no
extra auth step.
"""
import json

# The garmin_client will be set by the main file
garmin_client = None


def configure(client):
    """Configure the module with the Garmin client instance"""
    global garmin_client
    garmin_client = client


def _dump(payload, cdate: str, label: str) -> str:
    if payload is None or payload == []:
        return f"No {label} data found for {cdate}."
    return json.dumps({"date": cdate, label: payload}, indent=2, default=str)


def register_tools(app):
    """Register all recovery/wellness tools with the MCP server app"""

    @app.tool()
    async def get_training_readiness(cdate: str) -> str:
        """Get training readiness score and its contributing factors for a date

        Combines sleep, recovery time, HRV status, acute training load and
        stress into a single 0-100 readiness score. Use this before deciding
        whether to push a hard session or swap it for an easy/recovery one.

        Args:
            cdate: Date in YYYY-MM-DD format
        """
        try:
            data = garmin_client.get_training_readiness(cdate)
            return _dump(data, cdate, "training_readiness")
        except Exception as e:
            return f"Error retrieving training readiness: {str(e)}"

    @app.tool()
    async def get_hrv_status(cdate: str) -> str:
        """Get heart rate variability (HRV) status and overnight trend for a date

        Args:
            cdate: Date in YYYY-MM-DD format
        """
        try:
            data = garmin_client.get_hrv_data(cdate)
            return _dump(data, cdate, "hrv")
        except Exception as e:
            return f"Error retrieving HRV data: {str(e)}"

    @app.tool()
    async def get_body_battery(start_date: str, end_date: str = "") -> str:
        """Get Body Battery (energy reserve) levels between two dates

        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: Optional end date in YYYY-MM-DD format (defaults to start_date)
        """
        try:
            data = garmin_client.get_body_battery(start_date, end_date or None)
            if not data:
                return f"No Body Battery data found between {start_date} and {end_date or start_date}."
            return json.dumps({
                "start_date": start_date,
                "end_date": end_date or start_date,
                "body_battery": data
            }, indent=2, default=str)
        except Exception as e:
            return f"Error retrieving Body Battery data: {str(e)}"

    @app.tool()
    async def get_sleep(cdate: str) -> str:
        """Get sleep stages, duration and sleep score for a date

        Args:
            cdate: Date in YYYY-MM-DD format
        """
        try:
            data = garmin_client.get_sleep_data(cdate)
            return _dump(data, cdate, "sleep")
        except Exception as e:
            return f"Error retrieving sleep data: {str(e)}"

    @app.tool()
    async def get_body_weight(start_date: str, end_date: str = "") -> str:
        """Get body weight entries between two dates

        Useful for correlating pace/HR trends against bodyweight changes -
        e.g. distinguishing genuine aerobic fitness gains from the pace-at-HR
        improvement that comes from being lighter, or checking whether the
        profile weight behind Garmin's VO2max/race-time estimates is stale.
        Read-only (does not log weigh-ins).

        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: Optional end date in YYYY-MM-DD format (defaults to start_date)
        """
        try:
            data = garmin_client.get_weigh_ins(start_date, end_date or start_date)
            if not data:
                return f"No body weight data found between {start_date} and {end_date or start_date}."
            return json.dumps({
                "start_date": start_date,
                "end_date": end_date or start_date,
                "body_weight": data
            }, indent=2, default=str)
        except Exception as e:
            return f"Error retrieving body weight data: {str(e)}"

    @app.tool()
    async def get_stress(cdate: str) -> str:
        """Get all-day stress levels and time-in-stress-category breakdown for a date

        Args:
            cdate: Date in YYYY-MM-DD format
        """
        try:
            data = garmin_client.get_all_day_stress(cdate)
            return _dump(data, cdate, "stress")
        except Exception as e:
            return f"Error retrieving stress data: {str(e)}"

    @app.tool()
    async def get_resting_heart_rate(cdate: str) -> str:
        """Get resting heart rate for a date

        Args:
            cdate: Date in YYYY-MM-DD format
        """
        try:
            data = garmin_client.get_rhr_day(cdate)
            return _dump(data, cdate, "resting_heart_rate")
        except Exception as e:
            return f"Error retrieving resting heart rate: {str(e)}"

    @app.tool()
    async def get_training_status(cdate: str) -> str:
        """Get training status (e.g. productive, peaking, overreaching, detraining)
        plus VO2max and acute training load for a date

        Args:
            cdate: Date in YYYY-MM-DD format
        """
        try:
            data = garmin_client.get_training_status(cdate)
            return _dump(data, cdate, "training_status")
        except Exception as e:
            return f"Error retrieving training status: {str(e)}"

    @app.tool()
    async def get_calendar_events(start_year: int, start_month: int, months: int = 1) -> str:
        """Get races/events from the Garmin Connect calendar (the manually-added "Events"
        feature - distinct from activities and scheduled workouts).

        Scans one or more calendar months starting at start_year/start_month and returns
        every entry from that feature (itemType=="event"), with title, date, location,
        distance, and registration URL. Also includes Garmin's own "is_race" flag, which
        is unreliable on its own - it is true for some registered races (e.g. road
        marathons) but false for others that are just as real (e.g. a 100km hiking/trail
        ultra), so it is reported as extra info rather than used to filter results.

        Args:
            start_year: Year to start scanning (e.g. 2026)
            start_month: Month to start scanning, 1-12
            months: How many consecutive months to scan starting from start_year/start_month (default 1, max 24)
        """
        try:
            months = max(1, min(months, 24))
            events = {}
            year, month = start_year, start_month
            for _ in range(months):
                url = f"calendar-service/year/{year}/month/{month - 1}"
                response = garmin_client.garth.get("connectapi", url)
                data = response.json()
                for item in data.get("calendarItems", []):
                    if item.get("itemType") == "event":
                        target = item.get("completionTarget") or {}
                        # calendar-service month views overlap at the edges (a given
                        # event can appear in two consecutive months' results), so
                        # dedupe by Garmin's own event id.
                        events[item.get("id")] = {
                            "title": item.get("title"),
                            "date": item.get("date"),
                            "start_time": (item.get("eventTimeLocal") or {}).get("startTimeHhMm"),
                            "location": item.get("location"),
                            "distance": target.get("value"),
                            "distance_unit": target.get("unit"),
                            "is_race": item.get("isRace"),
                            "url": item.get("url"),
                        }
                month += 1
                if month > 12:
                    month = 1
                    year += 1

            events = sorted(events.values(), key=lambda e: e.get("date") or "")

            if not events:
                return f"No races/events found in the {months} month(s) starting {start_year}-{start_month:02d}."

            return json.dumps({"count": len(events), "events": events}, indent=2, default=str)
        except Exception as e:
            return f"Error retrieving calendar events: {str(e)}"

    @app.tool()
    async def get_race_predictions() -> str:
        """Get Garmin's predicted race times (5K, 10K, half marathon, marathon)
        based on recent training and fitness trend
        """
        try:
            data = garmin_client.get_race_predictions()
            if not data:
                return "No race predictions available."
            return json.dumps({"race_predictions": data}, indent=2, default=str)
        except Exception as e:
            return f"Error retrieving race predictions: {str(e)}"

    return app
