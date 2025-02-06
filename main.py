import sentry_sdk
import typer

import noaa.gefs.forecast.cli as noaa_gefs_forecast
from common.config import Config

if Config.is_sentry_enabled:
    sentry_sdk.init(
        dsn=Config.sentry_dsn,
        environment=Config.env,
    )


app = typer.Typer(pretty_exceptions_show_locals=False)
app.add_typer(noaa_gefs_forecast.app, name="noaa-gefs-forecast")

if __name__ == "__main__":
    app()
