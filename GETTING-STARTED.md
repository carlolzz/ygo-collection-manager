# Getting started

A guide to running the YGO Collection Explorer on your own computer. No
programming needed — you'll copy and paste one command.

It takes about 15 minutes, most of which is waiting for a download.

---

## What this app does

You point it at a CSV file exported from the card scanner app, and it gives you
a browsable, searchable view of your collection: card artwork, filters, charts,
a rough value, and a tool that checks a deck list against what you own and tells
you what you're missing.

Everything runs on your own computer. Nothing is uploaded anywhere, and the app
never changes your collection file — it only reads it.

---

## Step 1 — Install Docker Desktop

Docker is a free tool that runs an app in a self-contained bundle, so you don't
have to install anything else or configure anything.

1. Go to **<https://www.docker.com/products/docker-desktop/>**
2. Click the download button for your system (Windows, Mac, or Linux).
   - On a Mac, pick **Apple Silicon** if your Mac is from 2020 or later, or
     **Intel** if it's older. Not sure? Click the  menu → *About This Mac*;
     if it says "Apple M1/M2/M3/M4", you want Apple Silicon.
3. Open the downloaded file and follow the installer.
4. **Restart your computer** if it asks you to.
5. Open Docker Desktop. The first launch takes a minute and may ask you to
   accept an agreement. You can skip the sign-in — an account is not needed.

You'll know it's ready when the Docker Desktop window shows a green **Engine
running** indicator at the bottom left.

> **Leave Docker Desktop open** whenever you want to use the app. If you close
> it, the app stops.

---

## Step 2 — Make a folder for your collection

Make a new folder somewhere you'll remember — your Desktop is fine. Call it
something like `ygo-explorer`.

Inside it, make **another** folder called exactly `data`. So you have:

```
ygo-explorer/
└── data/
```

Now put your collection export — the `.csv` file from the scanner app — inside
the `data` folder. It'll have a name like `ygo_collection_2026-07-28.csv`.

Don't have one yet? That's fine, carry on. The app will let you add it later
through a button in the browser.

---

## Step 3 — Open a terminal in that folder

A terminal is a window where you type commands. Don't worry — you only need one.

**Windows:** Open the `ygo-explorer` folder in File Explorer. Click the address
bar at the top, type `powershell`, and press Enter.

**Mac:** Right-click the `ygo-explorer` folder → *Services* → *New Terminal at
Folder*. (If you don't see it: open *Terminal* from Applications → Utilities,
type `cd ` with a space, then drag the folder onto the window and press Enter.)

**Linux:** Right-click inside the folder → *Open in Terminal*.

---

## Step 4 — Start the app

Copy this line, paste it into the terminal, and press Enter:

**Windows (PowerShell):**

```powershell
docker run -p 8000:8000 -v "${PWD}\data:/data" charliegordonmouse/ygo-explorer
```

**Mac or Linux:**

```bash
docker run -p 8000:8000 -v "$PWD/data:/data" charliegordonmouse/ygo-explorer
```

The first time, this downloads the app — about 500 MB, so it may take a few
minutes. You'll see a lot of text scroll past. That's normal.

> **On an Apple Silicon Mac** (M1 and later) you may see a warning about the
> image's platform not matching. It's safe to ignore — the app runs fine, just a
> little slower to start.

When it's ready you'll see a line like:

```
Uvicorn running on http://0.0.0.0:8000
```

Leave that terminal window open. Closing it stops the app.

---

## Step 5 — Open it in your browser

Go to **<http://localhost:8000>**

That's it. If your CSV was in the `data` folder, your collection is already
there. If not, the page will show a **Choose a CSV export** button.

### One thing to do on your first visit

A yellow bar across the top will say **Card data not downloaded yet**. Click
**Download card data** and wait about a minute.

That fetches a catalogue of every Yu-Gi-Oh card — roughly 21 MB, once — which is
where card pictures, stats and prices come from. Until you do it, your cards
will show as plain names with no artwork.

You only ever need to do this again if you want newer prices, and the app will
tell you when the data is over a month old.

---

## Using it day to day

**To start the app:** open Docker Desktop, then run the same command from
Step 4 in the same folder.

**To stop it:** click the terminal window and press `Ctrl + C`. Or quit Docker
Desktop.

**To update to a newer version:**

```
docker pull charliegordonmouse/ygo-explorer
```

Then start it as usual.

**Your data stays put.** Everything the app downloads goes into the `data`
folder. You can delete `data/cache` any time to free up space — it'll just
download again next time.

---

## What the pages do

| Page | What it's for |
|---|---|
| **Browse** | Your cards, with pictures. Filter by anything; the web address updates so you can bookmark a filtered view. |
| **Statistics** | Charts: what conditions you own, which types, when you added things, which cards you have most of. |
| **Valuation** | Press a button to get a rough total value. It's clearly labelled an estimate, and it tells you how confident it is. |
| **Deck check** | Paste a deck list and see what you're missing and roughly what it'd cost. |

### About the deck check

Paste in either kind of deck export from EDOPro — the long `ydke://...` code, or
a plain typed list like:

```
Main Deck:
3 Sabersaurus
2 Rescue Rabbit

Side Deck:
2 Maxx "C"
```

It works out which cards you're short of, counting the main, extra and side deck
together, since you need those cards at the same time. A different artwork of a
card still counts as owning it.

### About the prices

They're **estimates**, and the app says so next to every total. They come from a
free community card database, not from a shop, so treat them as a rough guide —
useful for "is this deck €20 or €200", not for insurance.

---

## If something goes wrong

**"docker: command not found" or "Cannot connect to the Docker daemon"**
Docker Desktop isn't running. Open it and wait for **Engine running**.

**"port is already allocated"**
Something else is using port 8000. Use a different one — change `-p 8000:8000`
to `-p 8080:8000` and then visit <http://localhost:8080> instead.

**The page won't load**
Give it a few seconds after starting. Check the terminal for the "Uvicorn
running" line. Make sure you typed `localhost:8000`, not `0.0.0.0:8000`.

**My collection isn't showing**
Check the `.csv` file is directly inside the `data` folder, not in a subfolder,
and that its name starts with `ygo_collection_`. Restart the app after adding
it. Or just use the upload button on the page.

**No card pictures**
They download as you browse, a few at a time, on purpose — the card database
asks apps not to hammer their servers. Give it a moment and refresh.

**I'm on Windows and my data keeps disappearing**
You're probably using Git Bash, which garbles folder paths for Docker. Use
PowerShell instead (Step 3).

---

## Is this safe?

- Everything runs on your computer. Your collection is never uploaded.
- The app only reads your CSV file — it can't change or delete it.
- It only uses the internet to download the public card catalogue and card
  pictures, and only when you ask it to.
- No account, no sign-up, no tracking.

Card names, images and data belong to their respective owners. This is a
personal tool for looking at a collection you already own, and isn't affiliated
with or endorsed by Konami or YGOPRODeck.
