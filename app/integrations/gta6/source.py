from dataclasses import dataclass


@dataclass(frozen=True)
class GTA6SourceItem:
    title: str
    summary: str
    url: str
    source_name: str
    fact_type: str
    confidence: str
    published_at: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("title is required")

        if not isinstance(self.summary, str):
            raise ValueError("summary must be a string")

        if not isinstance(self.url, str) or not self.url.strip():
            raise ValueError("url is required")

        if not isinstance(self.source_name, str) or not self.source_name.strip():
            raise ValueError("source_name is required")

        if not isinstance(self.fact_type, str) or not self.fact_type.strip():
            raise ValueError("fact_type is required")

        if not isinstance(self.confidence, str) or not self.confidence.strip():
            raise ValueError("confidence is required")
