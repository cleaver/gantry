# Reverse Proxy and SSL/TLS Certificates

Gantry uses Caddy as a reverse proxy to route traffic to your projects and `mkcert` to provide trusted, locally-signed TLS certificates. This enables you to access your projects via `https://<project-name>.test` with a valid SSL certificate in your browser.

## How it Works

1.  **DNS Resolution**: Gantry configures your system (via `dnsmasq`) to resolve all `*.test` domains to `127.0.0.1`.
2.  **Certificate Generation**: `mkcert` is used to create a local Certificate Authority (CA) and generate a wildcard certificate for `*.test`. This CA is installed in your system's and browser's trust stores.
3.  **Reverse Proxy**: Caddy runs as a background service, listening on ports 80 and 443. It uses the generated certificate to terminate TLS.
4.  **Routing**: When you access `https://myapp.test`, Caddy receives the request and proxies it to the correct local port for your project (e.g., `localhost:5001`), as defined in the Gantry registry.

## Caddy and mkcert Setup

The easiest way to get started is to run the all-in-one setup command. This only needs to be done once per machine.

```bash
gantry setup all
```

This command will:
1.  Download and install the correct binaries for `caddy` and `mkcert` into `~/.gantry/bin/`.
2.  Run `mkcert -install` to create a local CA and install it in your system and browser trust stores. You may be prompted for your password.
3.  Configure `dnsmasq` for `.test` domains. This may also require `sudo` privileges.

### Manual Setup

If you prefer to manage the components yourself, you can run the steps individually:

1.  **Install Caddy**:
    ```bash
    gantry setup caddy
    ```

2.  **Install mkcert**:
    ```bash
    gantry setup mkcert
    ```

3.  **Setup the Certificate Authority**:
    ```bash
    gantry cert setup-ca
    ```

4.  **Setup DNS**:
    ```bash
    gantry dns-setup
    ```

## Self-Signed Certificate Explanation

When you first run `gantry cert setup-ca` (or `gantry setup all`), `mkcert` creates a new, unique Certificate Authority (CA) on your local machine. It then installs the root certificate of this CA into your operating system's and browsers' trust stores.

This means that any certificate generated and signed by this local CA will be trusted by your machine, just like a "real" certificate from a public CA (like Let's Encrypt).

**Why is this useful?**

-   **No More SSL Warnings**: You can develop against `https://` URLs without browser warnings about untrusted certificates.
-   **Realistic Development**: Your local environment more closely matches production, which uses HTTPS.
-   **Security**: The private key for your local CA never leaves your machine, so it's secure.

When Gantry registers a project, it ensures a wildcard certificate for `*.test` exists, which Caddy then uses for all your projects. This certificate is what secures the connection between your browser and the Caddy reverse proxy.
