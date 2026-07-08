class GammaService:
    def prepare(self) -> str:
        return "gamma"


def gamma_entry() -> str:
    return GammaService().prepare()
