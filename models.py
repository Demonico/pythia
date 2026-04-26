from dataclasses import dataclass, field


@dataclass
class Section:
    paper_id: str
    section_type: str  # motivation, proposal, wording, discussion, etc.
    content: str
    page_number: int


@dataclass
class Paper:
    paper_id: str      # e.g. P2300R7
    title: str
    authors: list[str]
    date: str
    status: str        # accepted, rejected, pending
    sections: list[Section] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)  # paper_ids cited
