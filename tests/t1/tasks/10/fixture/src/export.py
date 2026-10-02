from src.formatting import _format_user
from src.models import User


def export_row(user: User) -> str:
    return _format_user(user)
