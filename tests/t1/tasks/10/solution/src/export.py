from src.models import User
from src.presentation import render_user


def export_row(user: User) -> str:
    return render_user(user)
