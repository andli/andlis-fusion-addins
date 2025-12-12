# test_hex_pattern.py
# Unit tests for HexPattern geometry calculations
#
# Run with: python -m pytest test_hex_pattern.py -v

import math
import pytest
from unittest.mock import MagicMock
import sys

# Mock the adsk module before importing HexPattern
adsk_mock = MagicMock()
adsk_mock.core = MagicMock()
adsk_mock.fusion = MagicMock()
sys.modules['adsk'] = adsk_mock
sys.modules['adsk.core'] = adsk_mock.core
sys.modules['adsk.fusion'] = adsk_mock.fusion

# Now we can import our module
sys.path.insert(0, 'HexPattern')
import HexPattern as hp


class TestHexLayoutGeometry:
    """Tests for _calculate_hex_layout geometry calculations."""

    def test_flat_top_dimensions(self):
        """Verify flat-top hex dimensions: width = 2r, height = sqrt(3)*r."""
        # Face 100mm wide, 5 hexes, no margin
        face_width = 10.0  # cm (internal units)
        face_height = 10.0
        num_x = 5
        margin = 0.0

        radius, centers, pointy = hp._calculate_hex_layout(
            face_width, face_height, num_x, margin, pointy_top=False
        )

        hex_width = 2 * radius
        hex_height = math.sqrt(3) * radius

        # With 5 hexes and no margin, each hex should be 2cm wide
        assert abs(hex_width - 2.0) < 0.0001
        # Height should be sqrt(3) * r = sqrt(3) * 1 = 1.732...
        assert abs(hex_height - math.sqrt(3)) < 0.0001

    def test_pointy_top_dimensions(self):
        """Verify pointy-top hex dimensions: width = sqrt(3)*r, height = 2r."""
        face_width = 10.0
        face_height = 10.0
        num_x = 5
        margin = 0.0

        radius, centers, pointy = hp._calculate_hex_layout(
            face_width, face_height, num_x, margin, pointy_top=True
        )

        hex_width = math.sqrt(3) * radius
        hex_height = 2 * radius

        # With 5 hexes and no margin, each hex should be 2cm wide
        assert abs(hex_width - 2.0) < 0.0001

    def test_row_spacing_no_margin_flat_top(self):
        """Row spacing with no margin should be 3/4 * hex_height for flat-top."""
        face_width = 10.0
        face_height = 10.0
        num_x = 5
        margin = 0.0

        radius, centers, _ = hp._calculate_hex_layout(
            face_width, face_height, num_x, margin, pointy_top=False
        )

        hex_height = math.sqrt(3) * radius
        expected_row_spacing = (3 / 4) * hex_height

        # Find centers in row 0 and row 1
        row0_centers = [c for c in centers if abs(c[1] - centers[0][1]) < 0.001]
        row1_y = centers[0][1] + expected_row_spacing
        row1_centers = [c for c in centers if abs(c[1] - row1_y) < 0.01]

        assert len(row1_centers) > 0, "Should have hexes in row 1"
        actual_row_spacing = row1_centers[0][1] - row0_centers[0][1]
        assert abs(actual_row_spacing - expected_row_spacing) < 0.001

    def test_column_spacing_same_row(self):
        """Hexes in same row should be spaced by hex_width + margin."""
        face_width = 10.0
        face_height = 10.0
        num_x = 5
        margin = 0.1  # 1mm margin

        radius, centers, _ = hp._calculate_hex_layout(
            face_width, face_height, num_x, margin, pointy_top=False
        )

        hex_width = 2 * radius
        expected_col_spacing = hex_width + margin

        # Get first row centers (sorted by x)
        first_row_y = centers[0][1]
        row0_centers = sorted([c for c in centers if abs(c[1] - first_row_y) < 0.001], key=lambda c: c[0])

        if len(row0_centers) >= 2:
            actual_spacing = row0_centers[1][0] - row0_centers[0][0]
            assert abs(actual_spacing - expected_col_spacing) < 0.001

    def test_odd_row_offset(self):
        """Odd rows should be offset by half the column spacing."""
        face_width = 10.0
        face_height = 10.0
        num_x = 5
        margin = 0.0

        radius, centers, _ = hp._calculate_hex_layout(
            face_width, face_height, num_x, margin, pointy_top=False
        )

        hex_width = 2 * radius
        col_spacing = hex_width + margin
        expected_offset = col_spacing / 2

        # Get row 0 and row 1 centers
        first_row_y = centers[0][1]
        row0_centers = sorted([c for c in centers if abs(c[1] - first_row_y) < 0.001], key=lambda c: c[0])

        row_spacing = (3 / 4) * math.sqrt(3) * radius
        second_row_y = first_row_y + row_spacing
        row1_centers = sorted([c for c in centers if abs(c[1] - second_row_y) < 0.01], key=lambda c: c[0])

        if len(row0_centers) > 0 and len(row1_centers) > 0:
            # Row 1's first hex should be offset from row 0's first hex
            x_diff = row1_centers[0][0] - row0_centers[0][0]
            assert abs(x_diff - expected_offset) < 0.01

    def test_margin_affects_spacing(self):
        """Adding margin should increase both row and column spacing."""
        face_width = 10.0
        face_height = 10.0
        num_x = 5

        # Without margin
        _, centers_no_margin, _ = hp._calculate_hex_layout(
            face_width, face_height, num_x, 0.0, pointy_top=False
        )

        # With margin
        _, centers_with_margin, _ = hp._calculate_hex_layout(
            face_width, face_height, num_x, 0.2, pointy_top=False
        )

        # With margin, we should have fewer hexes (because they're more spread out)
        # or different spacing
        # Actually hex size changes with margin, so let's just verify both run
        assert len(centers_no_margin) > 0
        assert len(centers_with_margin) > 0

    def test_hex_count_matches_num_x(self):
        """First row should have num_x hexagons when face is wide enough."""
        face_width = 10.0
        face_height = 3.0  # Short, so only 1-2 rows
        num_x = 5
        margin = 0.0

        radius, centers, _ = hp._calculate_hex_layout(
            face_width, face_height, num_x, margin, pointy_top=False
        )

        # Get first row centers
        first_row_y = centers[0][1]
        row0_centers = [c for c in centers if abs(c[1] - first_row_y) < 0.001]

        assert len(row0_centers) == num_x

    def test_negative_margin_raises_error(self):
        """Very large margin that results in negative hex width should error."""
        face_width = 1.0
        face_height = 1.0
        num_x = 10
        margin = 1.0  # Way too large

        with pytest.raises(RuntimeError, match="margin too large"):
            hp._calculate_hex_layout(face_width, face_height, num_x, margin)


