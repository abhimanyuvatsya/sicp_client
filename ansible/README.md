# Ansible deployment

This playbook provisions a Raspberry Pi (tested on Raspberry Pi OS Lite) with the SICP control service, MQTT bridge, and web UI.

## Usage

1. Copy `inventory.example` to `inventory` and adjust the host/IP and SSH username.
2. Create a variable file (for example `group_vars/sicp_tablets.yml`) that defines the tablets and MQTT credentials:

```yaml
sicp_repo_url: "https://github.com/your-org/sicp_client.git"
sicp_repo_version: "main"

sicp_tablets:
  - name: "Lobby Tablet"
    host: "192.168.2.91"
  - name: "Reception Tablet"
    host: "192.168.2.92"
  - name: "Conference Room"
    host: "192.168.2.93"
  - name: "Showroom"
    host: "192.168.2.94"
  - name: "Warehouse"
    host: "192.168.2.95"

sicp_mqtt:
  host: "mqtt.local"
  port: 1883
  username: "homeassistant"
  password: "SUPER_SECRET"  # Use ansible-vault for production

sicp_web:
  bind_host: "0.0.0.0"
  bind_port: 8080
```

3. Run the playbook:

```bash
ansible-playbook -i inventory ansible/deploy.yml
```

The playbook creates a dedicated system user, installs the Python virtual environment, pushes the configuration, and registers a `sicp.service` systemd unit that starts automatically on boot.

If you prefer to deploy the local working tree without using Git, leave `sicp_repo_url` empty. The role will copy the checked out sources from the controller to the target host.
