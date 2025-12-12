# HexPattern.py
# Cuts a honeycomb pattern of hexagons from a selected rectangular face.
#
# Usage:
# 1. Select an edge on a rectangular face (defines width direction for hex count)
# 2. Run this script from Scripts & Add-Ins
# 3. Enter parameters in the dialog that appears

import adsk.core
import adsk.fusion
import traceback
import math

# Prefix for generated features
GENERATED_PREFIX = "hex#"

# Global variables for command handlers
_app = None
_ui = None
_selected_edge = None
_selected_face = None
_face_width = None
_handlers = []


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


def _calculate_hex_layout(face_width, face_height, num_x, margin, pointy_top=False, start_from_min_y=True, allow_partial=False):
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
        allow_partial: If True, include partial hexes at edges; if False, only full hexes

    Returns:
        (radius, centers, pointy_top) - circumradius, list of (x,y) centers, orientation
    """
    sqrt3 = math.sqrt(3)

    if pointy_top:
        # Flat-top hex (flat edges at top/bottom, vertices on sides)
        # hex_width (vertex-to-vertex) = 2 * r
        # hex_height (flat-to-flat) = sqrt(3) * r
        #
        # In flat-top honeycomb, same-row hexes are spaced 3r apart (not 2r)
        # face_width = 2r + (num_x - 1) * (3r + margin)
        # Solving for r: r = (face_width - (num_x-1) * margin) / (3*num_x - 1)
        radius = (face_width - (num_x - 1) * margin) / (3 * num_x - 1)
        if radius <= 0:
            raise RuntimeError(f"Hexagon margin too large for face width with {num_x} hexagons.")
        hex_width = 2 * radius
        hex_height = sqrt3 * radius
        row_spacing = 0.5 * hex_height + margin * 0.5
        col_spacing = 3 * radius + margin
    else:
        # Pointy-top hex (vertices at top/bottom, flat edges on sides)
        # hex_width (flat-to-flat) = sqrt(3) * r
        # hex_height (vertex-to-vertex) = 2 * r
        #
        # face_width = num_x * hex_width + (num_x - 1) * margin
        hex_width = (face_width - (num_x - 1) * margin) / num_x
        if hex_width <= 0:
            raise RuntimeError(f"Hexagon margin too large for face width with {num_x} hexagons.")
        radius = hex_width / sqrt3
        hex_height = 2 * radius
        row_spacing = 0.75 * hex_height + margin * sqrt3 / 2
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

    # For partial hexes, start one row earlier to catch partials on the first edge
    first_row = -1 if allow_partial else 0

    row = first_row
    while True:
        y = start_y + row * row_spacing * y_direction

        # Y direction boundary check
        if allow_partial:
            # Stop only when hex is completely beyond the face
            if y_direction > 0:
                if y - hex_half_height > max_y + 0.001:
                    break
            else:
                if y + hex_half_height < min_y - 0.001:
                    break
            # Also skip if hex is completely before the face (for row -1 check)
            if y_direction > 0:
                if y + hex_half_height < min_y - 0.001:
                    row += 1
                    continue
            else:
                if y - hex_half_height > max_y + 0.001:
                    row += 1
                    continue
        else:
            # Stop if hex would extend beyond face (full hexes only)
            if y_direction > 0:
                if y + hex_half_height > max_y + 0.001:
                    break
            else:
                if y - hex_half_height < min_y - 0.001:
                    break

        # Odd rows offset horizontally (use absolute row index for offset calc)
        x_offset = row_x_offset if (abs(row) % 2 == 1) else 0

        if allow_partial:
            # Add partial hex on left edge if visible
            left_hex_x = start_x + x_offset - col_spacing
            if left_hex_x + hex_half_width > min_x - 0.001:
                centers.append((left_hex_x, y))

            # X direction: hexes across the row (allow partial on right)
            col = 0
            while True:
                x = start_x + col * col_spacing + x_offset

                # Stop if hex is completely beyond face
                if x - hex_half_width > max_x + 0.001:
                    break

                centers.append((x, y))
                col += 1
        else:
            # Only full hexes - must fit entirely within face
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


def _calculate_hex_width(face_width, num_x, margin, pointy_top):
    """Calculate hex width given parameters."""
    sqrt3 = math.sqrt(3)
    if pointy_top:
        # Flat-top: radius = (face_width - (num_x-1) * margin) / (3*num_x - 1)
        radius = (face_width - (num_x - 1) * margin) / (3 * num_x - 1)
        if radius <= 0:
            return 0
        return 2 * radius  # hex_width = 2r for flat-top
    else:
        # Pointy-top: hex_width directly from face fit
        hex_width = (face_width - (num_x - 1) * margin) / num_x
        if hex_width <= 0:
            return 0
        return hex_width


def _execute_hex_pattern(face, edge, num_x, margin, pointy_top, allow_partial=False):
    """Execute the hex pattern cut operation."""
    global _app, _ui

    design = adsk.fusion.Design.cast(_app.activeProduct)

    # Start timeline group
    timeline = design.timeline
    timeline_start = timeline.markerPosition

    # Create sketch on face first (needed to get sketch coordinates)
    comp = face.body.parentComponent
    sketch = comp.sketches.add(face)

    # Get face dimensions using edge as the width direction
    face_info = _get_face_dimensions_from_edge(face, edge, sketch)
    if not face_info:
        _ui.messageBox('HexPattern: Could not analyze face geometry.')
        return

    face_width, face_height, edge_is_along_x, sketch_center_x, sketch_center_y, start_from_min = face_info

    # Calculate hex layout
    try:
        radius, centers, pointy_top = _calculate_hex_layout(face_width, face_height, num_x, margin, pointy_top, start_from_min, allow_partial)
    except RuntimeError as e:
        _ui.messageBox(f'HexPattern: {str(e)}')
        return

    if len(centers) == 0:
        _ui.messageBox('HexPattern: No hexagons fit in the selected face.')
        return

    # Defer compute to batch all sketch operations (much faster)
    sketch.isComputeDeferred = True

    # Pre-calculate hexagon point offsets
    hex_offsets = []
    for i in range(6):
        if pointy_top:
            angle = i * math.pi / 3
        else:
            angle = math.pi / 2 + i * math.pi / 3
        hex_offsets.append((radius * math.cos(angle), radius * math.sin(angle)))

    # Draw all hexagons
    lines = sketch.sketchCurves.sketchLines
    for cx, cy in centers:
        for i in range(6):
            hx1 = hex_offsets[i][0]
            hy1 = hex_offsets[i][1]
            hx2 = hex_offsets[(i + 1) % 6][0]
            hy2 = hex_offsets[(i + 1) % 6][1]

            if edge_is_along_x:
                x1 = sketch_center_x + cx + hx1
                y1 = sketch_center_y + cy + hy1
                x2 = sketch_center_x + cx + hx2
                y2 = sketch_center_y + cy + hy2
            else:
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

    # Expected hex area - used to filter profiles
    expected_area = 3 * math.sqrt(3) / 2 * radius * radius
    # Min area: small enough for corner partials, large enough to exclude margin slivers
    # Margin slivers are roughly margin * edge_length, which is much smaller than even tiny hex partials
    min_area = expected_area * 0.03  # 3% of full hex
    max_area = expected_area * 1.1

    for i in range(profiles.count):
        profile = profiles.item(i)
        try:
            area = profile.areaProperties().area
            if min_area < area <= max_area:
                hex_profiles.add(profile)
        except:
            pass

    if hex_profiles.count == 0:
        _ui.messageBox(
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
        _ui.messageBox(f'HexPattern: Cut failed - {str(e)}')
        return

    # Group timeline
    timeline_end = timeline.markerPosition
    if timeline_end - timeline_start >= 2:
        try:
            group = timeline.timelineGroups.add(timeline_start, timeline_end - 1)
            group.name = "HexPattern"
        except:
            pass

    _ui.messageBox(
        f'HexPattern: Created {hex_profiles.count} hexagon cuts.\n'
        f'Hex width: {_calculate_hex_width(face_width, num_x, margin, pointy_top) * 10:.2f} mm'
    )


class HexPatternCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            cmd = args.command
            cmd.setDialogMinimumSize(300, 200)
            inputs = cmd.commandInputs

            # Add number of hexes input
            num_input = inputs.addIntegerSpinnerCommandInput('numHexes', 'Number of Hexes', 1, 100, 1, 5)

            # Add hex width info display (directly under number of hexes)
            hex_width_text = inputs.addTextBoxCommandInput('hexWidthInfo', 'Hex Width', '', 1, True)

            # Add margin input (in mm for display)
            margin_input = inputs.addValueInput('margin', 'Margin', 'mm', adsk.core.ValueInput.createByReal(0.05))  # 0.5mm default

            # Add orientation radio buttons
            orientation_group = inputs.addRadioButtonGroupCommandInput('orientation', '')
            orientation_items = orientation_group.listItems
            orientation_items.add('Flat Top', True)  # Default selected
            orientation_items.add('Pointy Top', False)

            # Add partial hexes option
            inputs.addBoolValueInput('allowPartial', 'Cut partial hexes at edges', True, '', False)

            _update_hex_width_display(inputs)

            # Connect to input changed event
            onInputChanged = HexPatternInputChangedHandler()
            cmd.inputChanged.add(onInputChanged)
            _handlers.append(onInputChanged)

            # Connect to execute event
            onExecute = HexPatternExecuteHandler()
            cmd.execute.add(onExecute)
            _handlers.append(onExecute)

            # Connect to destroy event (for cleanup when dialog closes)
            onDestroy = HexPatternDestroyHandler()
            cmd.destroy.add(onDestroy)
            _handlers.append(onDestroy)

        except:
            _ui.messageBox('Failed to create command:\n{}'.format(traceback.format_exc()))


class HexPatternInputChangedHandler(adsk.core.InputChangedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            _update_hex_width_display(args.inputs)
        except:
            pass


class HexPatternExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            global _selected_edge, _selected_face

            inputs = args.command.commandInputs

            num_x = inputs.itemById('numHexes').value
            margin = inputs.itemById('margin').value  # Already in cm (internal units)

            orientation_group = inputs.itemById('orientation')
            pointy_top = orientation_group.selectedItem.name == 'Flat Top'

            allow_partial = inputs.itemById('allowPartial').value

            _execute_hex_pattern(_selected_face, _selected_edge, num_x, margin, pointy_top, allow_partial)

        except:
            _ui.messageBox('Failed to execute:\n{}'.format(traceback.format_exc()))


class HexPatternDestroyHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        # Terminate the script when dialog closes
        adsk.terminate()


def _update_hex_width_display(inputs):
    """Update the hex width info text based on current inputs."""
    global _face_width

    if _face_width is None:
        return

    num_input = inputs.itemById('numHexes')
    margin_input = inputs.itemById('margin')
    hex_width_text = inputs.itemById('hexWidthInfo')
    orientation_group = inputs.itemById('orientation')

    if not all([num_input, margin_input, hex_width_text, orientation_group]):
        return

    num_x = num_input.value
    margin = margin_input.value  # Internal units (cm)
    pointy_top = orientation_group.selectedItem.name == 'Flat Top'

    hex_width = _calculate_hex_width(_face_width, num_x, margin, pointy_top)

    if hex_width <= 0:
        hex_width_text.text = 'Margin too large'
    else:
        # Convert from cm to mm for display
        hex_width_text.text = f'{hex_width * 10:.2f} mm'


def _run_impl(app, ui):
    """Main implementation logic - validates selection and shows dialog."""
    global _selected_edge, _selected_face, _face_width

    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        ui.messageBox('HexPattern: No active Fusion design.')
        return

    # Check selection - expect an edge
    sel = ui.activeSelections
    if sel.count != 1:
        ui.messageBox('HexPattern: Please select exactly one edge on a rectangular face.\n'
                      'The edge direction will be used for hex count alignment.')
        return

    edge = adsk.fusion.BRepEdge.cast(sel.item(0).entity)
    if not edge:
        ui.messageBox('HexPattern: Please select an edge (not a face or body).\n'
                      'The edge direction will be used for hex count alignment.')
        return

    # Get the face from the edge
    face = _get_face_from_edge(edge)
    if not face:
        ui.messageBox('HexPattern: Could not find a planar face for this edge.')
        return

    # Store selection for use in dialog
    _selected_edge = edge
    _selected_face = face

    # Calculate face width for the dialog
    # We need a temporary sketch to get face dimensions
    comp = face.body.parentComponent
    temp_sketch = comp.sketches.add(face)
    face_info = _get_face_dimensions_from_edge(face, edge, temp_sketch)
    temp_sketch.deleteMe()

    if not face_info:
        ui.messageBox('HexPattern: Could not analyze face geometry.')
        return

    _face_width = face_info[0]  # Store face width for hex width calculation

    # Create and show the command dialog
    cmdDefs = ui.commandDefinitions

    # Clean up any existing command definition
    existing_cmd = cmdDefs.itemById('HexPatternCmd')
    if existing_cmd:
        existing_cmd.deleteMe()

    cmd_def = cmdDefs.addButtonDefinition('HexPatternCmd', 'Hex Pattern', 'Create hexagon pattern cutouts')

    onCommandCreated = HexPatternCommandCreatedHandler()
    cmd_def.commandCreated.add(onCommandCreated)
    _handlers.append(onCommandCreated)

    cmd_def.execute()


def run(context):
    global _app, _ui, _handlers
    try:
        _app = adsk.core.Application.get()
        _ui = _app.userInterface
        _handlers = []

        # Prevent script from terminating while dialog is open
        adsk.autoTerminate(False)

        _run_impl(_app, _ui)
    except Exception:
        if _ui:
            _ui.messageBox('HexPattern failed:\n{}'.format(traceback.format_exc()))


def stop(context):
    # Re-enable auto terminate when script stops
    adsk.autoTerminate(True)
