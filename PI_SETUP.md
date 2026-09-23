# Running Algo_Beta on a Raspberry Pi (lite branch)

This branch (`raspberry-pi-lite`) strips three things out of the Windows
system for a headless Pi 4/5 (Raspberry Pi OS 64-bit recommended):

| Dropped | Why | Replacement |
|---|---|---|
| `algo_beta_gui/` desktop dashboard | needs a display; customtkinter/tkinter | [ui/glass_cockpit.html](ui/glass_cockpit.html) (view in a browser) + Telegram |
| FinBERT sentiment (torch/transformers) | ~2GB install, slow inference on ARM CPU | off by default (`ENABLE_FINBERT=False`); re-enable if you want it |
| Sound alerts (pygame) | went with the GUI, wasn't used elsewhere | Telegram notifications (already wired in) |

Everything else — PH1 through PH9, the orchestrator, Kalman/TCAS/ILS,
Zerodha connectivity — is the same code as `main`, unmodified.

## 1. System packages

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip build-essential wget \
    chromium-chromedriver chromium-browser
```

## 2. TA-Lib C library (must be built before `pip install TA-Lib`)

```bash
wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
tar -xzf ta-lib-0.4.0-src.tar.gz
cd ta-lib
./configure --prefix=/usr
make
sudo make install
cd ..
```

## 3. Clone and set up the venv

```bash
git clone -b raspberry-pi-lite https://github.com/dheeban87-jpg/Algo_Beta.git
cd Algo_Beta
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements-pi.txt
```

If `pip install TA-Lib` fails with a build error, it means step 2 didn't
put the library where pip expects it — confirm `/usr/lib/libta_lib.so`
exists, then retry.

## 4. Credentials

Nothing to do here — `config.py` ships with working credentials as fallback
defaults, so a plain `git clone` on the Pi already has everything it needs.
No env vars to export, no editing required.

This does mean the same credentials travel with every clone of this repo.
That's an accepted tradeoff for this private setup; if that ever changes
(repo goes public, gets shared, etc.) rotate the credentials and switch to
environment variables instead — the `os.environ.get('X', "fallback")`
pattern already in `config.py` supports that without any code change, an
env var just needs to be exported before `python orchestrator.py` runs.

## 5. Runtime directories

The Pi needs these created before first run (git doesn't track empty/
runtime directories):

```bash
mkdir -p logs data regret_logs
```

## 6. Run it

Foreground, to confirm it starts cleanly:

```bash
source venv/bin/activate
python orchestrator.py
```

For unattended running, use a systemd service instead of the Windows Task
Scheduler entries referenced in `eod_trade_consolidator.py`'s docstring —
those are Windows-only and don't apply here. A minimal unit:

```ini
# /etc/systemd/system/algo-beta.service
[Unit]
Description=Algo_Beta trading orchestrator
After=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/Algo_Beta
ExecStart=/home/pi/Algo_Beta/venv/bin/python orchestrator.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now algo-beta
journalctl -u algo-beta -f
```

## What's not yet verified

This branch has been reviewed for import-time crashes (Windows-only APIs,
torch/transformers required unconditionally) but has **not** been run
end-to-end on real Pi hardware. Before trusting it with real capital:

1. Run a full day in paper mode on the Pi and diff the trade log against
   the same day run on the Windows box, if both are running in parallel.
2. Watch CPU/memory under `htop` during market hours — PH2's per-stock
   scan loop and Kalman updates were tuned on a desktop CPU, not ARM.
3. Confirm Selenium + chromium-chromedriver actually completes the Kite
   login flow — this is the piece most likely to behave differently on
   ARM Chromium versus desktop Chrome.
