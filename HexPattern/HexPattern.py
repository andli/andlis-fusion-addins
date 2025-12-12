# HexPattern.py
# Cuts a honeycomb pattern of hexagons from a selected rectangular face.
#
# Usage:
# 1. Create user parameters:
#    - hexNumX    (unitless int) - number of hexagons along the selected edge
#    - hexMargin  (length, e.g. 0.5 mm) - space between hexagons
#    - hexPointyTop (optional, text) - "TRUE" for flat-top hexes instead of default pointy-top
#
# 2. Select an edge on a rectangular face (defines width direction for hexNumX)
# 3. Run this script from Scripts & Add-Ins

import adsk.core
import adsk.fusion
import traceback
import math

# Prefix for generated features
GENERATED_PREFIX = "hex#"


def _get_user_param(design, name, required=True, param_type="value"):
    params = design.userParameters
    p = params.itemByName(name)
    if not p and required:
        hint = ""
        if param_type == "int":
            hint = "\nCreate it in Modify → Change Parameters as a unitless integer."
        elif param_type == "length":
            hint = "\nCreate it in Modify → Change Parameters with a length unit (e.g., mm)."
        raise RuntimeError(f'Missing user parameter "{name}".{hint}')
    return p


def _get_face_from_edge(edge):
    """Get a planar face that contains this edge.
    If multiple planar faces share this edge, returns the largest one
    (most likely to be the intended target for hex pattern).
    Returns None if no planar face found.
    """
    planar_faces = []
    for face in edge.faces:
        # Check if face is planar
        if face.geometry.objectType == adsk.core.Plane.classType():
            planar_faces.append(face)

    if not planar_faces:
        return None

    if len(planar_faces) == 1:
        return planar_faces[0]

    # Multiple planar faces - pick the largest one
    largest_face = None
    largest_area = 0
    for face in planar_faces:
        area = face.area
        if area > largest_area:
            largest_area = area
            largest_face = face

    return largest_face


def _get_face_dimensions_from_edge(face, edge, sketch):
    """Get the dimensions of a rectangular face, with width along the edge direction.

    Returns:
        (width, height, edge_is_along_sketch_x, sketch_center_x, sketch_center_y, start_from_min)
        - width: face dimension along the selected edge
        - height: face dimension perpendicular to the selected edge
        - edge_is_along_sketch_x: True if selected edge aligns with sketch X axis
        - sketch_center_x/y: face center in sketch coordinates
        - start_from_min: True if pattern should start from min side (edge position)
    """
    # Get face's UV parameter range (this is what the sketch will use)
    evaluator = face.evaluator
    param_range = evaluator.parametricRange()
    if not param_range:
        return None

    param_min = param_range.minPoint
    param_max = param_range.maxPoint

    # Get corner points to determine face orientation
    (ret, corner1) = evaluator.getPointAtParameter(param_min)
    if not ret:
        return None
    (ret, corner2) = evaluator.getPointAtParameter(adsk.core.Point2D.create(param_max.x, param_min.y))
    if not ret:
        return None
    (ret, corner3) = evaluator.getPointAtParameter(param_max)
    if not ret:
        return None

    # Sketch X direction (along U parameter)
    sketch_x_length = corner1.distanceTo(corner2)
    # Sketch Y direction (along V parameter)
    sketch_y_length = corner2.distanceTo(corner3)

    # Get sketch X direction vector
    sketch_x_vec = adsk.core.Vector3D.create(
        corner2.x - corner1.x,
        corner2.y - corner1.y,
        corner2.z - corner1.z
    )
    sketch_x_vec.normalize()

    # Get edge direction
    edge_start = edge.startVertex.geometry
    edge_end = edge.endVertex.geometry
    edge_vec = adsk.core.Vector3D.create(
        edge_end.x - edge_start.x,
        edge_end.y - edge_start.y,
        edge_end.z - edge_start.z
    )
    edge_vec.normalize()

    # Calculate face center in world coordinates
    face_center_world = adsk.core.Point3D.create(
        (corner1.x + corner3.x) / 2,
        (corner1.y + corner3.y) / 2,
        (corner1.z + corner3.z) / 2
    )

    # Calculate edge midpoint in world coordinates
    edge_mid_world = adsk.core.Point3D.create(
        (edge_start.x + edge_end.x) / 2,
        (edge_start.y + edge_end.y) / 2,
        (edge_start.z + edge_end.z) / 2
    )

    # Transform both to sketch coordinates
    sketch_transform = sketch.transform
    sketch_transform.invert()

    face_center_sketch = adsk.core.Point3D.create(
        face_center_world.x, face_center_world.y, face_center_world.z
    )
    face_center_sketch.transformBy(sketch_transform)
    sketch_center_x = face_center_sketch.x
    sketch_center_y = face_center_sketch.y

    edge_mid_sketch = adsk.core.Point3D.create(
        edge_mid_world.x, edge_mid_world.y, edge_mid_world.z
    )
    edge_mid_sketch.transformBy(sketch_transform)

    # Check if edge is parallel to sketch X or sketch Y
    # Use dot product - if ~1 or ~-1, they're parallel
    dot = abs(sketch_x_vec.dotProduct(edge_vec))

    # Determine which side of the face the edge is on
    edge_on_min_x = edge_mid_sketch.x < sketch_center_x
    edge_on_min_y = edge_mid_sketch.y < sketch_center_y

    if dot > 0.9:  # Edge is along sketch X direction
        # Width (hexNumX) is along X, height is along Y
        # Pattern should start Y from the selected edge side
        return (sketch_x_length, sketch_y_length, True, sketch_center_x, sketch_center_y, edge_on_min_y)
    else:  # Edge is along sketch Y direction
        # Width (hexNumX) is along Y, height is along X
        # Pattern should start X from the selected edge side
        return (sketch_y_length, sketch_x_length, False, sketch_center_x, sketch_center_y, edge_on_min_x)


