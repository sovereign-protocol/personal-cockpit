# Personal Cockpit

Personal Cockpit is a standalone local view that aggregates summaries from
active Sovereign applications through optional, versioned public facades. It
does not own or reinterpret source-application protocol trees and remains usable
when any source application is absent.

## Quickstart

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\sovereign-host.exe 9307 config/personal-cockpit.example.json
```

Install source applications separately and list them before Personal Cockpit in
the host configuration to enable their adapters.

Software/assets are Apache-2.0; documentation is CC-BY-4.0. Sovereign Core is a
separately replaceable LGPL-3.0-or-later dependency.