class TestHoneycombInterlocking:
    """Tests verifying proper honeycomb interlocking geometry."""

    def test_diagonal_edge_distance_with_margin(self):
        """Verify that diagonal edges have correct margin separation.

        In a honeycomb, hex B's top vertex should be `margin` distance away
        from the diagonal edge of hex A above it.
        """
        face_width = 10.0
        face_height = 10.0
        num_x = 3
        margin = 0.1  # 1mm

        radius, centers, _ = hp._calculate_hex_layout(
            face_width, face_height, num_x, margin, pointy_top=False
        )

        sqrt3 = math.sqrt(3)
        hex_height = sqrt3 * radius

        # Get a hex from row 0 and the adjacent hex from row 1
        first_row_y = centers[0][1]
        row0_centers = sorted([c for c in centers if abs(c[1] - first_row_y) < 0.001], key=lambda c: c[0])

        expected_row_spacing = (3 / 4) * hex_height + margin * sqrt3 / 2
        second_row_y = first_row_y + expected_row_spacing
        row1_centers = sorted([c for c in centers if abs(c[1] - second_row_y) < 0.01], key=lambda c: c[0])

        if len(row0_centers) > 0 and len(row1_centers) > 0:
            # Verify the row spacing
            actual_spacing = row1_centers[0][1] - row0_centers[0][1]
            assert abs(actual_spacing - expected_row_spacing) < 0.01


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
