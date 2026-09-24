from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.db import models


@lru_cache(maxsize=1)
def _fernet() -> MultiFernet:
    keys = settings.FIELD_ENCRYPTION_KEYS
    if not keys:
        raise RuntimeError("FIELD_ENCRYPTION_KEYS is empty")
    return MultiFernet([Fernet(k) for k in keys])


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


class EncryptedTextField(models.TextField):
    """Text stored as a Fernet token; reads back as plain str.

    Values can't be queried or indexed, which is the point: merchant keys and
    OAuth tokens only ever get read by id.
    """

    def from_db_value(self, value, expression, connection):
        if value in (None, ""):
            return value
        try:
            return decrypt(value)
        except InvalidToken as exc:
            raise ValueError(f"cannot decrypt {self.model.__name__}.{self.name}") from exc

    def get_prep_value(self, value):
        if value in (None, ""):
            return value
        return encrypt(str(value))


def mask(value: str | None, visible: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= visible:
        return "•" * len(value)
    return "•" * 8 + value[-visible:]
