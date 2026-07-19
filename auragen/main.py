"""Console entry point: `auragen` or `python -m auragen.main`."""

from auragen.cli.commands import app


def run() -> None:
    app()


if __name__ == "__main__":
    run()
