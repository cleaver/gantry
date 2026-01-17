# Gantry DNS Setup (.test TLD)

Gantry simplifies local development by automatically resolving `.test` domains (e.g., `my-project.test`) to your local machine (`127.0.0.1`). This allows you to access your projects in the browser using memorable, browser-friendly names instead of `localhost:PORT`.

## How it Works: The `.test` TLD

The `.test` top-level domain (TLD) is a special-use domain name reserved by the IETF (in RFC 2606 and RFC 6761) for testing purposes. It is guaranteed never to be installed into the global Domain Name System (DNS), making it safe for local development without the risk of conflicting with real-world domains.

Gantry leverages this by configuring a local DNS resolver to direct all traffic for any domain ending in `.test` to your local machine.

## One-Time DNS Setup

To enable this functionality, Gantry needs to configure a local DNS resolver. Gantry uses `dnsmasq`, a lightweight and widely available DNS server.

You only need to run this setup command once per machine.

```bash
gantry dns-setup
```

**What this command does:**

1.  **Checks for `dnsmasq`**: It first checks if `dnsmasq` is installed on your system.
2.  **Installs `dnsmasq`**: If `dnsmasq` is not found, it will prompt you to install it using your system's package manager (e.g., `apt`, `dnf`, `pacman`). This step requires `sudo` privileges.
3.  **Creates a configuration file**: It creates a configuration file at `/etc/dnsmasq.d/gantry.conf`. This file contains a single rule:
    ```
    address=/.test/127.0.0.1
    ```
    This rule tells `dnsmasq` to resolve any query for a `.test` domain to `127.0.0.1`.
4.  **Restarts `dnsmasq`**: It restarts the `dnsmasq` service to apply the new configuration. This also requires `sudo` privileges.
5.  **Verifies System DNS**: It ensures that your system is configured to use the local `dnsmasq` resolver. On most modern Linux systems that use `systemd-resolved`, this is handled automatically. Gantry will also attempt to configure `/etc/resolv.conf` if needed.

After the setup is complete, any project you register with Gantry (e.g., `gantry register --hostname my-project`) will be immediately accessible at `http://my-project.test` and `https://my-project.test` (once Caddy is configured in Phase 4).

## Troubleshooting DNS Issues

If you are having trouble resolving `.test` domains after running `gantry dns-setup`, here are some common issues and how to resolve them.

### 1. Verify with `gantry dns-test`

The first step is to use Gantry's built-in test command:

```bash
gantry dns-test my-project
```

This command performs a DNS lookup for `my-project.test` and tells you if it resolves correctly.

### 2. Check if dnsmasq is running

Verify that the `dnsmasq` service is active:

```bash
systemctl status dnsmasq
```

If it's not running, try starting it:

```bash
sudo systemctl start dnsmasq
```

### 3. Check your system's resolver configuration

Your system must be configured to use `127.0.0.1` as a DNS server. Check the contents of `/etc/resolv.conf`:

```bash
cat /etc/resolv.conf
```

You should see a line like this, typically at the top:

```
nameserver 127.0.0.1
```

If you don't, it means your system is not querying the local `dnsmasq` instance. This can happen if another network management tool (like NetworkManager) is overwriting `/etc/resolv.conf`.

**Solution for NetworkManager:**

If you are using NetworkManager, you can configure it to use `dnsmasq`.
1. Edit `/etc/NetworkManager/NetworkManager.conf`.
2. Add `dns=dnsmasq` to the `[main]` section.
3. Restart NetworkManager: `sudo systemctl restart NetworkManager`.

**Solution for `systemd-resolved`:**

If your system uses `systemd-resolved`, ensure it's configured to forward `.test` queries. Gantry attempts to do this, but you can verify by checking for a file like `/etc/systemd/resolved.conf.d/gantry.conf` with the following content:

```
[Resolve]
DNS=127.0.0.1
Domains=~test
```

### 4. Firewall Issues

Ensure your firewall is not blocking DNS queries on port 53 for localhost.

- For `ufw`: `sudo ufw allow 53/udp`
- For `firewalld`: `sudo firewall-cmd --add-service=dns --permanent && sudo firewall-cmd --reload`

### 5. Check `gantry.conf` for `dnsmasq`

Ensure the configuration file exists and has the correct content:

```bash
cat /etc/dnsmasq.d/gantry.conf
```

It should contain: `address=/.test/127.0.0.1`

If the file is missing or incorrect, you can re-run `gantry dns-setup`.
