# HexPattern – Honeycomb Cut Pattern

**HexPattern** creates a honeycomb pattern of hexagonal cuts on a selected rectangular face. Great for ventilation grilles, decorative panels, speaker covers, or lightweight structures.

![HexPattern Example](example.png)

## Features

- Creates evenly-spaced flat-top hexagons in a honeycomb arrangement
- Automatically calculates hexagon size to fit specified count across width
- Configurable margin/gap between hexagons
- Cuts through the entire body thickness
- Fully parameter-driven — **no GUI**, no prompts

## User Parameters

Create these parameters in **Modify → Change Parameters**.

| Name        | Type           | Description                                          |
| ----------- | -------------- | ---------------------------------------------------- |
| `hexNumX`   | Unitless (int) | Number of hexagons across the face width (e.g., `5`) |
| `hexMargin` | Length         | Gap between hexagon edges (e.g., `0.5 mm`)           |

**Note:** Integer parameters must be created as **unitless** (leave the Unit field blank).

## Usage

1. Create your user parameters (`hexNumX`, `hexMargin`)
2. Select an edge on a rectangular face — this edge defines the "width" direction for `hexNumX`
3. Run **HexPattern** from **Scripts and Add-Ins** (`Shift+S`)
4. The add-in will:
   - Calculate hexagon size based on the edge length and `hexNumX`
   - Generate a honeycomb layout filling the face
   - Cut through the body with all hexagons

## How Sizing Works

- The hexagon radius is calculated so that exactly `hexNumX` hexagons fit along the selected edge
- The `hexMargin` parameter creates gaps between adjacent hexagon edges
- Rows alternate with a half-column offset (standard honeycomb pattern)
- Hexagons that would extend outside the face boundaries are omitted

## Notes

- Works best with rectangular or near-rectangular faces
- The selected edge determines which direction `hexNumX` applies to
- Very large margins relative to face size may result in no hexagons fitting
