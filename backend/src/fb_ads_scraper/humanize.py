"""Human-like cursor + scroll helpers driven by Playwright's page.mouse.

Playwright's `page.mouse.move(x, y, steps=N)` is a linear interpolation.
Humans don't move in straight lines at constant speed — paths are curved
and timing eases (slow start, faster middle, slow stop). This module
generates bezier-curve paths with variable timing and keeps a
client-side cursor position (Playwright doesn't expose the current
mouse coordinates after a move).
"""

from __future__ import annotations

import asyncio
import math
import random
from dataclasses import dataclass

from playwright.async_api import Page


def _bezier_point(
    t: float,
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
) -> tuple[float, float]:
    u = 1.0 - t
    b0, b1, b2, b3 = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    x = b0 * p0[0] + b1 * p1[0] + b2 * p2[0] + b3 * p3[0]
    y = b0 * p0[1] + b1 * p1[1] + b2 * p2[1] + b3 * p3[1]
    return x, y


def _ease_in_out(t: float) -> float:
    """Cubic ease-in-out — slow start, fast middle, slow end."""
    return 3 * t * t - 2 * t * t * t


def _control_points(
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Pick two random control points offset perpendicular to the path."""
    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy
    dist = math.hypot(dx, dy) or 1.0
    # unit perpendicular
    nx, ny = -dy / dist, dx / dist
    # offset magnitudes — scale with distance, with some variance
    off1 = random.uniform(0.10, 0.35) * dist * random.choice((-1, 1))
    off2 = random.uniform(0.10, 0.35) * dist * random.choice((-1, 1))
    # control points roughly 1/3 and 2/3 along the line, then offset perpendicular
    cp1 = (sx + dx * 0.33 + nx * off1, sy + dy * 0.33 + ny * off1)
    cp2 = (sx + dx * 0.66 + nx * off2, sy + dy * 0.66 + ny * off2)
    return cp1, cp2


@dataclass
class HumanCursor:
    """Tracks the cursor position and moves it along bezier paths."""

    x: float = 0.0
    y: float = 0.0

    async def move_to(
        self,
        page: Page,
        target_x: float,
        target_y: float,
        *,
        duration: float | None = None,
    ) -> None:
        start = (self.x, self.y)
        end = (float(target_x), float(target_y))
        dist = math.hypot(end[0] - start[0], end[1] - start[1])
        if dist < 1.0:
            return
        # Duration ≈ Fitts-law-ish: longer for bigger jumps, with noise.
        if duration is None:
            duration = min(1.2, 0.18 + dist / 1400.0) * random.uniform(0.85, 1.25)
        # Step count from distance + duration. Keep it cheap.
        steps = max(8, int(min(40, dist / 12.0 + duration * 18)))
        cp1, cp2 = _control_points(start, end)
        prev_t_real = 0.0
        for i in range(1, steps + 1):
            t = i / steps
            te = _ease_in_out(t)
            px, py = _bezier_point(te, start, cp1, cp2, end)
            # tiny tremor — sub-pixel-ish jitter
            px += random.uniform(-0.6, 0.6)
            py += random.uniform(-0.6, 0.6)
            await page.mouse.move(px, py, steps=1)
            # variable per-segment delay, roughly duration / steps with jitter
            seg = (t - prev_t_real) * duration * random.uniform(0.85, 1.2)
            prev_t_real = t
            if seg > 0:
                await asyncio.sleep(seg)
        self.x, self.y = end

    async def jitter(self, page: Page, *, radius: int = 80) -> None:
        """Drift to a nearby point, like an idle hand."""
        vp = page.viewport_size or {"width": 1366, "height": 900}
        # If we don't have a position yet, seed somewhere natural.
        if self.x == 0 and self.y == 0:
            self.x = random.uniform(vp["width"] * 0.3, vp["width"] * 0.7)
            self.y = random.uniform(vp["height"] * 0.3, vp["height"] * 0.7)
        tx = max(20.0, min(vp["width"] - 20.0, self.x + random.uniform(-radius, radius)))
        ty = max(40.0, min(vp["height"] - 40.0, self.y + random.uniform(-radius, radius)))
        await self.move_to(page, tx, ty, duration=random.uniform(0.18, 0.55))

    async def move_into_viewport(self, page: Page) -> None:
        """Move to a plausible reading spot if the cursor hasn't been used yet."""
        vp = page.viewport_size or {"width": 1366, "height": 900}
        tx = random.uniform(vp["width"] * 0.25, vp["width"] * 0.75)
        ty = random.uniform(vp["height"] * 0.25, vp["height"] * 0.65)
        await self.move_to(page, tx, ty)