def _calculate_hex_layout(face_width, face_height, num_x, margin, pointy_top=False, start_from_min_y=True):
    """Calculate hexagon size and positions for honeycomb layout.

    Default orientation is pointy-top (vertices at top/bottom, flat edges on sides).
    This creates a proper honeycomb where hexes in the same row touch flat-to-flat,
    and rows nestle into each other via diagonal edges.

    Args:
        face_width: Width of the face (along hexNumX direction)
        face_height: Height of the face (perpendicular to hexNumX)
        num_x: Number of hexagons across the width
        margin: Gap between adjacent hex edges
        pointy_top: If True, use flat-top hexes instead (flat edges at top/bottom)
        start_from_min_y: If True, start rows from min Y; if False, start from max Y

    Returns:
        (radius, centers, pointy_top) - circumradius, list of (x,y) centers, orientation
    """
    sqrt3 = math.sqrt(3)

    # Hex width to fit num_x across with margin between each
    # face_width = num_x * hex_width + (num_x - 1) * margin
    hex_width = (face_width - (num_x - 1) * margin) / num_x

    if hex_width <= 0:
        raise RuntimeError(f"Hexagon margin too large for face width with {num_x} hexagons.")

    # For honeycomb pattern with hexNumX hexes along X:
    # - Default: flat vertical edges (hexes touch flat-to-flat along X)
    # - This means vertices point up/down (pointy top/bottom)
    # - hex_width (flat-to-flat horizontally) = sqrt(3) * r
    # - hex_height (vertex-to-vertex vertically) = 2 * r
    #
    # If pointy_top=True (user override): flat edges at top/bottom instead

    if pointy_top:
        # User wants flat edges at top/bottom (flat-top hex)
        # hex_width (vertex-to-vertex) = 2 * r
        # hex_height (flat-to-flat) = sqrt(3) * r
        radius = hex_width / 2
        hex_height = sqrt3 * radius
        row_spacing = 1.5 * radius + margin * sqrt3 / 2
        col_spacing = hex_width + margin
    else:
        # Default honeycomb: pointy top/bottom, flat edges left/right
        # hex_width (flat-to-flat) = sqrt(3) * r
        # hex_height (vertex-to-vertex) = 2 * r
        radius = hex_width / sqrt3
        hex_height = 2 * radius
        row_spacing = 1.5 * radius + margin * sqrt3 / 2
        col_spacing = hex_width + margin

    # Odd rows offset by half of column spacing
    row_x_offset = col_spacing / 2

    hex_half_width = hex_width / 2
    hex_half_height = hex_height / 2

    # Face bounds (sketch origin at face center)
    min_x = -face_width / 2
    max_x = face_width / 2
    min_y = -face_height / 2
    max_y = face_height / 2

    # Generate hex centers
    # X direction (width): exactly num_x hexes, no overspill (user-defined for symmetry)
    # Y direction (height): allow overspill to fill entire face with partial hexes
    # Y starts from selected edge side (min or max Y)
    centers = []

    start_x = min_x + hex_half_width

    if start_from_min_y:
        start_y = min_y + hex_half_height
        y_direction = 1
    else:
        start_y = max_y - hex_half_height
        y_direction = -1

    row = 0
    while True:
        y = start_y + row * row_spacing * y_direction

        # Y direction: stop only when hex is completely beyond the face (allow overspill)
        if y_direction > 0:
            if y - hex_half_height > max_y + 0.001:
                break
        else:
            if y + hex_half_height < min_y - 0.001:
                break

        # Odd rows offset horizontally
        x_offset = row_x_offset if (row % 2 == 1) else 0

        # X direction: exactly num_x hexes per row (or fewer for offset rows)
        col = 0
        while col < num_x:
            x = start_x + col * col_spacing + x_offset

            # Stop if hex right edge would extend beyond face
            if x + hex_half_width > max_x + 0.001:
                break

            centers.append((x, y))
            col += 1

        row += 1

    return radius, centers, pointy_top


