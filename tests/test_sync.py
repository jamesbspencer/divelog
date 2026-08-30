"""Unit tests for Divelogs.org client, transformer, and one-way sync engine."""

from datetime import datetime
from pathlib import Path
import pytest
import responses

from divecloud.parser import DiveComputerInfo, DiveRecord, DiveSample, GasMix, TankInfo, ZXUParser
from divecloud.sync import OneWaySyncEngine, SyncResult
from divelogs.client import DivelogsClient
from divelogs.config import DivelogsConfig
from divelogs.exceptions import DivelogsAuthError, DivelogsUploadError
from divelogs.transformer import DiveTransformer


@pytest.fixture
def dl_config():
    return DivelogsConfig(
        api_url="https://divelogs.de/api",
        username="testuser",
        password="secretpassword",
        timeout=5.0,
    )


@pytest.fixture
def dl_client(dl_config):
    return DivelogsClient(dl_config)


@pytest.fixture
def sample_dive_record():
    return DiveRecord(
        duid="7165_4515_20260829103100_2",
        dive_number=2,
        start_time=datetime(2026, 8, 29, 10, 31, 0),
        duration_minutes=51.2,
        max_depth_feet=45.2,
        avg_depth_feet=27.5,
        min_temp_f=83.5,
        max_temp_f=84.0,
        computer=DiveComputerInfo(model="DSX", serial_number="4515", manufacturer="Apeks"),
        tank=TankInfo(
            start_pressure_psi=2970.0,
            end_pressure_psi=1065.0,
            gas_mix=GasMix(name="EAN32", o2_fraction=0.32, n2_fraction=0.68),
        ),
        samples=[
            DiveSample(time_seconds=0.0, depth_feet=0.0, temperature_f=84.0, pressure_psi=2970.0),
            DiveSample(time_seconds=20.0, depth_feet=15.0, temperature_f=83.5, pressure_psi=2900.0),
            DiveSample(time_seconds=40.0, depth_feet=45.2, temperature_f=83.5, pressure_psi=2500.0),
        ],
        site="Blue Hole",
        location="Belize",
    )


def test_dive_transformer(sample_dive_record):
    payload = DiveTransformer.transform_dive(sample_dive_record)

    assert payload["date"] == "2026-08-29"
    assert payload["time"] == "10:31:00"
    assert payload["duration"] == 3072  # 51.2 * 60
    assert payload["maxdepth"] == 13.78  # 45.2 ft in meters
    assert payload["meandepth"] == 8.38  # 27.5 ft in meters
    assert payload["depthtemp"] == 28.6  # 83.5 F in C
    assert payload["surfacetemp"] == 28.9  # 84.0 F in C
    assert payload["dc_model"] == "Apeks DSX"
    assert payload["divesite"] == "Blue Hole"
    assert payload["location"] == "Belize"

    # Tanks
    assert len(payload["tanks"]) == 1
    assert payload["tanks"][0]["o2"] == 32
    assert payload["tanks"][0]["he"] == 0
    assert payload["tanks"][0]["start_pressure"] == 204.8  # 2970 psi in bar
    assert payload["tanks"][0]["end_pressure"] == 73.4   # 1065 psi in bar

    # Samples
    assert payload["samplerate"] == 20
    assert len(payload["sampledata"]) == 3
    assert payload["sampledata"][0] == {"d": 0.0, "t": 28.9}
    assert payload["sampledata"][2]["d"] == 13.78


@responses.activate
def test_divelogs_auth_success(dl_client):
    responses.add(
        responses.POST,
        "https://divelogs.de/api/login",
        json={"status": "success", "bearer_token": "jwt_token_abc_123"},
        status=200,
    )

    token = dl_client.authenticate()
    assert token == "jwt_token_abc_123"
    assert dl_client.session.headers["Authorization"] == "Bearer jwt_token_abc_123"


@responses.activate
def test_divelogs_auth_failure(dl_client):
    responses.add(
        responses.POST,
        "https://divelogs.de/api/login",
        json={"status": "error", "message": "Invalid password"},
        status=401,
    )

    with pytest.raises(DivelogsAuthError):
        dl_client.authenticate()


@responses.activate
def test_divelogs_get_divelist(dl_client):
    dl_client._bearer_token = "jwt_token_123"

    mock_divelist = [
        {"id": 101, "number": 1, "date": "2026-08-29", "time": "08:41:00", "duration": 2500, "maxdepth": 15.4},
        {"id": 102, "number": 2, "date": "2026-08-29", "time": "10:31:00", "duration": 3076, "maxdepth": 13.8},
    ]

    responses.add(
        responses.GET,
        "https://divelogs.de/api/divelist",
        json=mock_divelist,
        status=200,
    )

    divelist = dl_client.get_divelist()
    assert len(divelist) == 2
    assert divelist[0]["id"] == 101


def test_sync_engine_deduplication(sample_dive_record):
    engine = OneWaySyncEngine()

    existing = [
        {"id": 1, "date": "2026-08-29", "time": "10:30:00"},  # 1 min diff -> duplicate
    ]
    assert engine.is_duplicate(sample_dive_record, existing, tolerance_minutes=2) is True

    existing_diff_day = [
        {"id": 2, "date": "2026-08-28", "time": "10:31:00"},
    ]
    assert engine.is_duplicate(sample_dive_record, existing_diff_day) is False


@responses.activate
def test_sync_engine_dry_run(tmp_path, sample_dive_record):
    dl_config = DivelogsConfig(username="", password="")
    dl_client = DivelogsClient(dl_config)
    engine = OneWaySyncEngine(divelogs_client=dl_client)

    result = engine.sync(local_dir=tmp_path, download_from_cloud=False, dry_run=True)
    assert result.total_found == 0
    assert result.is_dry_run is True


def test_gps_geocoder_decode():
    from divecloud.geocoder import GPSGeocoder

    # Test BAM binary angle measurement decoding
    lat, lng = GPSGeocoder.parse_gps_string("GPS=[1.1082911E9,-1.0296864E9],MINTEMP=83.5")
    assert lat is not None and lng is not None
    assert round(lat, 2) == 46.45
    assert round(lng, 2) == -86.31

    # Test invalid / zero GPS
    lat_zero, lng_zero = GPSGeocoder.parse_gps_string("GPS=[0.0,0.0],MINTEMP=80.0")
    assert lat_zero is None
    assert lng_zero is None
