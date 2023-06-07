from .. import AbstractServiceHandler


class ServiceHandler(AbstractServiceHandler):
	def __init__(self) -> None:
		super().__init__(key="anione", name="Ani-One", is_generic=False)
