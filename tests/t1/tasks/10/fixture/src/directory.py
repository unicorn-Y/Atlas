from src.formatting import _format_user
from src.models import User


def directory_entry(user: User) -> str:
    return _format_user(user)
