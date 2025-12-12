# test_patterned_count.py
# Unit tests for PatternedCount logic that doesn't require Fusion 360 API
#
# Run with: python -m pytest test_patterned_count.py -v

import math
import pytest
from unittest.mock import MagicMock, patch
import sys

# Mock the adsk module before importing PatternedCount
adsk_mock = MagicMock()
adsk_mock.core = MagicMock()
adsk_mock.fusion = MagicMock()
sys.modules['adsk'] = adsk_mock
sys.modules['adsk.core'] = adsk_mock.core
sys.modules['adsk.fusion'] = adsk_mock.fusion

# Now we can import our module
sys.path.insert(0, 'PatternedCount')
import PatternedCount as pc


class TestFilterOuterProfiles:
    """Tests for _filter_outer_profiles - filters out holes inside other profiles."""

    def test_no_profiles(self):
        result = pc._filter_outer_profiles([])
        assert result == []

    def test_single_profile(self):
        profiles = [{'min': (0, 0), 'max': (10, 10), 'number': '1'}]
        result = pc._filter_outer_profiles(profiles)
        assert len(result) == 1

    def test_non_overlapping_profiles(self):
        profiles = [
            {'min': (0, 0), 'max': (10, 10), 'number': '1'},
            {'min': (20, 0), 'max': (30, 10), 'number': '2'},
            {'min': (40, 0), 'max': (50, 10), 'number': '3'},
        ]
        result = pc._filter_outer_profiles(profiles)
        assert len(result) == 3

    def test_inner_profile_filtered(self):
        """Inner profile (hole in "0" or "8") should be filtered out."""
        profiles = [
            {'min': (0, 0), 'max': (10, 10), 'number': '0'},  # Outer
            {'min': (2, 2), 'max': (8, 8), 'number': '0'},    # Inner (hole)
        ]
        result = pc._filter_outer_profiles(profiles)
        assert len(result) == 1
        assert result[0]['min'] == (0, 0)

    def test_multiple_with_holes(self):
        """Multiple characters, some with holes."""
        profiles = [
            # "0" with hole
            {'min': (0, 0), 'max': (10, 10), 'number': '0'},
            {'min': (2, 2), 'max': (8, 8), 'number': '0'},
            # "1" no hole
            {'min': (20, 0), 'max': (25, 10), 'number': '1'},
            # "8" with two holes (simplified as one for test)
            {'min': (40, 0), 'max': (50, 10), 'number': '8'},
            {'min': (42, 2), 'max': (48, 8), 'number': '8'},
        ]
        result = pc._filter_outer_profiles(profiles)
        assert len(result) == 3
        numbers = [p['number'] for p in result]
        assert '0' in numbers
        assert '1' in numbers
        assert '8' in numbers


class TestCircularModeGeometry:
    """Tests for circular mode geometry calculations."""

    def test_segment_angle_10_segments(self):
        """10 segments should give 36 degree (pi/5 radian) spacing."""
        seg_count = 10
        segment_angle = 2 * math.pi / seg_count
        assert abs(segment_angle - math.pi / 5) < 0.0001
        assert abs(math.degrees(segment_angle) - 36) < 0.01

    def test_segment_angle_12_segments(self):
        """12 segments should give 30 degree spacing."""
        seg_count = 12
        segment_angle = 2 * math.pi / seg_count
        assert abs(math.degrees(segment_angle) - 30) < 0.01

    def test_position_on_circle(self):
        """Test calculating position on circle from angle."""
        center_x, center_y = 5.0, 5.0
        radius = 2.0

        # At angle 0 (right side of circle)
        angle = 0
        x = center_x + radius * math.cos(angle)
        y = center_y + radius * math.sin(angle)
        assert abs(x - 7.0) < 0.0001
        assert abs(y - 5.0) < 0.0001

        # At angle pi/2 (top of circle)
        angle = math.pi / 2
        x = center_x + radius * math.cos(angle)
        y = center_y + radius * math.sin(angle)
        assert abs(x - 5.0) < 0.0001
        assert abs(y - 7.0) < 0.0001

    def test_clockwise_vs_counterclockwise(self):
        """CW should negate the segment angle."""
        seg_count = 10
        ccw_angle = 2 * math.pi / seg_count
        cw_angle = -ccw_angle

        # After 3 segments CCW, angle should be positive
        assert 3 * ccw_angle > 0
        # After 3 segments CW, angle should be negative
        assert 3 * cw_angle < 0


