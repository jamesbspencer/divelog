"""Transformer to convert DiveRecord into Divelogs.org API JSON payload."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from divecloud.parser import DiveRecord, DiveSample


class DiveTransformer:
    """Transforms internal DiveRecord instances into Divelogs.org API schemas."""

    @staticmethod
    def feet_to_meters(feet: float) -> float:
        """Convert feet to meters rounded to 2 decimal places."""
        return round(feet * 0.3048, 2)

    @staticmethod
    def fahrenheit_to_celsius(f: float) -> float:
        """Convert Fahrenheit to Celsius rounded to 1 decimal place."""
        return round((f - 32.0) * (5.0 / 9.0), 1)

    @staticmethod
    def psi_to_bar(psi: float) -> float:
        """Convert PSI to bar rounded to 1 decimal place."""
        return round(psi * 0.06894757, 1)

    @classmethod
    def transform_dive(cls, record: DiveRecord) -> Dict[str, Any]:
        """Convert a DiveRecord into Divelogs.org Dive JSON schema."""
        start_dt = record.start_time
        date_str = start_dt.strftime("%Y-%m-%d") if start_dt else "2026-01-01"
        time_str = start_dt.strftime("%H:%M:%S") if start_dt else "12:00:00"

        # Calculate duration in seconds
        if record.duration_minutes > 0:
            duration_sec = int(round(record.duration_minutes * 60.0))
        elif record.samples:
            duration_sec = int(round(record.samples[-1].time_seconds))
        else:
            duration_sec = 0

        # Computer model
        comp_parts = []
        if record.computer.manufacturer and record.computer.manufacturer.lower() != "unknown":
            comp_parts.append(record.computer.manufacturer)
        if record.computer.model and record.computer.model.lower() != "unknown":
            comp_parts.append(record.computer.model)
        dc_model_str = " ".join(comp_parts) if comp_parts else "Apeks DSX"

        # Tank data
        tanks: List[Dict[str, Any]] = []
        tank_entry: Dict[str, Any] = {
            "o2": int(round(record.tank.gas_mix.o2_fraction * 100)),
            "he": int(round(record.tank.gas_mix.he_fraction * 100)),
        }
        if record.tank.start_pressure_psi is not None and record.tank.start_pressure_psi > 0:
            tank_entry["start_pressure"] = cls.psi_to_bar(record.tank.start_pressure_psi)
        if record.tank.end_pressure_psi is not None and record.tank.end_pressure_psi > 0:
            tank_entry["end_pressure"] = cls.psi_to_bar(record.tank.end_pressure_psi)
        tanks.append(tank_entry)

        # Sample data & samplerate
        sampledata: List[Dict[str, Any]] = []
        samplerate = 2
        if len(record.samples) >= 2:
            dt = record.samples[1].time_seconds - record.samples[0].time_seconds
            if dt > 0:
                samplerate = int(round(dt))

        for s in record.samples:
            sample_pt: Dict[str, Any] = {
                "d": cls.feet_to_meters(s.depth_feet),
            }
            if s.temperature_f is not None:
                sample_pt["t"] = cls.fahrenheit_to_celsius(s.temperature_f)
            sampledata.append(sample_pt)

        # Base payload
        payload: Dict[str, Any] = {
            "date": date_str,
            "time": time_str,
            "duration": duration_sec,
            "maxdepth": cls.feet_to_meters(record.max_depth_feet),
            "dc_model": dc_model_str,
            "tanks": tanks,
            "samplerate": samplerate,
            "sampledata": sampledata,
        }

        if record.avg_depth_feet > 0:
            payload["meandepth"] = cls.feet_to_meters(record.avg_depth_feet)

        if record.min_temp_f is not None:
            payload["depthtemp"] = cls.fahrenheit_to_celsius(record.min_temp_f)

        if record.max_temp_f is not None:
            payload["surfacetemp"] = cls.fahrenheit_to_celsius(record.max_temp_f)

        if record.latitude is not None:
            payload["lat"] = record.latitude

        if record.longitude is not None:
            payload["lng"] = record.longitude

        if record.site:
            payload["divesite"] = record.site

        if record.location:
            payload["location"] = record.location

        if record.notes:
            payload["notes"] = record.notes

        return payload
