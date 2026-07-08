class DeltaService:
    def prepare(self) -> str:
        return "delta"


def delta_entry() -> str:
    return DeltaService().prepare()
