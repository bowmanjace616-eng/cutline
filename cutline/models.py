"""Data model. Every edit is stored as an edit list over the source file, never as a re-encoded file."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Range(BaseModel):
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


class Word(BaseModel):
    text: str
    start: float
    end: float


class Sentence(BaseModel):
    text: str
    start: float
    end: float


class Transcript(BaseModel):
    language: str | None = None
    words: list[Word] = Field(default_factory=list)

    def sentences(self, max_gap: float = 0.8) -> list[Sentence]:
        """Group words into sentences on end punctuation or a long pause."""
        out: list[Sentence] = []
        cur: list[Word] = []
        for i, w in enumerate(self.words):
            cur.append(w)
            nxt = self.words[i + 1] if i + 1 < len(self.words) else None
            ends = w.text.rstrip().endswith((".", "?", "!"))
            gap = nxt is not None and nxt.start - w.end > max_gap
            if ends or gap or nxt is None:
                out.append(
                    Sentence(
                        text=" ".join(x.text.strip() for x in cur),
                        start=cur[0].start,
                        end=cur[-1].end,
                    )
                )
                cur = []
        return out


class Short(BaseModel):
    title: str
    start: float
    end: float
    hook: str | None = None


class CaptionStyle(BaseModel):
    preset: str = "bold"  # bold | clean | karaoke
    font: str = "DejaVu Sans"
    size: int = 84
    color: str = "FFFFFF"  # RRGGBB
    highlight: str = "FFD400"  # active word colour (karaoke preset)
    words_per_line: int = 3


class Overlay(BaseModel):
    """A motion-graphics element, timed in OUTPUT seconds of the video it is drawn on."""

    kind: str  # title | lower_third | zoom
    start: float
    end: float
    text: str = ""
    subtitle: str = ""
    target: str = "long"  # long | shorts | montage | all
    zoom: float = 1.15  # for kind=zoom


class EditList(BaseModel):
    keep: list[Range] = Field(default_factory=list)
    removed: list[Range] = Field(default_factory=list)  # user-requested cuts, kept so they survive re-planning
    shorts: list[Short] = Field(default_factory=list)
    captions: CaptionStyle = Field(default_factory=CaptionStyle)
    overlays: list[Overlay] = Field(default_factory=list)


class MediaInfo(BaseModel):
    duration: float
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    has_audio: bool = True


class Project(BaseModel):
    id: str
    source: str
    media: MediaInfo
    silences: list[Range] = Field(default_factory=list)
    transcript: Transcript | None = None
    edits: EditList = Field(default_factory=EditList)
    outputs: dict[str, str] = Field(default_factory=dict)
