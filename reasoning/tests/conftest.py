import pytest

def pytest_addoption(parser):
    parser.addoption(
        "--file-id", 
        action="store", 
        default="558f1a53", 
        help="file_id untuk dites pada reasoning system"
    )

    parser.addoption(
        "--inst-id", 
        action="store", 
        default="8466278", 
        help="ID institution untuk dites pada e2e by id"
    )

@pytest.fixture
def file_id(request):
    return request.config.getoption("--file-id")

@pytest.fixture
def inst_id(request):
    return int(request.config.getoption("--inst-id"))
