"""PediaPro's own colours.

The program has shipped as **PediaPro** since before this file existed — it is
in the footer of every screen and on the logo in the sidebar — and the logo is
blue with a green leaf. The interface was green throughout, so the product did
not look like its own mark.

These are the two colours from the design system that are unambiguous. They
are taken from the brand board rather than chosen here, which is why they are
constants with a source rather than numbers typed into a stylesheet: the next
person to want "the brand blue" should find one place holding it.

Nothing is forced. The clinic accent has always driven the whole palette —
one colour recolours the sidebar, the buttons, the chips and the cards — so
this only changes what a clinic gets **before** it chooses anything. A clinic
that wants its own colour still picks it in settings and nothing here argues.
"""

# Primary Pedia Blue — the "Pedia" half of the logo, and the chrome.
PRIMARY = "#0E6299"

# Secondary Pro Green — the leaf and the "Pro" half. Kept as the accent the
# theme already uses for growth and confirmation.
SECONDARY = "#4DAF4B"

# Dark grey for body text, from the same board.
INK = "#333333"
