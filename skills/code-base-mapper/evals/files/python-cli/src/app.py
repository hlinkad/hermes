import argparse


DEFAULT_GREETING = "Hello"


class Runner:
    def __init__(self, greeting: str = DEFAULT_GREETING) -> None:
        self.greeting = greeting

    def run(self, name: str) -> str:
        return f"{self.greeting}, {name.strip().title()}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    print(Runner().run(args.name))


if __name__ == "__main__":
    main()
