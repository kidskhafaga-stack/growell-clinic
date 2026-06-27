# PediaPro brand assets (program identity)

Drop the official PediaPro logo files here and they become the program's
**default** identity — shown on the login screen and at the bottom of every
printout, alongside (never replacing) the clinic's own logo. No upload needed;
they ship inside the app.

## Files the app looks for

| File | Used where | Notes |
|------|-----------|-------|
| `pediapro-logo.png` | Login screen + print footer | **Required** for the default to appear. Horizontal colour logo (logo + "PediaPro" + slogan). Transparent PNG, ~600×200px. |
| `pediapro-mark.png` | (optional) compact spots / future favicon | Icon-only mark (the person-in-heart). Square, transparent. |

## How it resolves
1. If an admin uploads a logo in **Settings → Logo → Program logo**, that wins.
2. Otherwise, if `pediapro-logo.png` exists **here**, it is used automatically.
3. Otherwise the text name "PediaPro" + slogan is shown.

## To add via GitHub
Upload `pediapro-logo.png` into this folder (`app/static/img/brand/`) and
commit. That's it — the login page and printouts pick it up on the next load.
