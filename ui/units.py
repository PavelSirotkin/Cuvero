"""Display units: millimetres or mils (1/1000 inch). Data always stays in millimetres."""

from dataclasses import dataclass

MIL = 0.0254  # millimetres per mil


@dataclass
class Units:
    mil: bool = False

    @property
    def suffix(self) -> str:
        return "mil" if self.mil else "мм"

    @property
    def decimals(self) -> int:
        return 1 if self.mil else 3

    def to_display(self, value_mm: float) -> float:
        return value_mm / MIL if self.mil else value_mm

    def from_display(self, value: float) -> float:
        return value * MIL if self.mil else value

    def text(self, value_mm: float, digits: int | None = None) -> str:
        """Number in display units with a decimal comma, without the unit name."""
        digits = self.decimals if digits is None else digits
        return f"{self.to_display(value_mm):.{digits}f}".replace(".", ",")

    def with_suffix(self, value_mm: float, digits: int | None = None) -> str:
        return f"{self.text(value_mm, digits)} {self.suffix}"
