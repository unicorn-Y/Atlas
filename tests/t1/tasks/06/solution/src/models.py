from dataclasses import dataclass, field


@dataclass(frozen=True)
class Note:
    id: str
    title: str
    body: str
    tags: list[str] = field(default_factory=list)
