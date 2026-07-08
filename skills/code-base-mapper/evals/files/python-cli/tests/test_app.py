from src.app import Runner


def test_main() -> None:
    assert Runner().run("ada") == "Hello, Ada"
