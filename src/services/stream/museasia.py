from .. import AbstractServiceHandler


class ServiceHandler(AbstractServiceHandler):
	def __init__(self) -> None:
		super().__init__(key="museasia", name="Muse Asia", is_generic=False)
