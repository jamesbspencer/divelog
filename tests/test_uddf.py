"""Unit tests for ZXU parser and UDDF exporter."""

from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

from divecloud.parser import DiveComputerInfo, DiveRecord, DiveSample, GasMix, TankInfo, ZXUParser
from divecloud.uddf import UDDFExporter


SAMPLE_ZXU_RAW = """FSH|^~<>{}|OCI201^^|ZXU|20260830131820|
ZRH|^~<>{}|AQUGA|4515|FSWG|ThFt|F|PSIA|CF|
ZAR{
<AQUALUNG>
<APP>DiverLog+</APP>
<DUID>7165_4515_20260829103100_2</DUID>
<DIVE_DT>20260829103100</DIVE_DT>
<PDC_MODEL>DSX</PDC_MODEL>
<PDC_SERIAL>4515</PDC_SERIAL>
<MANUFACTURER>Apeks</MANUFACTURER>
<SITE>Blue Hole</SITE>
<DIVESTATS>DIVENO=2,MAXDEPTH=45.2,MINTEMP=83.5,EDT=005100</DIVESTATS>
<TANK>NUMBER=1,STARTPRESSURE=2970.00,ENDPRESSURE=1065.00,FO2=32,AVGDEPTH=27.5,DIVETIME=51.2</TANK>
</AQUALUNG>
}
ZDH|1|2|I|Q2S|20260829103100|51.2||PO2|
ZDP{
|0|0|2.21|
|0.500000|15.0||||||83.5||2970|
|1.000000|45.2||||||83.0||2500|
|1.500000|30.0||||||83.5||1800|
|2.000000|0.0||||||84.0||1065|
ZDP}
"""


def test_zxu_parser_raw_text():
    record = ZXUParser.parse_raw_text(SAMPLE_ZXU_RAW, filename="sample.zxu")

    assert record.duid == "7165_4515_20260829103100_2"
    assert record.dive_number == 2
    assert record.start_time == datetime(2026, 8, 29, 10, 31, 0)
    assert record.max_depth_feet == 45.2
    assert record.min_temp_f == 83.5
    assert record.site == "Blue Hole"

    # Computer
    assert record.computer.model == "DSX"
    assert record.computer.serial_number == "4515"
    assert record.computer.manufacturer == "Apeks"

    # Tank & Gas
    assert record.tank.start_pressure_psi == 2970.0
    assert record.tank.end_pressure_psi == 1065.0
    assert record.tank.gas_mix.name == "EAN32"
    assert record.tank.gas_mix.o2_fraction == 0.32

    # Samples
    assert len(record.samples) == 5
    assert record.samples[0].time_seconds == 0.0
    assert record.samples[1].time_seconds == 30.0
    assert record.samples[1].depth_feet == 15.0
    assert record.samples[1].pressure_psi == 2970.0
    assert record.samples[2].time_seconds == 60.0
    assert record.samples[2].depth_feet == 45.2


def test_unit_converters():
    assert UDDFExporter.feet_to_meters(32.8084) == 10.0
    assert UDDFExporter.fahrenheit_to_kelvin(32.0) == 273.15
    assert UDDFExporter.fahrenheit_to_kelvin(212.0) == 373.15
    assert round(UDDFExporter.psi_to_pascal(14.50377)) == 100000


def test_uddf_export_single(tmp_path):
    record = ZXUParser.parse_raw_text(SAMPLE_ZXU_RAW, filename="sample.zxu")
    out_file = tmp_path / "dive.uddf"

    xml_str = UDDFExporter.export_single_dive(record, out_file)
    assert out_file.exists()
    assert "<uddf" in xml_str
    assert 'version="3.2.0"' in xml_str

    # Validate XML parsing
    root = ET.fromstring(xml_str)
    assert root.tag.endswith("uddf")

    # Check generator
    gen_name = root.find(".//{*}generator/{*}name")
    assert gen_name is not None and gen_name.text == "divelog-sync"

    # Check dive computer
    comp_model = root.find(".//{*}divecomputer/{*}model")
    assert comp_model is not None and comp_model.text == "DSX"

    # Check dive number
    divenum = root.find(".//{*}dive/{*}divenumber")
    assert divenum is not None and divenum.text == "2"

    # Check waypoints / samples
    waypoints = root.findall(".//{*}samples/{*}waypoint")
    assert len(waypoints) == 5

    # Check greatest depth in meters (45.2 ft = 13.78 m)
    greatest_depth = root.find(".//{*}informationafterdive/{*}greatestdepth")
    assert greatest_depth is not None and greatest_depth.text == "13.78"


def test_uddf_export_combined(tmp_path):
    record1 = ZXUParser.parse_raw_text(SAMPLE_ZXU_RAW, filename="dive1.zxu")
    record2 = ZXUParser.parse_raw_text(SAMPLE_ZXU_RAW, filename="dive2.zxu")
    record2.duid = "dive_2"
    record2.dive_number = 3

    out_file = tmp_path / "combined.uddf"
    xml_str = UDDFExporter.export_dives([record1, record2], out_file)

    root = ET.fromstring(xml_str)
    dives = root.findall(".//{*}profiledata/{*}repetitiongroup/{*}dive")
    assert len(dives) == 2
