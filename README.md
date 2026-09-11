# Tech Atlas

Tech Atlas builds a technology radar: it crawls a register of sources, extracts
technology mentions with AI agents, and scores each technology. It is an API +
MongoDB backend, and it pairs with **[Tech Lens](https://github.com/rauthanak/tech-lens)**,
the web portal you use in your browser.

This guide gets everything running on your own computer **without any coding
tools** — you install one app (Docker Desktop), paste one key into one file, and
run one command. Follow the section for your computer: [Mac](#run-it-on-a-mac)
or [Windows](#run-it-on-windows).

**What you need**

- A Mac or Windows computer with about 10 GB of free disk space
- An internet connection (the first start downloads a few GB)
- An OpenAI API key (next section — this is the only account you must create)
- 30–45 minutes the first time; later starts take seconds

---

## First: get an OpenAI API key

The AI agents need a key to work, and running them costs a small amount of
money billed to that key.

1. Go to <https://platform.openai.com> and create an account (or sign in).
2. Open **Settings → Billing** and add a payment method. Adding a small amount
   of credit (e.g. $10) is enough to try things out.
3. Open **API keys** (under Settings) and click **Create new secret key**.
4. Copy the key — it looks like `sk-...` and is **shown only once**. Paste it
   somewhere safe (Notes) until you use it in the steps below.

---

## Run it on a Mac

### 1. Download the code (two projects)

The two projects must sit **next to each other in the same folder**, with these
exact names:

```
TechRadar/            ← a folder you create, anywhere you like
├── tech-atlas/
└── tech-lens/
```

1. In your browser open <https://github.com/rauthanak/tech-atlas>, click the
   green **Code** button, then **Download ZIP**.
2. Do the same at <https://github.com/rauthanak/tech-lens>.
3. In **Downloads**, double-click each ZIP to unpack it. You get folders named
   `tech-atlas-main` and `tech-lens-main`.
4. **Rename them** (click the name, press Return) to exactly `tech-atlas` and
   `tech-lens` — the trailing `-main` must go, or the start command below will
   fail.
5. Make a new folder (e.g. `TechRadar` in your home folder) and drag both
   renamed folders into it.

### 2. Install Docker Desktop

Docker Desktop is the app that runs everything; with it you don't need to
install anything else (no database, no programming languages).

1. Go to <https://www.docker.com/products/docker-desktop/> and download
   **Docker Desktop for Mac**. Pick **Apple Silicon** unless your Mac is
   Intel-based ( → **About This Mac** shows the chip).
2. Open the downloaded `.dmg` and drag **Docker** into **Applications**.
3. Launch **Docker** from Applications. The first launch:
   - asks you to accept the service agreement — accept;
   - may offer a sign-in — you can **skip** it;
   - asks for your **Mac password** — enter it (this installs the `docker`
     command your Terminal will use; no manual PATH changes are needed).
4. Wait until the whale icon in the menu bar (top right) stops animating and
   says **Docker Desktop is running**.

### 3. Put your API key in place

1. Open **Terminal** (press `⌘`+`Space`, type `Terminal`, press Return).
2. Copy-paste these three lines, pressing Return after each (adjust the first
   line if you put the folder somewhere other than your home folder):

   ```bash
   cd ~/TechRadar/tech-atlas
   cp .env.example .env
   open -e .env
   ```

3. TextEdit opens a settings file. Find the line `OPENAI_API_KEY=` and paste
   your key right after the `=` (no spaces), so it reads
   `OPENAI_API_KEY=sk-...`. Save (`⌘`+`S`) and close TextEdit.

### 4. Start it

In the same Terminal window:

```bash
docker compose up
```

- The **first** start builds everything and downloads a few GB — expect 5–15
  minutes of scrolling text. Later starts take seconds.
- Leave this window open; it shows the live logs. The apps keep running until
  you stop them.

If Terminal says `command not found: docker`: Docker Desktop is not running
yet (step 2.4), or this Terminal window is older than the Docker install —
open a **new** Terminal window, `cd ~/TechRadar/tech-atlas`, and try again.

### 5. Check that it works

- Open <http://localhost:3100> in your browser — the **Tech Lens portal**
  should appear. This is the app you use.
- <http://localhost:8100/api/health> should show a short technical reply —
  that's the API confirming it is up.

### 6. Stopping and restarting

- **Stop:** click the Terminal window and press `Ctrl`+`C`.
- **Start again later:** open Terminal, `cd ~/TechRadar/tech-atlas`,
  `docker compose up`. Your data is kept between runs.
- You can also open the **Docker Desktop** app to see the three running parts
  (`mongo`, `atlas`, `lens`) with start/stop buttons and logs.

---

## Run it on Windows

### 1. Download the code (two projects)

The two projects must sit **next to each other in the same folder**, with these
exact names:

```
TechRadar\            ← a folder you create, anywhere you like
├── tech-atlas\
└── tech-lens\
```

1. In your browser open <https://github.com/rauthanak/tech-atlas>, click the
   green **Code** button, then **Download ZIP**.
2. Do the same at <https://github.com/rauthanak/tech-lens>.
3. In **Downloads**, right-click each ZIP → **Extract All…**. You get folders
   named `tech-atlas-main` and `tech-lens-main`.
4. **Rename them** (right-click → Rename) to exactly `tech-atlas` and
   `tech-lens` — the trailing `-main` must go, or the start command below will
   fail.
5. Make a new folder, e.g. `C:\TechRadar`, and move both renamed folders into
   it.

### 2. Install Docker Desktop

Docker Desktop is the app that runs everything; with it you don't need to
install anything else (no database, no programming languages).

1. Go to <https://www.docker.com/products/docker-desktop/> and download
   **Docker Desktop for Windows** (the standard AMD64 download fits almost all
   PCs).
2. Run the installer. Keep **"Use WSL 2"** ticked if asked. It may ask to
   **restart your computer** — do so.
3. Launch **Docker Desktop** from the Start menu. Accept the service
   agreement; you can **skip** the sign-in. The installer sets up everything
   the command line needs — no manual PATH changes.
4. If it reports that WSL 2 or virtualization is missing, follow the link it
   shows (a small Microsoft update) and start Docker Desktop again.
5. Wait until the whale icon in the system tray (bottom right) says
   **Docker Desktop is running**.

### 3. Put your API key in place

1. Open **PowerShell** (press the Windows key, type `PowerShell`, press
   Enter).
2. Copy-paste these three lines, pressing Enter after each (adjust the first
   line if you used a different folder):

   ```powershell
   cd C:\TechRadar\tech-atlas
   copy .env.example .env
   notepad .env
   ```

3. Notepad opens a settings file. Find the line `OPENAI_API_KEY=` and paste
   your key right after the `=` (no spaces), so it reads
   `OPENAI_API_KEY=sk-...`. Save and close Notepad.

### 4. Start it

In the same PowerShell window:

```powershell
docker compose up
```

- The **first** start builds everything and downloads a few GB — expect 5–15
  minutes of scrolling text. Later starts take seconds.
- Leave this window open; it shows the live logs. The apps keep running until
  you stop them.

If PowerShell says `docker` is not recognized: Docker Desktop is not running
yet (step 2.5), or this PowerShell window is older than the Docker install —
open a **new** PowerShell window, `cd C:\TechRadar\tech-atlas`, and try again.

### 5. Check that it works

- Open <http://localhost:3100> in your browser — the **Tech Lens portal**
  should appear. This is the app you use.
- <http://localhost:8100/api/health> should show a short technical reply —
  that's the API confirming it is up.

### 6. Stopping and restarting

- **Stop:** click the PowerShell window and press `Ctrl`+`C`.
- **Start again later:** open PowerShell, `cd C:\TechRadar\tech-atlas`,
  `docker compose up`. Your data is kept between runs.
- You can also open the **Docker Desktop** app to see the three running parts
  (`mongo`, `atlas`, `lens`) with start/stop buttons and logs.

---

## If something goes wrong

| What you see | What it means / what to do |
| --- | --- |
| `command not found: docker` / `'docker' is not recognized` | Docker Desktop isn't running, or your terminal window is older than the install. Start Docker Desktop, wait for "running", open a **new** terminal window. |
| `Cannot connect to the Docker daemon` | Docker Desktop is installed but not running. Launch it and wait for the whale. |
| `port is already allocated` (mentions 27017, 8100, or 3100) | Another program on your computer uses that port. On a Mac with a locally installed MongoDB, run `brew services stop mongodb-community` and try again. |
| Build error mentioning `../tech-lens` | The folders aren't side by side, or the `-main` rename in step 1 was skipped. |
| `MongoDB cannot start: Linux kernel versions 6.19 and newer…` | A workaround for this is already built in (`GLIBC_TUNABLES` on the `mongo` service in `docker-compose.yml`). If you still see it, you may have an old copy of the code — re-download it. If it persists, change `image: mongo:8` to `image: mongo:7` in `docker-compose.yml` and start again. |
| First start seems stuck for minutes | Normal — it is downloading and building. Watch Docker Desktop's whale menu or the scrolling log. |

Anything else: copy the last ~20 lines of the log and send them to whoever
gave you these repos.

---

## For developers (run without Docker)

Native setup needs local installs: **MongoDB** listening on
`localhost:27017`, **Python 3.12+**, and **Node.js** (for tech-lens).

- macOS/Linux: `./start.sh` in each project.
- Windows: double-click `start.bat` (runs `start.ps1`) in each project.

Both scripts create the environment, install dependencies, seed the database
(tech-atlas), and start dev servers: API on **8100**, portal on **3100**.
Settings live in `.env` (created from `.env.example` on first start).
