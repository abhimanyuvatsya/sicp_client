# Philips SICP Tablet Controller

This project provides a resilient controller for Philips signage tablets that expose the
[SICP protocol](https://westanonline.sharepoint.com/sites/Support/Shared%20Documents/Forms/AllItems.aspx?id=%2Fsites%2FSupport%2FShared%20Documents%2FBDL%20Technical%2FTechnical%20Documents%2FSICP%20Protocol%2FLatest%20SICP%20Document&p=true&ga=1).
It can manage multiple tablets from a single Raspberry Pi, surfaces the LED accent strip
and panel power controls through MQTT/Home Assistant, and includes a web UI for manual
control and troubleshooting.

## Features

- **Multi-tablet management** – define any number of tablets with static IP addresses and
  poll them on configurable intervals.
- **Two-way synchronisation** – every control action is confirmed with a subsequent `GET`
  request and the latest power/LED state is published back to MQTT and the web UI.
- **Home Assistant integration** – MQTT discovery exposes each tablet as a `light` (for
  LED colour) and a `switch` (for power). State updates flow in both directions.
- **Resilient networking** – retry logic, error logging, and periodic refreshes keep the
  controller healthy even when tablets drop offline.
- **Web dashboard** – built-in FastAPI app for issuing manual commands, viewing tablet
  status, and tailing recent logs directly from the Pi.
- **CLI compatibility** – the original `sicp_client.py` command line remains available for
  ad-hoc diagnostics.
- **Automated deployment** – an Ansible playbook provisions a Raspberry Pi (tested with a
  fresh Raspberry Pi OS Lite install) including a systemd service.

## Project layout

```
├── src/sicp/           # Python package (protocol helpers, MQTT bridge, service, web UI)
├── sicp_client.py      # CLI wrapper (calls `python -m sicp.cli`)
├── ansible/            # Playbook, inventory, and templates for deployment
├── pyproject.toml      # Packaging metadata and runtime dependencies
└── README.md           # You are here
```

## Runtime requirements

- Python 3.10 or newer (Python 3.11 ships with modern Raspberry Pi OS releases)
- Network access from the Pi to every Philips tablet on TCP port 5000
- An MQTT broker (the Home Assistant Mosquitto add-on works well)

## Configuration file

The service reads `/etc/sicp/config.yaml` by default. Example:

```yaml
mqtt:
  host: mqtt.local
  port: 1883
  username: your-ha-user
  password: "supersecret"
  base_topic: sicp
  ha_discovery_prefix: homeassistant

socket_timeout: 5.0
socket_retries: 2
socket_retry_delay: 1.0
web_host: 0.0.0.0
web_port: 8080
log_buffer: 2000

tablets:
  - id: tablet01
    name: Lobby Tablet
    host: 192.168.2.101
    port: 5000
    poll_interval: 30
  - id: tablet02
    name: Training Room Tablet
    host: 192.168.2.102
    poll_interval: 45
```

### MQTT topics & Home Assistant

For each tablet `tablet01`, the controller uses the following topics (configurable via the
`base_topic` variable):

- `sicp/tablet01/light/set` – JSON command payload (e.g. `{"state":"ON","color":{"r":255,"g":64,"b":0}}`).
- `sicp/tablet01/light/state` – JSON state payload mirrored to Home Assistant.
- `sicp/tablet01/power/set` – Plain-text `ON`/`OFF` commands for panel power.
- `sicp/tablet01/power/state` – Current power state.
- `sicp/tablet01/attributes` – Diagnostic attributes (last refresh, last error, IP).
- `sicp/status` – Availability topic published as `online`/`offline`.

MQTT discovery publishes:

- `homeassistant/light/tablet01/config` – RGB light entity controlling the LED strip.
- `homeassistant/switch/tablet01/config` – Switch entity for panel power.

Home Assistant will automatically add the entities once discovery is enabled on the
broker.

## Running the service manually

```bash
# Clone the project and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Launch the service (ensure config.yaml exists)
sicp-service --config ./config.yaml
```

The web dashboard becomes available at `http://<pi-ip>:8080/` by default. Use the
`/logs` page for quick debugging.

## Command line client

The legacy CLI remains available for quick checks:

```bash
python3 sicp_client.py 192.168.2.101 get
python3 sicp_client.py 192.168.2.101 set --color "#FF0000"
python3 sicp_client.py 192.168.2.101 power off
```

All retry/timeout options are still supported (`--timeout`, `--retries`, `--retry-delay`).

## Automated deployment with Ansible

The `ansible/` directory targets a fresh Raspberry Pi OS Lite installation.

1. Update `ansible/inventory.ini` with the Pi’s IP address.
2. Adjust `ansible/group_vars/sicp_tablets.yml` to describe your five tablets and MQTT
   broker credentials.
3. Set `sicp_repo_url` in `ansible/playbook.yml` to wherever this repository is hosted
   (Git, HTTPS, etc.).
4. Run the playbook:

   ```bash
   cd ansible
   ansible-playbook -i inventory.ini playbook.yml
   ```

The playbook will:

- Install Python, Git, and system dependencies
- Check out the controller source under `/opt/sicp-controller`
- Create a Python virtual environment and install the package
- Render `/etc/sicp/config.yaml` from your tablet list
- Register a `sicp.service` systemd unit and start it automatically on boot

Subsequent updates are as easy as pushing a new commit to your repo and re-running the
playbook.

## Troubleshooting & observability

- **Web UI** – `/logs` surfaces the last 2,000 log lines. Tablet rows show the most recent
  sync time and any error messages.
- **Systemd** – `journalctl -u sicp.service` provides long-form logs if you prefer SSH.
- **MQTT** – watch `sicp/#` topics to verify discovery and state traffic.
- **Retries** – network hiccups trigger retries with exponential delays defined in the
  config; failures are logged and surfaced in both the UI and MQTT attributes.

## Roadmap ideas

- Add Prometheus metrics export
- Optional HTTPS/TLS for the web UI
- Inventory-driven tablet naming from an external CMDB

Contributions and issue reports are welcome!
