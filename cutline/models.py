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


class ColorGrade(BaseModel):
    """A look applied to the picture (not to text). Neutral values change nothing."""

    preset: str | None = None  # name it was built from, e.g. "darker"; some presets add a curve or split tone
    brightness: float = 0.0  # -1..1, added to every pixel (eq)
    contrast: float = 1.0  # 0..3
    saturation: float = 1.0  # 0 = black and white, 1 = unchanged, 2 = very vivid
    gamma: float = 1.0  # <1 darkens shadows and midtones, >1 lifts them
    warmth: float = 0.0  # -1 (cool, blue) .. 1 (warm, orange)
    vignette: float = 0.0  # 0..1 darkened corners
    start: float | None = None  # source seconds; None = whole video
    end: float | None = None


class TextAnim(BaseModel):
    style: str = "fade"  # none | fade | slide | pop | zoom | blur | typewriter
    direction: str = "right"  # slide: side it comes in FROM (in) or leaves TOWARD (out)
    seconds: float = 0.6
    distance: float = 0.15  # slide travel, as a fraction of the frame width/height
    fade: bool = True  # slide also fades


class TextOverlay(BaseModel):
    """Custom on-screen text (titles, callouts, lower thirds), timed in source seconds."""

    id: str
    text: str
    start: float
    end: float
    position: str = "center"  # center, top, bottom, left, right, top_left, top_right, bottom_left, bottom_right, lower_third
    x: float | None = None  # 0..1 across the frame; with y, overrides position (text centred on the point)
    y: float | None = None  # 0..1 down the frame
    font: str = "Inter"
    size: int = 96  # pixels on a 1080p frame; scaled to the output
    color: str = "FFFFFF"  # RRGGBB
    bold: bool = True
    italic: bool = False
    outline: float = 3.0
    outline_color: str = "000000"
    shadow: float = 2.0
    background: str | None = None  # RRGGBB box behind the text, or None
    animate_in: TextAnim = Field(default_factory=TextAnim)
    animate_out: TextAnim = Field(default_factory=lambda: TextAnim(direction="left"))
    applies_to: str = "all"  # all | long | shorts


class EditList(BaseModel):
    keep: list[Range] = Field(default_factory=list)
    removed: list[Range] = Field(default_factory=list)  # user-requested cuts, kept so they survive re-planning
    shorts: list[Short] = Field(default_factory=list)
    captions: CaptionStyle = Field(default_factory=CaptionStyle)
    grades: list[ColorGrade] = Field(default_factory=list)
    texts: list[TextOverlay] = Field(default_factory=list)


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
