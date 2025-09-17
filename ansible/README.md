# Ansible deployment

This playbook installs the SICP controller on a Raspberry Pi (or any Debian-based
host). It provisions a dedicated service user, checks out the application,
installs dependencies inside a Python virtual environment, and enables a
systemd unit.

## Usage

1. Update `inventory.ini` with the IP address of your Raspberry Pi.
2. Edit `group_vars/all.yml` to point `sicp_repo_url` at your git repository and
   to provide MQTT credentials and the tablets you want to manage.
3. Run the playbook:

   ```bash
   ansible-playbook -i inventory.ini playbook.yml
   ```

The playbook configures the service to read `/etc/sicp/config.yml`. Modify the
values in `group_vars/all.yml` or override them per-host to add new tablets.

When the deployment completes, the service listens on the configured web port
(default `8080`) and connects to the MQTT broker defined in the configuration.
