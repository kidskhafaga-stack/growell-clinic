"""Tiny Code 39 barcode renderer (pure SVG, no dependencies).

Code 39 is the classic warehouse symbology: any cheap USB scanner reads it,
it needs no checksum, and it encodes A–Z, 0–9 and ``- . $ / + % space`` —
exactly the shape of our internal item codes (ITM-0001, VAC-0007…). Rendering
locally keeps label printing fully offline.
"""

# Each character = 9 elements (bars/spaces alternating, starting with a bar);
# '1' = wide element, '0' = narrow. Standard Code 39 table.
_CODE39 = {
    "0": "000110100", "1": "100100001", "2": "001100001", "3": "101100000",
    "4": "000110001", "5": "100110000", "6": "001110000", "7": "000100101",
    "8": "100100100", "9": "001100100", "A": "100001001", "B": "001001001",
    "C": "101001000", "D": "000011001", "E": "100011000", "F": "001011000",
    "G": "000001101", "H": "100001100", "I": "001001100", "J": "000011100",
    "K": "100000011", "L": "001000011", "M": "101000010", "N": "000010011",
    "O": "100010010", "P": "001010010", "Q": "000000111", "R": "100000110",
    "S": "001000110", "T": "000010110", "U": "110000001", "V": "011000001",
    "W": "111000000", "X": "010010001", "Y": "110010000", "Z": "011010000",
    "-": "010000101", ".": "110000100", " ": "011000100", "$": "010101000",
    "/": "010100010", "+": "010001010", "%": "000101010", "*": "010010100",
}


def _sanitise(code):
    out = "".join(c for c in (code or "").upper() if c in _CODE39 and c != "*")
    return out or "0"


def svg(code, height=48, narrow=2, wide=5, quiet=10):
    """Render ``code`` as a Code 39 SVG string (bars only, no caption)."""
    payload = f"*{_sanitise(code)}*"
    x = quiet
    rects = []
    for ch in payload:
        pattern = _CODE39[ch]
        for i, w in enumerate(pattern):
            width = wide if w == "1" else narrow
            if i % 2 == 0:  # even positions are bars, odd are spaces
                rects.append(
                    f'<rect x="{x}" y="0" width="{width}" height="{height}" />')
            x += width
        x += narrow  # inter-character narrow space
    total = x - narrow + quiet
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {height}" '
        f'width="{total}" height="{height}" fill="#000" '
        f'preserveAspectRatio="xMidYMid meet" role="img">{"".join(rects)}</svg>')
