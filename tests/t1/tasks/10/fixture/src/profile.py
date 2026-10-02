from src.formatting import _format_user
from src.models import User


def profile_label(user: User) -> str:
    return _format_user(user)