def _run_impl(app, ui):
    """Main implementation logic."""
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        ui.messageBox('HexPattern: No active Fusion design.')
        return

    # Check selection - expect an edge
    sel = ui.activeSelections
    if sel.count != 1:
        ui.messageBox('HexPattern: Please select exactly one edge on a rectangular face.\n'
                      'The edge direction will be used for hexNumX alignment.')
        return

    edge = adsk.fusion.BRepEdge.cast(sel.item(0).entity)
    if not edge:
        ui.messageBox('HexPattern: Please select an edge (not a face or body).\n'
                      'The edge direction will be used for hexNumX alignment.')
        return

    # Get the face from the edge
    face = _get_face_from_edge(edge)
    if not face:
        ui.messageBox('HexPattern: Could not find a planar face for this edge.')
        return

    # Get parameters
    num_x_param = _get_user_param(design, 'hexNumX', param_type="int")
    margin_param = _get_user_param(design, 'hexMargin', param_type="length")
    pointy_param = _get_user_param(design, 'hexPointyTop', required=False)

    num_x = int(round(num_x_param.value))
    if num_x < 1:
        ui.messageBox('HexPattern: hexNumX must be at least 1.')
        return

    margin = margin_param.value  # Internal units (cm)

    # Check pointy top parameter (default: flat-top)
    pointy_top = False
    if pointy_param:
        pointy_val = pointy_param.expression.strip().strip("'\"").upper()
        pointy_top = pointy_val in ("TRUE", "YES", "1")

    # Start timeline group
    timeline = design.timeline
    timeline_start = timeline.markerPosition

    # Create sketch on face first (needed to get sketch coordinates)
    comp = face.body.parentComponent
    sketch = comp.sketches.add(face)

    # Get face dimensions using edge as the width direction
    face_info = _get_face_dimensions_from_edge(face, edge, sketch)
    if not face_info:
        ui.messageBox('HexPattern: Could not analyze face geometry.')
        return

    face_width, face_height, edge_is_along_x, sketch_center_x, sketch_center_y, start_from_min = face_info

    # Calculate hex layout
    try:
        radius, centers, pointy_top = _calculate_hex_layout(face_width, face_height, num_x, margin, pointy_top, start_from_min)
    except RuntimeError as e:
        ui.messageBox(f'HexPattern: {str(e)}')
        return

    if len(centers) == 0:
        ui.messageBox('HexPattern: No hexagons fit in the selected face.')
        return

    # Defer compute to batch all sketch operations (much faster)
    sketch.isComputeDeferred = True

    # Pre-calculate hexagon point offsets
    # For honeycomb with hexNumX along X axis, we need:
    # - Flat edges on left/right (so same-row hexes touch flat-to-flat)
    # - Diagonal edges on top/bottom (so rows nestle into each other)
    # This is "pointy-top" orientation: vertices at 90°, 150°, 210°, 270°, 330°, 30°
    #
    # The pointy_top parameter lets user flip to "flat-top" if desired
    hex_offsets = []
    for i in range(6):
        if pointy_top:
            # User requested flat-top: flat edge at top, vertices at 0°, 60°, 120°, 180°, 240°, 300°
            angle = i * math.pi / 3
        else:
            # Default for honeycomb: pointy-top (vertex at top)
            # Vertices at 90°, 150°, 210°, 270°, 330°, 30° (starting from top, going CCW)
            angle = math.pi / 2 + i * math.pi / 3
        hex_offsets.append((radius * math.cos(angle), radius * math.sin(angle)))

    # Draw all hexagons
    # Offset all coordinates by the face center in sketch space
    lines = sketch.sketchCurves.sketchLines
    for cx, cy in centers:
        for i in range(6):
            hx1 = hex_offsets[i][0]
            hy1 = hex_offsets[i][1]
            hx2 = hex_offsets[(i + 1) % 6][0]
            hy2 = hex_offsets[(i + 1) % 6][1]

            if edge_is_along_x:
                # Normal orientation: width (hexNumX) along sketch X
                # cx = position along width (X), cy = position along height (Y)
                x1 = sketch_center_x + cx + hx1
                y1 = sketch_center_y + cy + hy1
                x2 = sketch_center_x + cx + hx2
                y2 = sketch_center_y + cy + hy2
            else:
                # Rotated 90°: width (hexNumX) along sketch Y
                # cx = position along width -> goes to Y
                # cy = position along height -> goes to X
                # Hex offsets also rotate 90°: (hx, hy) -> (hy, -hx)
                x1 = sketch_center_x + cy + hy1
                y1 = sketch_center_y + cx - hx1
                x2 = sketch_center_x + cy + hy2
                y2 = sketch_center_y + cx - hx2

            lines.addByTwoPoints(
                adsk.core.Point3D.create(x1, y1, 0),
                adsk.core.Point3D.create(x2, y2, 0)
            )

    # Re-enable compute to create profiles
    sketch.isComputeDeferred = False
    adsk.doEvents()

    profiles = sketch.profiles
    hex_profiles = adsk.core.ObjectCollection.create()

    # Expected hex area (approximately)
    expected_area = 3 * math.sqrt(3) / 2 * radius * radius
    # Minimum area to filter out tiny slivers (10% of hex area)
    min_area = expected_area * 0.1
    # Maximum area (full hex + some tolerance)
    max_area = expected_area * 1.1

    for i in range(profiles.count):
        profile = profiles.item(i)
        try:
            area = profile.areaProperties().area
            # Select profiles that are between min and max area
            # This includes partial hexes at edges but excludes tiny slivers
            if min_area < area <= max_area:
                hex_profiles.add(profile)
        except:
            pass

    if hex_profiles.count == 0:
        ui.messageBox(
            f'HexPattern: No hexagon profiles found.\n'
            f'Drew {len(centers)} hexagons but could not identify closed profiles.\n'
            f'This may happen if hexagons overlap or extend outside the face.'
        )
        return

    # Cut the hexagons through the body
    extrudes = comp.features.extrudeFeatures
    cut_input = extrudes.createInput(hex_profiles, adsk.fusion.FeatureOperations.CutFeatureOperation)
    cut_input.setAllExtent(adsk.fusion.ExtentDirections.NegativeExtentDirection)

    try:
        cut_feature = extrudes.add(cut_input)
        cut_feature.name = f"{GENERATED_PREFIX}cut"
    except Exception as e:
        ui.messageBox(f'HexPattern: Cut failed - {str(e)}')
        return

    # Group timeline
    timeline_end = timeline.markerPosition
    if timeline_end - timeline_start >= 2:
        try:
            group = timeline.timelineGroups.add(timeline_start, timeline_end - 1)
            group.name = "HexPattern"
        except:
            pass

    ui.messageBox(
        f'HexPattern: Created {hex_profiles.count} hexagon cuts.\n'
        f'Hex radius: {radius * 10:.2f} mm'
    )


def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        _run_impl(app, ui)
    except Exception:
        if ui:
            ui.messageBox('HexPattern failed:\n{}'.format(traceback.format_exc()))


def stop(context):
    pass
