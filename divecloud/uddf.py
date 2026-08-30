"""Universal Dive Data Format (UDDF v3.2.0) exporter."""

from __future__ import annotations

import logging
import xml.dom.minidom
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union

from divecloud.parser import DiveRecord, DiveSample

logger = logging.getLogger(__name__)


class UDDFExporter:
    """Exports parsed DiveRecords to UDDF 3.2.0 XML format."""

    @staticmethod
    def feet_to_meters(feet: float) -> float:
        """Convert feet to meters."""
        return round(feet * 0.3048, 2)

    @staticmethod
    def fahrenheit_to_kelvin(f: float) -> float:
        """Convert Fahrenheit to Kelvin."""
        return round((f - 32.0) * (5.0 / 9.0) + 273.15, 2)

    @staticmethod
    def psi_to_pascal(psi: float) -> float:
        """Convert PSI to Pascal."""
        return round(psi * 6894.757, 1)

    @classmethod
    def export_dives(
        cls,
        dives: List[DiveRecord],
        output_path: Optional[Union[Path, str]] = None,
    ) -> str:
        """Export a list of DiveRecords into a single UDDF XML document."""
        root = ET.Element("uddf", {"version": "3.2.0", "xmlns": "http://www.streit.cc/uddf/3.2/"})

        # 1. Generator section
        gen = ET.SubElement(root, "generator")
        ET.SubElement(gen, "name").text = "divelog-sync"
        ET.SubElement(gen, "version").text = "0.1.0"
        ET.SubElement(gen, "manufacturer").text = "https://github.com/jamesbspencer/divelog"
        ET.SubElement(gen, "datetime").text = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        # 2. Diver section
        diver = ET.SubElement(root, "diver")
        owner = ET.SubElement(diver, "owner", {"id": "diver_owner"})
        personal = ET.SubElement(owner, "personal")
        ET.SubElement(personal, "first_name").text = "Diver"

        # 3. Gas Definitions (collect unique mixes across all dives)
        gas_defs = ET.SubElement(root, "gasdefinitions")
        mix_map = {}
        for idx, dive in enumerate(dives, 1):
            mix = dive.tank.gas_mix
            mix_key = (mix.o2_fraction, mix.he_fraction)
            if mix_key not in mix_map:
                mix_id = f"mix_{len(mix_map) + 1}"
                mix_map[mix_key] = mix_id
                mix_elem = ET.SubElement(gas_defs, "mix", {"id": mix_id})
                ET.SubElement(mix_elem, "name").text = mix.name
                ET.SubElement(mix_elem, "o2").text = f"{mix.o2_fraction:.3f}"
                ET.SubElement(mix_elem, "n2").text = f"{mix.n2_fraction:.3f}"
                ET.SubElement(mix_elem, "he").text = f"{mix.he_fraction:.3f}"

        # 4. Profile Data
        profile_data = ET.SubElement(root, "profiledata")
        rep_group = ET.SubElement(profile_data, "repetitiongroup", {"id": "rg_1"})

        for idx, dive in enumerate(dives, 1):
            dive_id = f"dive_{dive.duid or idx}"
            dive_elem = ET.SubElement(rep_group, "dive", {"id": dive_id})

            # Date and Time
            if dive.start_time:
                date_elem = ET.SubElement(dive_elem, "date")
                ET.SubElement(date_elem, "year").text = str(dive.start_time.year)
                ET.SubElement(date_elem, "month").text = f"{dive.start_time.month:02d}"
                ET.SubElement(date_elem, "day").text = f"{dive.start_time.day:02d}"

                time_elem = ET.SubElement(dive_elem, "time")
                ET.SubElement(time_elem, "hour").text = f"{dive.start_time.hour:02d}"
                ET.SubElement(time_elem, "minute").text = f"{dive.start_time.minute:02d}"
                ET.SubElement(time_elem, "second").text = f"{dive.start_time.second:02d}"

            ET.SubElement(dive_elem, "divenumber").text = str(dive.dive_number)

            # Information Before Dive
            info_before = ET.SubElement(dive_elem, "informationbeforedive")

            # Dive computer info
            if dive.computer.model != "Unknown":
                comp_elem = ET.SubElement(info_before, "divecomputer")
                ET.SubElement(comp_elem, "model").text = dive.computer.model
                if dive.computer.serial_number != "Unknown":
                    ET.SubElement(comp_elem, "serialnumber").text = dive.computer.serial_number
                if dive.computer.manufacturer:
                    ET.SubElement(comp_elem, "manufacturer").text = dive.computer.manufacturer

            # Tank data before dive
            mix_key = (dive.tank.gas_mix.o2_fraction, dive.tank.gas_mix.he_fraction)
            mix_id = mix_map.get(mix_key, "mix_1")

            tank_data_before = ET.SubElement(info_before, "tankdata")
            ET.SubElement(tank_data_before, "link", {"ref": mix_id})
            # Standard 80 cuft (AL80) has 11.1 Liters = 0.0111 m^3 water capacity
            tank_vol_m3 = 0.0111 if (dive.tank.volume_cuft or 80.0) == 80.0 else round((dive.tank.volume_cuft or 80.0) * 0.0283168 / (3000.0 / 14.696), 4)
            ET.SubElement(tank_data_before, "tankvolume").text = str(tank_vol_m3)
            working_pa = cls.psi_to_pascal(dive.tank.working_pressure_psi or 3000.0)
            ET.SubElement(tank_data_before, "workingpressure").text = str(working_pa)

            if dive.tank.start_pressure_psi is not None:
                start_pa = cls.psi_to_pascal(dive.tank.start_pressure_psi)
                ET.SubElement(tank_data_before, "tankpressurebegin").text = str(start_pa)

            # Samples (time-series profile)
            if dive.samples:
                samples_elem = ET.SubElement(dive_elem, "samples")
                for s in dive.samples:
                    wp = ET.SubElement(samples_elem, "waypoint")
                    ET.SubElement(wp, "depth").text = str(cls.feet_to_meters(s.depth_feet))
                    ET.SubElement(wp, "divetime").text = str(round(s.time_seconds, 1))

                    if s.temperature_f is not None:
                        temp_k = cls.fahrenheit_to_kelvin(s.temperature_f)
                        ET.SubElement(wp, "temperature").text = str(temp_k)

                    if s.pressure_psi is not None and s.pressure_psi > 0:
                        press_pa = cls.psi_to_pascal(s.pressure_psi)
                        ET.SubElement(wp, "tankpressure").text = str(press_pa)

            # Information After Dive
            info_after = ET.SubElement(dive_elem, "informationafterdive")
            if dive.max_depth_feet > 0:
                ET.SubElement(info_after, "greatestdepth").text = str(cls.feet_to_meters(dive.max_depth_feet))
            if dive.avg_depth_feet > 0:
                ET.SubElement(info_after, "averagedepth").text = str(cls.feet_to_meters(dive.avg_depth_feet))
            if dive.duration_minutes > 0:
                duration_sec = round(dive.duration_minutes * 60.0, 1)
                ET.SubElement(info_after, "diveduration").text = str(duration_sec)
            if dive.min_temp_f is not None:
                ET.SubElement(info_after, "lowesttemperature").text = str(cls.fahrenheit_to_kelvin(dive.min_temp_f))

            if dive.tank.end_pressure_psi is not None:
                tank_data_after = ET.SubElement(info_after, "tankdata")
                end_pa = cls.psi_to_pascal(dive.tank.end_pressure_psi)
                ET.SubElement(tank_data_after, "tankpressureend").text = str(end_pa)

                # Breathing consumption volume in m^3 (SI standard)
                p_start = dive.tank.start_pressure_psi or 0.0
                delta_p = p_start - dive.tank.end_pressure_psi
                if delta_p > 0:
                    # Standard AL80 basis (77.4 cu ft = 2.1917 m^3 at 3000 psi)
                    consumed_m3 = (delta_p / 3000.0) * 2.1917
                    ET.SubElement(tank_data_after, "breathingconsumptionvolume").text = f"{consumed_m3:.4f}"

            # Site, location, and SAC notes
            notes_text = []
            if dive.site:
                notes_text.append(f"Site: {dive.site}")
            if dive.location:
                notes_text.append(f"Location: {dive.location}")

            # Calculate SAC if tank telemetry is available
            p_start = dive.tank.start_pressure_psi or 0.0
            p_end = dive.tank.end_pressure_psi or 0.0
            delta_p = p_start - p_end
            if delta_p > 0 and dive.avg_depth_feet > 0 and dive.duration_minutes > 0:
                ata = 1.0 + (dive.avg_depth_feet / 33.0)
                sac_psi = delta_p / (dive.duration_minutes * ata)
                rmv_cfm = sac_psi * (77.4 / 3000.0)  # AL80 basis
                notes_text.append(f"SAC: {sac_psi:.1f} psi/min ({rmv_cfm:.2f} cfm)")

            if dive.notes:
                notes_text.append(dive.notes)

            if notes_text:
                ET.SubElement(info_after, "notes").text = " | ".join(notes_text)

        # Convert to pretty XML string
        xml_bytes = ET.tostring(root, encoding="utf-8")
        dom = xml.dom.minidom.parseString(xml_bytes)
        pretty_xml = dom.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")

        # Strip extra blank lines generated by minidom
        cleaned_xml = "\n".join([line for line in pretty_xml.split("\n") if line.strip()]) + "\n"

        if output_path:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(cleaned_xml, encoding="utf-8")
            logger.info("Saved UDDF export to %s", out)

        return cleaned_xml

    @classmethod
    def export_single_dive(
        cls,
        dive: DiveRecord,
        output_path: Optional[Union[Path, str]] = None,
    ) -> str:
        """Export a single DiveRecord to UDDF XML."""
        return cls.export_dives([dive], output_path=output_path)
