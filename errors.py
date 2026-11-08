"""Errores que se pueden mostrar tal cual en la interfaz."""


class HistoriaError(Exception):
    """Error de uso o de entorno, con mensaje en español y, si hace falta, en inglés."""

    def __init__(self, message: str, message_en: str | None = None) -> None:
        super().__init__(message)
        self.message_en = message_en or message
