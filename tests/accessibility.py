"""Shared WCAG contrast calculations for static and browser tests."""

from collections.abc import Sequence

TEXT_CONTRAST_MINIMUM = 4.5
NON_TEXT_CONTRAST_MINIMUM = 3.0


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert a six-digit CSS hex color to an RGB triplet."""
    red, green, blue = (int(hex_color[index : index + 2], 16) for index in (1, 3, 5))
    return red, green, blue


def contrast_ratio(first: Sequence[int], second: Sequence[int]) -> float:
    """Return the WCAG contrast ratio between two 8-bit RGB colors."""

    def relative_luminance(color: Sequence[int]) -> float:
        channels = [channel / 255 for channel in color]
        linear = [
            channel / 12.92
            if channel <= 0.04045
            else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        red, green, blue = linear
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    first_luminance = relative_luminance(first)
    second_luminance = relative_luminance(second)
    lighter = max(first_luminance, second_luminance)
    darker = min(first_luminance, second_luminance)
    return (lighter + 0.05) / (darker + 0.05)