class TestLinearModeGeometry:
    """Tests for linear mode geometry calculations."""

    def test_position_plus_x(self):
        """Test +X direction positioning."""
        base_cx, base_cy = 0, 0
        pitch = 6.0
        dir_x, dir_y = 1, 0

        for i in range(10):
            target_cx = base_cx + i * pitch * dir_x
            target_cy = base_cy + i * pitch * dir_y
            assert target_cx == i * 6.0
            assert target_cy == 0

    def test_position_minus_x(self):
        """Test -X direction positioning."""
        base_cx, base_cy = 0, 0
        pitch = 6.0
        dir_x, dir_y = -1, 0

        for i in range(10):
            target_cx = base_cx + i * pitch * dir_x
            assert target_cx == -i * 6.0

    def test_position_plus_y(self):
        """Test +Y direction positioning."""
        base_cx, base_cy = 0, 0
        pitch = 6.0
        dir_x, dir_y = 0, 1

        for i in range(10):
            target_cy = base_cy + i * pitch * dir_y
            assert target_cy == i * 6.0


class TestCollectTextBoxes:
    """Tests for _collect_text_boxes function."""

    def test_rotation_angles_calculated(self):
        """Test that rotation angles are calculated correctly for circular mode."""
        # Mock texts collection
        mock_texts = MagicMock()
        mock_texts.count = 3

        def make_mock_text(text_val, cx, cy):
            t = MagicMock()
            t.text = text_val
            t.boundingBox.minPoint.x = cx - 1
            t.boundingBox.minPoint.y = cy - 1
            t.boundingBox.maxPoint.x = cx + 1
            t.boundingBox.maxPoint.y = cy + 1
            return t

        mock_texts.item = lambda i: [
            make_mock_text('0', 0, 0),
            make_mock_text('1', 5, 0),
            make_mock_text('2', 10, 0),
        ][i]

        start_number = 0
        segment_angle = math.pi / 5  # 36 degrees

        result = pc._collect_text_boxes(mock_texts, start_number, True, segment_angle)

        assert len(result) == 3
        assert result[0]['rotation'] == 0  # Template, no rotation
        assert abs(result[1]['rotation'] - segment_angle) < 0.0001
        assert abs(result[2]['rotation'] - 2 * segment_angle) < 0.0001

    def test_linear_mode_no_rotation(self):
        """In linear mode, all rotation angles should be 0."""
        mock_texts = MagicMock()
        mock_texts.count = 2

        def make_mock_text(text_val):
            t = MagicMock()
            t.text = text_val
            t.boundingBox.minPoint.x = 0
            t.boundingBox.minPoint.y = 0
            t.boundingBox.maxPoint.x = 1
            t.boundingBox.maxPoint.y = 1
            return t

        mock_texts.item = lambda i: make_mock_text(str(i))

        result = pc._collect_text_boxes(mock_texts, 0, False, 0)

        assert all(tb['rotation'] == 0 for tb in result)


class TestDirectionParsing:
    """Tests for direction parameter parsing logic."""

    @pytest.mark.parametrize("dir_str,expected", [
        ("+X", (1, 0)),
        ("-X", (-1, 0)),
        ("+Y", (0, 1)),
        ("-Y", (0, -1)),
        ("+x", (1, 0)),  # lowercase
        ("-y", (0, -1)),
        ("  +X  ", (1, 0)),  # whitespace
    ])
    def test_direction_parsing(self, dir_str, expected):
        """Test various direction string formats."""
        dir_str_clean = dir_str.strip().strip("'\"").upper()
        dir_x, dir_y = 1, 0  # default
        if dir_str_clean == "-X":
            dir_x, dir_y = -1, 0
        elif dir_str_clean == "+Y":
            dir_x, dir_y = 0, 1
        elif dir_str_clean == "-Y":
            dir_x, dir_y = 0, -1

        assert (dir_x, dir_y) == expected


class TestArcDirectionParsing:
    """Tests for arc direction parameter parsing."""

    @pytest.mark.parametrize("arc_str,expected_cw", [
        ("CW", True),
        ("CCW", False),
        ("cw", True),
        ("ccw", False),
        ("  CW  ", True),
        ("'CW'", True),
        ('"CCW"', False),
    ])
    def test_arc_direction_parsing(self, arc_str, expected_cw):
        """Test various arc direction string formats."""
        arc_str_clean = arc_str.strip().strip("'\"").upper()
        arc_clockwise = arc_str_clean == "CW"
        assert arc_clockwise == expected_cw


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
