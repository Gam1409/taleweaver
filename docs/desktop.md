# Desktop applications

Windows, macOS and Linux share one supervisor and the same web application.
Docker remains the server-oriented fourth distribution; it has no desktop tray.
The supervisor starts one owned backend process, which serves the built frontend.
Python, Node.js and model weights do not need to be installed by desktop users.
AI and image providers still use the endpoints configured in Administration.

## Starting and controlling the application

Launch `TaleWeaver.exe`, `TaleWeaver.app`, or the Linux `TaleWeaver` executable.
The tray menu has **Start / Stop / Restart / Log / Exit**, plus **Open TaleWeaver**.
The default browser opens once the backend and frontend script both respond.
Health recovery does not open duplicate tabs.

- Green: the owned process, API readiness endpoint, frontend HTML and JavaScript respond.
- Red: explicitly stopped.
- Yellow: starting, stopping, a crashed process or an unhealthy backend/frontend.

Stop and Exit request graceful shutdown, then terminate only the owned process
if it does not exit. An occupied port is an error; the launcher never adopts or
kills a different server. A per-profile OS file lock prevents duplicate launchers.
Opening the application while its profile is already locked returns exit code 2.

## User data and updates

The default profile uses the OS application-data directory:

| OS | Location |
| --- | --- |
| Windows | `%LOCALAPPDATA%\TaleWeaver` |
| macOS | `~/Library/Application Support/TaleWeaver` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/TaleWeaver` |

`server.env` stores generated signing/encryption keys; `data/` holds SQLite,
sessions and media; `memory/` holds RAG; `logs/desktop.log` includes server output.
Logs rotate at 5 MB with two backups. Secrets and logs are outside public media.
Keys are generated only for a new profile and persist across updates. A database
without its original keys is rejected instead of silently rekeyed. Back up the
whole profile before updating. Replacing the application bundle does not replace
the profile. `--data-dir PATH` selects a different profile, including paths with spaces.

The service binds only `127.0.0.1`. Change `BACKEND_PORT` in `server.env` while
stopped if the default 8000 is occupied. Provider environment settings can also
be added there. The normal web setup flow creates the first administrator.

## Build and CI policy

Builds are native: Windows on Windows, macOS on macOS, Linux on Ubuntu 22.04.
The resulting Linux minimum is that build's glibc; older distributions require
their own build. macOS artifacts use the runner's architecture, shown by Actions.
Preview builds are unsigned; macOS notarization and Windows publisher signing
require separately configured release credentials. No signing keys are bundled.

The **Desktop distributions** workflow runs lightweight launcher tests on all
three operating systems for launcher changes. Full packaging runs only for
`v*` release tags or **Run workflow**. It builds the frontend, packages the service,
then runs the actual executable against a disposable profile. A second smoke
test initializes the native tray and menu and waits for readiness without opening
a browser. Linux uses a private D-Bus session and Xvfb for that check. No LLM
requests are made. Failed startup, migrations, API or missing frontend fail the job.
Archives are uploaded as Actions artifacts, rather than committed into Git.

For a local build with Python 3.12 and Node 22:

```sh
poetry install --with packaging --extras desktop
cd frontend
npm ci
npm run build
cd ..
poetry run python scripts/build_desktop.py --logo /path/to/original.png
poetry run python scripts/smoke_desktop.py dist/TaleWeaver/TaleWeaver
```

Use `.exe` on Windows or `dist/TaleWeaver.app/Contents/MacOS/TaleWeaver` on macOS.
The checked-in original is `docs/branding/visualnovel.jpg`; it is the default logo.
Linux builds need GTK, GObject introspection and Ayatana AppIndicator development
packages (the workflow lists exact packages). A desktop panel supporting status
icons is required; for example GNOME may need its AppIndicator extension. A
headless server should use Docker or the regular web server instead of the tray.

## Memory

The tray uses native OS menus through pystray and a 64-pixel icon. There is no
embedded Chromium, Vite or second web server. The headless source smoke test on
6 November 2026 measured peak RSS **21.7 MiB for the supervisor** and **268.9 MiB
for its backend**, with a fresh profile and no model calls. This excludes native
tray libraries, the external browser, populated sessions and active requests;
it is not a packaged-application memory guarantee. Each native build reports its
own measured headless and native-tray launcher/service peaks. RAG, transcription and other optional work
can add memory when used; those model workloads are not started by the tray.
