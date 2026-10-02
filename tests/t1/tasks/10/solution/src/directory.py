from src.models import User
from src.presentation import render_user


def directory_entry(user: User) -> str:
    return render_user(user)
