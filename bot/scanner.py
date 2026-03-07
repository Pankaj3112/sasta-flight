import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from fli.models import (
    Airport,
    DateSearchFilters,
    FlightSearchFilters,
    FlightSegment,
    PassengerInfo,
    SeatType,
    SortBy,
)
from fli.search import SearchDates, SearchFlights

from bot.config import DAYS_TO_SCAN, TOP_CHEAPEST

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    from_airport: str
    to_airport: str
    cheapest_price: float
    cheapest_travel_date: str
    cheapest_airline: str | None
    cheapest_departure: str | None
    cheapest_duration: int | None
    cheapest_stops: int | None
    top_days: list[dict]
    avg_price: float
    min_price: float
    max_price: float


def _get_airport(code: str):
    """Try to get Airport enum, fall back to raw string."""
    try:
        return Airport[code.upper()]
    except KeyError:
        return code.upper()


async def scan_route_dates(from_code: str, to_code: str, days: int = DAYS_TO_SCAN) -> list[dict]:
    """Get prices for the next N days. Returns list of {date, price} sorted by price."""
    tomorrow = datetime.now() + timedelta(days=1)
    end_date = tomorrow + timedelta(days=days)

    filters = DateSearchFilters(
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[_get_airport(from_code), 0]],
                arrival_airport=[[_get_airport(to_code), 0]],
                travel_date=tomorrow.strftime("%Y-%m-%d"),
            )
        ],
        from_date=tomorrow.strftime("%Y-%m-%d"),
        to_date=end_date.strftime("%Y-%m-%d"),
    )

    search = SearchDates()
    results = await asyncio.to_thread(search.search, filters)

    date_prices = []
    for r in results:
        date_prices.append({
            "date": r.date[0].strftime("%Y-%m-%d"),
            "price": r.price,
        })

    return sorted(date_prices, key=lambda x: x["price"])


async def scan_flight_details(from_code: str, to_code: str, travel_date: str) -> dict | None:
    """Get flight details for a specific date. Returns cheapest flight info."""
    filters = FlightSearchFilters(
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[_get_airport(from_code), 0]],
                arrival_airport=[[_get_airport(to_code), 0]],
                travel_date=travel_date,
            )
        ],
        seat_type=SeatType.ECONOMY,
        sort_by=SortBy.CHEAPEST,
    )

    search = SearchFlights()
    flights = await asyncio.to_thread(search.search, filters)

    if not flights:
        return None

    flight = flights[0]
    leg = flight.legs[0] if flight.legs else None

    return {
        "price": flight.price,
        "airline": leg.airline.value if leg else None,
        "departure": leg.departure_datetime.strftime("%I:%M %p") if leg else None,
        "duration": flight.duration,
        "stops": flight.stops,
    }


async def scan_route(from_code: str, to_code: str) -> ScanResult | None:
    """Full scan: date prices + flight details for cheapest day."""
    try:
        date_prices = await scan_route_dates(from_code, to_code)
    except Exception:
        logger.exception(f"Failed to scan dates for {from_code} -> {to_code}")
        return None

    if not date_prices:
        logger.warning(f"No prices found for {from_code} -> {to_code}")
        return None

    top_days = date_prices[:TOP_CHEAPEST]
    all_prices = [d["price"] for d in date_prices]
    cheapest = top_days[0]

    # Get flight details for cheapest day
    details = None
    try:
        details = await scan_flight_details(from_code, to_code, cheapest["date"])
    except Exception:
        logger.exception(f"Failed to get flight details for {cheapest['date']}")

    return ScanResult(
        from_airport=from_code.upper(),
        to_airport=to_code.upper(),
        cheapest_price=cheapest["price"],
        cheapest_travel_date=cheapest["date"],
        cheapest_airline=details["airline"] if details else None,
        cheapest_departure=details["departure"] if details else None,
        cheapest_duration=details["duration"] if details else None,
        cheapest_stops=details["stops"] if details else None,
        top_days=top_days,
        avg_price=sum(all_prices) / len(all_prices),
        min_price=min(all_prices),
        max_price=max(all_prices),
    )
