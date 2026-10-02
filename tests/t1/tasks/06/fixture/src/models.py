from dataclasses import dataclass


@dataclass(frozen=True)
class Note:
    id: str
    title: str
    body: str
