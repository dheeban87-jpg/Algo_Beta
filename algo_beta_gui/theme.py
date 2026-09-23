"""
Algo_Beta GUI -- Central Theme v2.0
=====================================
Claude-inspired warm light theme with high readability.
Larger fonts matching CMD prompt clarity.
All views import from here — single source of truth.
"""

# ═══════════════════════════════════════════════════════════════════════════════
#  COLOR PALETTE — Warm light theme (Claude-inspired)
# ═══════════════════════════════════════════════════════════════════════════════

# Backgrounds — warm cream/beige tones
BG_APP       = "#F5F0E8"    # main app background (warm parchment)
BG_SIDEBAR   = "#EDE7DB"    # sidebar (slightly darker cream)
BG_PANEL     = "#FFFFFF"    # card/panel background (clean white)
BG_HEADER    = "#E8E0D0"    # section headers (warm tan)
BG_INPUT     = "#FAF8F4"    # input fields, log background (soft white)
BG_INFOBAR   = "#E5DFD3"    # bottom info bar
BG_NAV_ACTIVE = "#DDD5C5"   # active nav item

# Borders
BORDER       = "#C8BFA8"    # main borders (warm gray)
BORDER_DIM   = "#D8D0C0"    # subtle borders

# Text — bold black for maximum readability
TEXT_PRIMARY  = "#000000"   # main text (pure black)
TEXT_LABEL    = "#000000"   # label text (black)
TEXT_MUTED    = "#333333"   # secondary text (dark)
TEXT_DIM      = "#666666"   # disabled/placeholder
TEXT_ENTRY    = "#000000"   # input text (black)

# Accent — Claude's signature warm orange + professional blues
ACCENT_PRIMARY = "#D97706"  # warm amber/orange (primary accent)
ACCENT_CYAN    = "#0369A1"  # professional blue (links, active items)

# Status colors — vivid on light background
GREEN  = "#16A34A"          # success/profit (forest green)
RED    = "#DC2626"          # error/loss (clear red)
AMBER  = "#D97706"          # warning (warm amber)
CYAN   = "#0284C7"          # info/detail (sky blue)
WHITE  = "#FFFFFF"

# Sidebar button colors — dark blue
SIDEBAR_BTN_BG     = "#1B4F72"   # dark blue background
SIDEBAR_BTN_HOVER  = "#154360"   # darker blue hover
SIDEBAR_BTN_TEXT   = "#FFFFFF"   # white text on dark blue

# Phase button colors
PHASE_BTN_BG      = "#1B4F72"   # dark blue (matches sidebar)
PHASE_BTN_HOVER   = "#154360"   # darker blue hover
PHASE_BTN_BORDER  = "#1A3E5C"   # dark blue border
PHASE_BTN_TEXT    = "#FFFFFF"   # white text on dark blue

# Aviation/gauge colors (used in phase_details.py)
SKY_BLUE     = "#1A6DD4"
SKY_BLUE_LT  = "#2D8CF0"
GROUND_BROWN = "#8B5E3C"
GROUND_DARK  = "#5A3D28"
HORIZON_LINE = "#1A1A1A"   # dark on light
AIRCRAFT_REF = "#D97706"
BB_UPPER     = "#DC2626"
BB_LOWER     = "#DC2626"
BB_MIDDLE    = "#0284C7"

ZONE_COLORS = {"green": GREEN, "amber": AMBER, "red": RED}


# ═══════════════════════════════════════════════════════════════════════════════
#  FONT DEFINITIONS — CMD-prompt sized for clarity
# ═══════════════════════════════════════════════════════════════════════════════

FONT_FAMILY = "Consolas"    # monospace, matches CMD prompt

# Named font tuples (family, size, weight)
FONT_LOGO       = (FONT_FAMILY, 16, "bold")     # app title
FONT_TITLE      = (FONT_FAMILY, 14, "bold")     # section titles
FONT_HEADING    = (FONT_FAMILY, 13, "bold")     # sub-headings
FONT_BODY_BOLD  = (FONT_FAMILY, 12, "bold")     # labels, buttons
FONT_BODY       = (FONT_FAMILY, 12)             # regular text
FONT_SMALL_BOLD = (FONT_FAMILY, 11, "bold")     # compact labels
FONT_SMALL      = (FONT_FAMILY, 11)             # compact text
FONT_TINY_BOLD  = (FONT_FAMILY, 10, "bold")     # compact bold labels
FONT_TINY       = (FONT_FAMILY, 10)             # footnotes, dim text
FONT_LOG        = (FONT_FAMILY, 12)             # log/console text
FONT_NAV        = (FONT_FAMILY, 12, "bold")     # sidebar nav items
FONT_BUTTON     = (FONT_FAMILY, 12, "bold")     # buttons
FONT_VERSION    = (FONT_FAMILY, 10)             # version strings


# ═══════════════════════════════════════════════════════════════════════════════
#  APPEARANCE MODE
# ═══════════════════════════════════════════════════════════════════════════════

CTK_APPEARANCE = "light"
CTK_THEME      = "blue"
