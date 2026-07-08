class BetaService:
    def prepare(self) -> str:
        return "beta"


def beta_entry() -> str:
    return BetaService().prepare()
