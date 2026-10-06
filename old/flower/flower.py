#! /usr/bin/env python

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle

# --- CONFIGURATION ---
PAGE_WIDTH = 8.5
PAGE_HEIGHT = 11.0
LIGHT_GREY = '#CCCCCC'  # Very light, subtle grey
LINE_WIDTH = 0.5  # Thinner line


def generate_version_1():
  """Version 1: Full page repeating Seed of Life with 1-inch radius circles."""
  fig, ax = plt.subplots(figsize=(PAGE_WIDTH, PAGE_HEIGHT))
  ax.set_xlim(0, PAGE_WIDTH)
  ax.set_ylim(0, PAGE_HEIGHT)
  ax.set_aspect('equal')
  ax.axis('off')

  R = 1.0  # 1-inch radius

  y_min, y_max = -1.0, PAGE_HEIGHT + 1.0
  x_min, x_max = -1.0, PAGE_WIDTH + 1.0

  j = 0
  y = y_min
  while y <= y_max:
    x_offset = (j % 2) * (R * 0.5)
    x = x_min + x_offset
    while x <= x_max:
      circle = Circle(
          (x, y),
          R,
          color=LIGHT_GREY,
          fill=False,
          linewidth=LINE_WIDTH,
      )
      ax.add_patch(circle)
      x += R
    y += R * (np.sqrt(3) / 2)
    j += 1

  plt.savefig(
      'seed_of_life_full_page.pdf',
      format='pdf',
      bbox_inches='tight',
      pad_inches=0,
  )
  plt.close()
  print('Generated: seed_of_life_full_page.pdf')


def generate_version_2():
  """Version 2: Grid of 1-inch cutout circles.

  Each cutout is completely filled with a repeating mini Seed of Life pattern
  (1/8" radius circles).
  """
  fig, ax = plt.subplots(figsize=(PAGE_WIDTH, PAGE_HEIGHT))
  ax.set_xlim(0, PAGE_WIDTH)
  ax.set_ylim(0, PAGE_HEIGHT)
  ax.set_aspect('equal')
  ax.axis('off')

  outer_radius = 1.0  # 1 inch radius for the cutout circle
  mini_radius = 1.0 / 8.0  # 1/8 inch radius for the mini pattern

  # Grid layout: 4 columns x 5 rows fits neatly on an 8.5 x 11 page
  col_centers = [1.25, 3.25, 5.25, 7.25]
  row_centers = [1.5, 3.5, 5.5, 7.5, 9.5]

  for cx in col_centers:
    for cy in row_centers:
      # 1. Draw the outer 1-inch radius dashed cut line
      outer_circle = Circle(
          (cx, cy),
          outer_radius,
          color='#999999',
          fill=False,
          linewidth=0.8,
          linestyle='--',
      )
      ax.add_patch(outer_circle)

      # 2. Fill the interior with a repeating hexagonal grid of mini circles (1/8" radius)
      # We span a bounding box around (cx, cy) of size outer_radius * 2
      y_min = cy - outer_radius - mini_radius
      y_max = cy + outer_radius + mini_radius
      x_min = cx - outer_radius - mini_radius
      x_max = cx + outer_radius + mini_radius

      row_idx = 0
      y = y_min
      while y <= y_max:
        x_offset = (row_idx % 2) * (mini_radius * 0.5)
        x = x_min + x_offset
        while x <= x_max:
          # Check if the mini circle center is close enough to be inside the 1" cutout
          dist = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
          if dist <= (outer_radius + mini_radius * 0.5):
            mini_circle = Circle(
                (x, y),
                mini_radius,
                color=LIGHT_GREY,
                fill=False,
                linewidth=LINE_WIDTH,
            )
            ax.add_patch(mini_circle)
          x += mini_radius
        y += mini_radius * (np.sqrt(3) / 2)
        row_idx += 1

  plt.savefig(
      'seed_of_life_cutouts.pdf',
      format='pdf',
      bbox_inches='tight',
      pad_inches=0,
  )
  plt.close()
  print('Generated: seed_of_life_cutouts.pdf')


if __name__ == '__main__':
  generate_version_1()
  generate_version_2()
  print('All updated pattern PDFs generated successfully!')
