# blueland
A reactive Bluetooth frontend daemon for Hyprland users.

## What is this?
Blueland is a modular Python backend that manages Bluetooth device connections, pairing, and authentication on Linux, with full D-Bus integration and optional Zenity-powered prompts for PIN/passkey confirmations. Designed for Hyprland (or other Wayland-based desktops that Blueman does not support), it replaces clunky tools like Blueman with a reactive, developer-friendly Bluetooth agent.

## Features:
- Pair, connect, and trust devices with a single D-Bus call (org.blueland.Frontend.PairConnDevice, with device MAC address)
- PIN/Passkey UI via Zenity (no need to touch the terminal)
- Live device stream via Unix socket (/run/user/<userid>/blueland/blueland.sock) for frontend integration
- Modular backend API for CLI wrappers or graphical frontends

## What it cannot do:
- A full-fledged UI like [blueman](https://github.com/blueman-project/blueman) or [overskride](https://github.com/kaii-lb/overskride) (you might want to check out [blueland-frontend](https://github.com/nelideven/blueland-frontend) instead)
- Manage multiple adapters (currently hardcoded to /org/bluez/hci0)
- Automatically handle low-level audio routing (e.g. Default sink/source switching)
- Persist device state across reboots (i.e. cache is session-based)
- Replace BlueZ. It wraps and enhances BlueZ, not reimplementing it

## Dependencies:
- dbus-next (pip install dbus-next)
- BlueZ
- Python 3.9 or higher
- Zenity

## Usage

1. Clone the repo:
```
bash
git clone https://github.com/yourname/blueland.git
cd blueland
```

2. Run the backend
```
python blueland.py
```

## Example D-Bus methods:
```
# Discover visible + paired devices
gdbus call --session \
  -d org.blueland.Frontend \
  -o /org/blueland/Frontend \
  -m org.blueland.Frontend.DiscoverDevices

# Pair, trust, and connect a device by MAC address
gdbus call --session \
  -d org.blueland.Frontend \
  -o /org/blueland/Frontend \
  -m org.blueland.Frontend.PairConnDevice \
  <device mac addr>

# Disconnect a device
gdbus call --session \
  -d org.blueland.Frontend \
  -o /org/blueland/Frontend \
  -m org.blueland.Frontend.DisconnectDevice \
  <device mac addr>

# Remove device from BlueZ cache
gdbus call --session \
  -d org.blueland.Frontend \
  -o /org/blueland/Frontend \
  -m org.blueland.Frontend.RemoveDevice \
  <device mac addr>
```
