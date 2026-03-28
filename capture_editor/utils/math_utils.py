import math
import random

from PyQt6.QtCore import QLineF, QPointF
from PyQt6.QtGui import QPainterPath, QPolygonF


def create_pigtail_arrow_path(
    start: QPointF,
    end: QPointF,
    coil_count: int = 1,
    coil_radius: float = 26.0,
) -> QPainterPath:
    """Create a curved pigtail arrow: sweeping body + single circular loop."""
    path = QPainterPath()
    path.moveTo(start)

    line = QLineF(start, end)
    length = line.length()
    if length <= 1.0:
        return path

    ux = (end.x() - start.x()) / length
    uy = (end.y() - start.y()) / length
    px = -uy
    py = ux

    turns = max(1, int(coil_count))
    radius = min(float(coil_radius), max(10.0, length * 0.13))
    radius = min(radius, length * 0.20)

    # Keep loop on a consistent side for a stable visual style.
    side = -1.0
    sx = px * side
    sy = py * side

    center = QPointF(
        start.x() + (ux * length * 0.56) + (sx * length * 0.16),
        start.y() + (uy * length * 0.56) + (sy * length * 0.16),
    )

    # Loop connection point (top-left-ish on loop in local u/s basis).
    theta0 = math.radians(145.0)
    entry = QPointF(
        center.x() + (ux * math.cos(theta0) * radius) + (sx * math.sin(theta0) * radius),
        center.y() + (uy * math.cos(theta0) * radius) + (sy * math.sin(theta0) * radius),
    )

    # Main sweeping curve into loop.
    c1 = QPointF(
        start.x() + (ux * length * 0.24) + (sx * length * 0.30),
        start.y() + (uy * length * 0.24) + (sy * length * 0.30),
    )
    c2 = QPointF(
        entry.x() - (ux * radius * 0.45) + (sx * radius * 0.20),
        entry.y() - (uy * radius * 0.45) + (sy * radius * 0.20),
    )
    path.cubicTo(c1, c2, entry)

    # Draw full clockwise loop and return to the same connection point.
    segments = 96 * turns
    for i in range(1, segments + 1):
        t = i / segments
        theta = theta0 - ((2.0 * math.pi * turns) * t)
        x = center.x() + (ux * math.cos(theta) * radius) + (sx * math.sin(theta) * radius)
        y = center.y() + (uy * math.cos(theta) * radius) + (sy * math.sin(theta) * radius)
        path.lineTo(x, y)

    # Sweep out to arrow tip, biased to the outer side so it does not cut loop center.
    exit_anchor = QPointF(
        entry.x() - (sx * radius * 0.35) + (ux * radius * 0.10),
        entry.y() - (sy * radius * 0.35) + (uy * radius * 0.10),
    )
    path.lineTo(exit_anchor)

    c3 = QPointF(
        exit_anchor.x() - (sx * radius * 0.90) + (ux * radius * 0.20),
        exit_anchor.y() - (sy * radius * 0.90) + (uy * radius * 0.20),
    )
    c4 = QPointF(
        end.x() - (ux * length * 0.20) - (sx * length * 0.10),
        end.y() - (uy * length * 0.20) - (sy * length * 0.10),
    )
    path.cubicTo(c3, c4, end)
    return path


def create_curved_arrow_path(start: QPointF, end: QPointF, control: QPointF) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(start)
    path.quadTo(control, end)
    return path


def create_handdrawn_path(start: QPointF, end: QPointF, shakiness: float = 2.0) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(start)

    line = QLineF(start, end)
    length = line.length()
    if length <= 0:
        return path

    steps = int(length / 10.0)
    steps = max(5, steps)

    for i in range(1, steps):
        t = i / steps
        pt = line.pointAt(t)

        offset_x = (random.random() - 0.5) * shakiness * 2
        offset_y = (random.random() - 0.5) * shakiness * 2

        path.lineTo(pt.x() + offset_x, pt.y() + offset_y)

    path.lineTo(end)
    return path


def get_arrowhead_polygon(
    end_point: QPointF,
    angle_deg: float,
    size: float = 15.0,
    style: str = "triangle",
) -> QPolygonF:
    poly = QPolygonF()
    angle_rad = angle_deg * math.pi / 180.0

    if style == "triangle":
        p1 = end_point

        back_angle1 = angle_rad + math.pi * 0.85
        back_angle2 = angle_rad - math.pi * 0.85

        p2 = QPointF(
            end_point.x() + size * math.cos(back_angle1),
            end_point.y() + size * math.sin(back_angle1),
        )
        p3 = QPointF(
            end_point.x() + size * math.cos(back_angle2),
            end_point.y() + size * math.sin(back_angle2),
        )

        poly.append(p1)
        poly.append(p2)
        poly.append(p3)

    elif style == "diamond":
        p1 = end_point
        mid_angle = angle_rad + math.pi
        mid = QPointF(
            end_point.x() + (size * 0.5) * math.cos(mid_angle),
            end_point.y() + (size * 0.5) * math.sin(mid_angle),
        )

        back_angle1 = angle_rad + math.pi * 0.75
        back_angle2 = angle_rad - math.pi * 0.75

        p2 = QPointF(
            mid.x() + (size * 0.5) * math.cos(back_angle1),
            mid.y() + (size * 0.5) * math.sin(back_angle1),
        )
        p3 = QPointF(
            end_point.x() + size * math.cos(mid_angle),
            end_point.y() + size * math.sin(mid_angle),
        )
        p4 = QPointF(
            mid.x() + (size * 0.5) * math.cos(back_angle2),
            mid.y() + (size * 0.5) * math.sin(back_angle2),
        )

        poly.append(p1)
        poly.append(p2)
        poly.append(p3)
        poly.append(p4)

    return poly
