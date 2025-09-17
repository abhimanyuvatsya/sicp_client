# SICP Tablet Service

This project provides a resilient management service for Philips commercial Android tablets that expose the SICP protocol. It includes:

* An asynchronous controller that handles LED color changes and panel power state with retry and verification logic.
* An MQTT bridge with Home Assistant auto-discovery support so each tablet appears as a light (LED strip) and switch (power control).
* A FastAPI-based web UI for manual testing, reviewing recent logs, and inspecting current tablet status.
* An Ansible role and playbook to deploy the service onto a Raspberry Pi (or other Debian-based host) with systemd supervision.

The system was designed for up to five tablets on a local network (e.g., `192.168.2.x`) but can scale to more with appropriate hardware resources.

## Repository layout

```
├── sicp_service/           # Python package containing the service implementation
│   ├── config.py           # YAML configuration loader and models
│   ├── logging_utils.py   # In-memory log buffer for the web UI
│   ├── main.py            # Entry point used by systemd / CLI
│   ├── manager.py         # Tablet orchestration and polling logic
│   ├── mqtt.py            # MQTT bridge and Home Assistant discovery
│   ├── sicp.py            # Low-level SICP protocol helpers
│   └── web.py             # FastAPI application for UI and REST API
├── ansible/               # Deployment playbook and role
├── config.example.yaml    # Sample configuration for five tablets
├── requirements.txt       # Python dependencies installed on the target host
└── README.md              # This document
```

## Runtime requirements

* Python 3.9 or newer
* Network connectivity from the service host to each Philips tablet (default TCP port `5000`)
* Access to an MQTT broker (tested against the Home Assistant Mosquitto add-on)
* Optional: TLS CA certificate if the MQTT broker requires TLS

## Configuration

All runtime settings are provided via a YAML file. Copy `config.example.yaml` to `/etc/sicp_service/config.yaml` (or pass a custom path using `--config`). Update the following sections:

* `mqtt`: Connection information for the broker acting as the bridge between Home Assistant and the tablets. Credentials can be left blank if anonymous access is allowed.
* `home_assistant`: Enable/disable auto-discovery and adjust the discovery prefix if your Home Assistant instance uses a non-default value.
* `polling`: Control how frequently the tablets are polled, socket timeouts, and retry behaviour.
* `web`: Bind address and port for the local web UI.
* `log_directory`: Directory where the rotating service log should be written.
* `tablets`: List of tablets to manage. Each entry must provide a unique `id`, the tablet IP in `host`, and optionally a friendly `name` and `port` (defaults to `5000`).

Example excerpt:

```yaml
mqtt:
  host: 192.168.2.2
  port: 1883
  username: ha_bridge
  password: "super-secret"
  base_topic: sicp_tablets
home_assistant:
  enabled: true
  discovery_prefix: homeassistant
polling:
  interval_seconds: 20
  timeout_seconds: 3
  retry_attempts: 3
  retry_delay_seconds: 1
web:
  host: 0.0.0.0
  port: 8080
log_directory: /var/log/sicp_service
tablets:
  - id: lobby
    name: Lobby Panel
    host: 192.168.2.21
  - id: conference
    name: Conference Room
    host: 192.168.2.22
```

## Running locally

Install dependencies and start the service from the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m sicp_service.main --config ./config.example.yaml
```

The service starts an HTTP server (default `http://localhost:8080/`) exposing:

* `/` — dashboard for manual LED/power control per tablet.
* `/logs` — rolling buffer of recent logs, useful for debugging.
* `/api/tablets` — JSON API for current tablet state.

MQTT topics follow the pattern `<base_topic>/<tablet_id>/...` with retained messages for availability and state. Home Assistant discovery publishes to `homeassistant/light/<tablet_id>/config` and `homeassistant/switch/<tablet_id>/config` so the tablets appear automatically.

## Ansible deployment

The repository ships with an Ansible role that provisions the service on a Raspberry Pi running Raspberry Pi OS Lite (or any Debian-based distribution). The role performs the following steps:

1. Installs Python tooling (`python3`, `python3-venv`, `python3-pip`) and `git`.
2. Creates a dedicated `sicp` user/group and required directories under `/opt/sicp_service`, `/etc/sicp_service`, and `/var/log/sicp_service`.
3. Copies the project sources (or optionally clones a Git repository) onto the host.
4. Creates a Python virtual environment and installs the dependencies from `requirements.txt`.
5. Renders `config.yaml` using variables defined in your inventory/group vars.
6. Installs and enables a `systemd` unit that keeps the service running and restarts it on failure.

### Inventory example

```ini
[tablets]
raspberrypi ansible_host=192.168.2.50 ansible_user=pi
```

### Variable example (`group_vars/tablets.yml`)

```yaml
sicp_service_mqtt:
  host: 192.168.2.2
  port: 1883
  username: mqtt_user
  password: mqtt_pass
sicp_service_tablets:
  - id: lobby
    name: Lobby Panel
    host: 192.168.2.21
  - id: conference
    name: Conference Panel
    host: 192.168.2.22
  - id: kitchen
    name: Kitchen Display
    host: 192.168.2.23
```

### Running the playbook

Execute the provided playbook from the repository root:

```bash
ansible-playbook -i inventory ansible/playbook.yml
```

Set `sicp_service_repo_url` if you would rather deploy from a Git server instead of copying the local working tree. Additional environment variables (for example MQTT credentials) can be injected via `sicp_service_environment`.

After deployment, verify the service:

```bash
sudo systemctl status sicp_service.service
sudo journalctl -u sicp_service.service -f
```

The service logs also appear in `/var/log/sicp_service/sicp_service.log` and in the web UI.

## Reliability considerations

* All SICP commands use configurable retry logic with exponential backoff to tolerate transient network issues.
* LED color and power changes are confirmed by issuing follow-up status requests; mismatches are logged and surfaced via MQTT/Home Assistant.
* Periodic polling keeps MQTT and the web dashboard in sync with the actual tablet state even if it changes outside of Home Assistant.
* The MQTT manager republishes retained availability and state payloads after reconnecting to guarantee Home Assistant always has current data.
* Detailed logs (captured in memory and optionally on disk) simplify debugging in case a tablet becomes unreachable.

## Developing

The code base targets Python 3.9+ and does not rely on platform-specific extensions, making it suitable for Raspberry Pi 3B hardware. When adding new features, prefer asyncio-friendly libraries and avoid blocking operations outside of `asyncio.to_thread()` wrappers.
