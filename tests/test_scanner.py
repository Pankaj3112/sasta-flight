import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from bot.scanner import scan_route_dates, scan_flight_details, ScanResult


@pytest.fixture
def mock_date_results():
    """Simulate fli SearchDates response."""
    results = []
    for i, price in enumerate([5000, 3200, 4500, 3800, 6000, 3500, 4200], start=1):
        mock = MagicMock()
        mock.date = [datetime(2026, 4, i)]
        mock.price = price
        results.append(mock)
    return results


@pytest.fixture
def mock_flight_results():
    """Simulate fli SearchFlights response."""
    leg = MagicMock()
    leg.airline.value = "IndiGo"
    leg.departure_datetime = datetime(2026, 4, 2, 6, 0)
    leg.arrival_datetime = datetime(2026, 4, 2, 8, 45)
    leg.departure_airport.value = "ATQ"
    leg.arrival_airport.value = "BOM"

    flight = MagicMock()
    flight.price = 3200
    flight.duration = 165
    flight.stops = 0
    flight.legs = [leg]
    return [flight]


@pytest.mark.asyncio
async def test_scan_route_dates(mock_date_results):
    with patch("bot.scanner.SearchDates") as MockSearch:
        MockSearch.return_value.search.return_value = mock_date_results
        result = await scan_route_dates("ATQ", "BOM", days=7)

    assert len(result) == 7
    assert result[0]["price"] == 3200  # sorted cheapest first
    assert result[0]["date"] == "2026-04-02"


@pytest.mark.asyncio
async def test_scan_flight_details(mock_flight_results):
    with patch("bot.scanner.SearchFlights") as MockSearch:
        MockSearch.return_value.search.return_value = mock_flight_results
        result = await scan_flight_details("ATQ", "BOM", "2026-04-02")

    assert result["price"] == 3200
    assert result["airline"] == "IndiGo"
    assert result["duration"] == 165
    assert result["stops"] == 0


@pytest.mark.asyncio
async def test_scan_route_dates_empty():
    with patch("bot.scanner.SearchDates") as MockSearch:
        MockSearch.return_value.search.return_value = []
        result = await scan_route_dates("ATQ", "BOM", days=7)

    assert result == []


@pytest.mark.asyncio
async def test_scan_route_full(mock_date_results, mock_flight_results):
    with patch("bot.scanner.SearchDates") as MockDates, \
         patch("bot.scanner.SearchFlights") as MockFlights:
        MockDates.return_value.search.return_value = mock_date_results
        MockFlights.return_value.search.return_value = mock_flight_results

        result = await scan_route("ATQ", "BOM")

    assert result is not None
    assert result.cheapest_price == 3200
    assert result.cheapest_airline == "IndiGo"
    assert len(result.top_days) == 5


# Import scan_route here to avoid import issues at top
from bot.scanner import scan_route
