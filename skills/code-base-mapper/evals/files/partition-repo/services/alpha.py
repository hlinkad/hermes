class AlphaService:
    def prepare(self) -> str:
        return "alpha"


def alpha_entry() -> str:
    return AlphaService().prepare()
