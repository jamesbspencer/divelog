"""Parser for DiveCloud / Pelagic / DiverLog .zxu dive log files."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from divecloud.geocoder import GPSGeocoder

logger = logging.getLogger(__name__)


@dataclass
class DiveSample:
    """A single time-series sample point in a dive profile."""
    time_seconds: float
    depth_feet: float
    temperature_f: Optional[float] = None
    pressure_psi: Optional[float] = None


@dataclass
class GasMix:
    """Gas mix definition for a dive."""
    id: str = "air"
    name: str = "Air"
    o2_fraction: float = 0.21
    he_fraction: float = 0.0
    n2_fraction: float = 0.79


@dataclass
class TankInfo:
    """Scuba tank and gas consumption information."""
    start_pressure_psi: Optional[float] = None
    end_pressure_psi: Optional[float] = None
    volume_cuft: Optional[float] = None
    working_pressure_psi: Optional[float] = None
    gas_mix: GasMix = field(default_factory=GasMix)


@dataclass
class DiveComputerInfo:
    """Dive computer hardware and software metadata."""
    model: str = "Unknown"
    serial_number: str = "Unknown"
    manufacturer: str = "Apeks"
    firmware: str = ""


@dataclass
class DiveRecord:
    """Complete parsed dive record."""
    duid: str
    dive_number: int = 1
    start_time: Optional[datetime] = None
    duration_minutes: float = 0.0
    max_depth_feet: float = 0.0
    avg_depth_feet: float = 0.0
    min_temp_f: Optional[float] = None
    max_temp_f: Optional[float] = None
    computer: DiveComputerInfo = field(default_factory=DiveComputerInfo)
    tank: TankInfo = field(default_factory=TankInfo)
    samples: List[DiveSample] = field(default_factory=list)
    site: str = ""
    location: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    notes: str = ""
    raw_filename: str = ""


class ZXUParser:
    """Parser for .zxu dive files."""

    @staticmethod
    def _parse_kv_string(text: str) -> dict[str, str]:
        """Parse key=value comma-separated string like 'DIVENO=2,MAXDEPTH=45.2'."""
        result = {}
        parts = text.split(",")
        for part in parts:
            if "=" in part:
                k, v = part.split("=", 1)
                result[k.strip().upper()] = v.strip()
        return result

    @classmethod
    def parse_file(cls, file_path: Path | str) -> DiveRecord:
        """Parse a .zxu file (zip archive or raw text) into a DiveRecord."""
        path = Path(file_path)
        raw_text = ""

        # Handle zip archives (.zxu files are zipped)
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                if not names:
                    raise ValueError(f"Empty zip archive: {path}")
                raw_text = z.read(names[0]).decode("utf-8", errors="replace")
        else:
            raw_text = path.read_text(encoding="utf-8", errors="replace")

        return cls.parse_raw_text(raw_text, filename=path.name)

    @classmethod
    def parse_raw_text(cls, raw_text: str, filename: str = "") -> DiveRecord:
        """Parse raw text from ZXU format into a DiveRecord."""
        record = DiveRecord(duid=filename.replace(".zxu", ""), raw_filename=filename)

        # 1. Parse Application Record <AQUALUNG>...</AQUALUNG>
        zar_start = raw_text.find("ZAR{")
        if zar_start != -1:
            zar_end = raw_text.find("}", zar_start)
            if zar_end != -1:
                zar_xml_str = raw_text[zar_start + 4 : zar_end].strip()
                cls._parse_aqualung_xml(zar_xml_str, record)

        # 2. Parse Dive Header (ZDH)
        zdh_match = re.search(r"^ZDH\|([^|\n\r]*)\|([^|\n\r]*)\|([^|\n\r]*)\|([^|\n\r]*)\|([^|\n\r]*)\|([^|\n\r]*)", raw_text, re.M)
        if zdh_match:
            try:
                if zdh_match.group(2):
                    record.dive_number = int(zdh_match.group(2))
            except ValueError:
                pass

            dt_str = zdh_match.group(5).strip()
            if dt_str and len(dt_str) >= 14:
                try:
                    record.start_time = datetime.strptime(dt_str[:14], "%Y%m%d%H%M%S")
                except ValueError:
                    pass

            try:
                if zdh_match.group(6):
                    # Group 6 is surface/start temperature in Fahrenheit
                    temp_f = float(zdh_match.group(6))
                    if 32.0 <= temp_f <= 115.0 and record.max_temp_f is None:
                        record.max_temp_f = temp_f
            except ValueError:
                pass

        # 3. Parse Dive Profile Samples (ZDP{...})
        zdp_start = raw_text.find("ZDP{")
        if zdp_start != -1:
            zdp_end = raw_text.find("ZDP}", zdp_start)
            if zdp_end != -1:
                zdp_block = raw_text[zdp_start + 4 : zdp_end].strip()
                record.samples = cls._parse_zdp_samples(zdp_block)

        # Compute max/avg depth and min temp if not set from headers
        if record.samples:
            sample_depths = [s.depth_feet for s in record.samples if s.depth_feet > 0]
            if sample_depths and record.max_depth_feet == 0.0:
                record.max_depth_feet = max(sample_depths)
            if sample_depths and record.avg_depth_feet == 0.0:
                record.avg_depth_feet = sum(sample_depths) / len(sample_depths)

            temps = [s.temperature_f for s in record.samples if s.temperature_f is not None]
            if temps:
                if record.min_temp_f is None:
                    record.min_temp_f = min(temps)
                if record.max_temp_f is None:
                    record.max_temp_f = max(temps)

        if record.duration_minutes == 0.0 and record.samples:
            record.duration_minutes = record.samples[-1].time_seconds / 60.0

        return record

    @classmethod
    def _parse_aqualung_xml(cls, xml_str: str, record: DiveRecord) -> None:
        """Parse XML tags in the AQUALUNG section."""
        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError as e:
            logger.debug("Failed to parse AQUALUNG XML: %s", e)
            return

        duid = root.findtext("DUID")
        if duid:
            record.duid = duid

        dive_dt = root.findtext("DIVE_DT")
        if dive_dt and len(dive_dt) >= 14 and not record.start_time:
            try:
                record.start_time = datetime.strptime(dive_dt[:14], "%Y%m%d%H%M%S")
            except ValueError:
                pass

        # Computer info
        record.computer.model = root.findtext("PDC_MODEL", "DSX")
        record.computer.serial_number = root.findtext("PDC_SERIAL", "Unknown")
        record.computer.manufacturer = root.findtext("MANUFACTURER", "Apeks")
        record.computer.firmware = root.findtext("PDC_FIRMWARE", "")

        # Metadata & Location
        record.site = root.findtext("SITE", "") or ""
        raw_location = root.findtext("LOCATION", "") or ""
        record.notes = root.findtext("NOTES", "") or ""

        # Decode GPS & Reverse Geocode
        lat, lng = GPSGeocoder.parse_gps_string(raw_location)
        if lat is not None and lng is not None:
            record.latitude = lat
            record.longitude = lng
            resolved = GPSGeocoder.reverse_geocode(lat, lng)
            record.location = resolved or f"GPS: {lat}, {lng}"
        elif "GPS=[" in raw_location:
            record.location = ""
        else:
            record.location = raw_location

        if not record.notes and "GPS=[" in raw_location and record.location:
            record.notes = f"Coordinates: {lat}, {lng}" if lat is not None else ""

        # Parse DIVESTATS
        divestats_str = root.findtext("DIVESTATS", "") or ""
        if divestats_str:
            stats = cls._parse_kv_string(divestats_str)
            if "DIVENO" in stats:
                try:
                    record.dive_number = int(stats["DIVENO"])
                except ValueError:
                    pass
            if "MAXDEPTH" in stats:
                try:
                    record.max_depth_feet = float(stats["MAXDEPTH"])
                except ValueError:
                    pass
            if "MINTEMP" in stats:
                try:
                    record.min_temp_f = float(stats["MINTEMP"])
                except ValueError:
                    pass
            if "EDT" in stats and record.duration_minutes == 0.0:
                edt_str = stats["EDT"].strip()
                if len(edt_str) == 6:
                    try:
                        hours = int(edt_str[:2])
                        mins = int(edt_str[2:4])
                        secs = int(edt_str[4:6])
                        record.duration_minutes = (hours * 60.0) + mins + (secs / 60.0)
                    except ValueError:
                        pass

        # Parse TANK
        tank_str = root.findtext("TANK", "") or ""
        if tank_str:
            tank_kv = cls._parse_kv_string(tank_str)
            if "STARTPRESSURE" in tank_kv:
                try:
                    record.tank.start_pressure_psi = float(tank_kv["STARTPRESSURE"])
                except ValueError:
                    pass
            if "ENDPRESSURE" in tank_kv:
                try:
                    record.tank.end_pressure_psi = float(tank_kv["ENDPRESSURE"])
                except ValueError:
                    pass
            if "FO2" in tank_kv:
                try:
                    fo2 = float(tank_kv["FO2"])
                    frac = fo2 / 100.0 if fo2 > 1.0 else fo2
                    if frac < 0.20 or frac > 1.0:
                        frac = 0.21
                    record.tank.gas_mix.o2_fraction = frac
                    record.tank.gas_mix.n2_fraction = round(1.0 - frac, 3)
                    if abs(frac - 0.21) < 0.01:
                        record.tank.gas_mix.name = "Air"
                    else:
                        record.tank.gas_mix.name = f"EAN{int(round(frac * 100))}"
                except ValueError:
                    pass
            if "AVGDEPTH" in tank_kv and record.avg_depth_feet == 0.0:
                try:
                    record.avg_depth_feet = float(tank_kv["AVGDEPTH"])
                except ValueError:
                    pass
            if "DIVETIME" in tank_kv:
                try:
                    divetime_val = float(tank_kv["DIVETIME"])
                    if divetime_val > 0.0:
                        record.duration_minutes = divetime_val
                except ValueError:
                    pass

    @classmethod
    def _parse_zdp_samples(cls, zdp_text: str) -> List[DiveSample]:
        """Parse line-by-line samples from the ZDP profile block."""
        samples: List[DiveSample] = []
        lines = [line.strip() for line in zdp_text.split("\n") if line.strip()]

        current_depth = 0.0
        current_temp = None
        current_press = None

        for line in lines:
            parts = line.split("|")
            if len(parts) < 3:
                continue

            # Index 1: Time in minutes
            try:
                time_mins = float(parts[1]) if parts[1] else 0.0
                time_sec = time_mins * 60.0
            except ValueError:
                continue

            # Index 2: Depth in feet
            if len(parts) > 2 and parts[2]:
                try:
                    current_depth = float(parts[2])
                except ValueError:
                    pass

            # Index 8: Temperature in Fahrenheit
            if len(parts) > 8 and parts[8]:
                try:
                    current_temp = float(parts[8])
                except ValueError:
                    pass

            # Index 10: Tank pressure in PSI
            if len(parts) > 10 and parts[10]:
                try:
                    current_press = float(parts[10])
                except ValueError:
                    pass

            samples.append(DiveSample(
                time_seconds=time_sec,
                depth_feet=current_depth,
                temperature_f=current_temp,
                pressure_psi=current_press,
            ))

        return samples
