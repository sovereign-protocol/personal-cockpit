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

## Desktop window

The Cockpit can open in its own window with every installed application
mounted behind it, so you switch between topics from one place instead of
running a host per application:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[desktop]"
.\.venv\Scripts\sovereign-desktop.exe
```

Whichever source applications are installed are mounted; the rest are skipped,
so this still opens when one is absent.

### Building the combined executable

```powershell
.\.venv\Scripts\python.exe -m pip install -e ../s-kanban -e ../s-agreement pyinstaller
.\.venv\Scripts\pyinstaller.exe Sovereign.spec
```

The result is `dist/Sovereign.exe` — the Cockpit, S-Kanban, S-Agreement and the
Core they run on in a single window. It is not built in CI, because the other
applications do not yet resolve from an index; S-Kanban's repository keeps a
single-application spec that CI does exercise, which is what keeps the spec
format honest.

Building it for your own use carries no distribution obligations. Passing it to
anyone else does: `sovereign` is LGPL-3.0-or-later, so its notices and relinking
terms travel with the binary. Every application in it is Apache-2.0, so they add
no further condition.

## License

Software/assets are Apache-2.0; documentation is CC-BY-4.0. Sovereign Core is a
separately replaceable LGPL-3.0-or-later dependency.
