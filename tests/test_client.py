"""Unit tests for DiveCloud automation client."""

from pathlib import Path
import pytest
import responses
from requests.exceptions import Timeout

from divecloud.client import DiveCloudClient
from divecloud.config import DiveCloudConfig
from divecloud.exceptions import (
    DiveCloudAuthError,
    DiveCloudParseError,
    DiveCloudTimeoutError,
)


@pytest.fixture
def sample_config():
    return DiveCloudConfig(
        base_url="https://divecloud.net",
        username="diver@example.com",
        password="secretpassword123",
        timeout=5.0,
        max_retries=1,
        request_delay=0.0,  # no delay in unit tests
    )


@pytest.fixture
def client(sample_config):
    return DiveCloudClient(sample_config)


@responses.activate
def test_check_registration_success(client):
    responses.add(
        responses.GET,
        "https://divecloud.net/checkReg.py",
        body="{YES VERIFIED}{PAID}{ACTIVE}",
        status=200,
    )

    result = client.check_registration()
    assert result["status"] == "YES VERIFIED"
    assert result["account_type"] == "PAID"
    assert result["account_state"] == "ACTIVE"


@responses.activate
def test_check_registration_not_found(client):
    responses.add(
        responses.GET,
        "https://divecloud.net/checkReg.py",
        body="{NO}",
        status=200,
    )

    with pytest.raises(DiveCloudAuthError) as exc_info:
        client.check_registration()
    assert "Account does not exist" in str(exc_info.value)


@responses.activate
def test_check_registration_timeout(client):
    responses.add(
        responses.GET,
        "https://divecloud.net/checkReg.py",
        body=Timeout("Connection timed out"),
    )

    with pytest.raises(DiveCloudTimeoutError):
        client.check_registration()


@responses.activate
def test_authenticate_full_handshake_success(client):
    # Step 1
    responses.add(
        responses.GET,
        "https://divecloud.net/checkReg.py",
        body="{YES VERIFIED}{FREE}",
        status=200,
    )

    # Step 2
    responses.add(
        responses.POST,
        "https://divecloud.net/init.py",
        body="{YES}{SESSION=dc_sess_9988776655}",
        status=200,
    )

    # Step 3
    responses.add(
        responses.POST,
        "https://divecloud.net/logincheck",
        body="success",
        status=200,
    )

    assert client.authenticate() is True
    assert client._is_authenticated is True
    assert client._session_token == "dc_sess_9988776655"


@responses.activate
def test_authenticate_bad_password(client):
    # Step 1
    responses.add(
        responses.GET,
        "https://divecloud.net/checkReg.py",
        body="{YES VERIFIED}{PAID}{ACTIVE}",
        status=200,
    )

    # Step 2 fails
    responses.add(
        responses.POST,
        "https://divecloud.net/init.py",
        body="{NO}ERRCODE=12 user/pass failed or user not verified",
        status=200,
    )

    with pytest.raises(DiveCloudAuthError) as exc_info:
        client.authenticate()
    assert "Authentication failed during session generation" in str(exc_info.value)


@responses.activate
def test_list_files(client):
    client._is_authenticated = True

    html_content = """
    <html>
      <body>
        <ul id="files_list">
          <li duid="7165_4515_20260829103100_2" name="7165_4515_20260829103100_2.zxu" dive="DLOG">
            <span class="file_name">08.29.26_10.31_DSX_4515</span>
          </li>
          <li duid="7165_4515_20260829084100_1" name="7165_4515_20260829084100_1.zxu" dive="DLOG">
            <span class="file_name">08.29.26_08.41_DSX_4515</span>
          </li>
        </ul>
      </body>
    </html>
    """

    responses.add(
        responses.GET,
        "https://divecloud.net/files",
        body=html_content,
        status=200,
    )

    files = client.list_files()
    assert len(files) == 2
    assert files[0]["duid"] == "7165_4515_20260829103100_2"
    assert files[0]["name"] == "7165_4515_20260829103100_2.zxu"
    assert files[0]["title"] == "08.29.26_10.31_DSX_4515"


@responses.activate
def test_download_file(client, tmp_path):
    client._is_authenticated = True
    client._session_token = "mock_session_123"

    file_content = b"PK\x03\x04DIVE_BINARY_LOG_STREAM_DATA"
    responses.add(
        responses.GET,
        "https://divecloud.net/download.py",
        body=file_content,
        status=200,
    )

    dest = tmp_path / "sample.zxu"
    result = client.download_file("7165_4515_20260829103100_2", dest)
    assert result == dest
    assert dest.read_bytes() == file_content
