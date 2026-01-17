# Configuring Service Subdomains

Gantry can automatically detect services defined in your `docker-compose.yml` file and assign them a unique subdomain under your project's `.test` domain.

## How Service Detection Works

When you register a project or run `gantry update`, Gantry scans your `docker-compose.yml` for services that have published ports. For each service, it extracts the service name and the host port.

For example, given this `docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:15
    ports:
      - "5432:5432"

  mailhog:
    image: mailhog/mailhog
    ports:
      - "1025:1025"  # SMTP
      - "8025:8025"  # Web UI
```

Gantry will detect:
- A service named `postgres` on port `5432`.
- A service named `mailhog` on port `1025` (it takes the first port listed).

## Subdomain Routing

Once detected, Gantry and Caddy work together to create subdomain routes:
- The main application (e.g., a web server) is available at `http://<project-name>.test`.
- Each detected service is available at `http://<service-name>.<project-name>.test`.

Using the example above for a project named `myapp`:
- The `postgres` database would be routed to by `db.myapp.test:5432`. Note that you still need a database client to connect to this.
- The `mailhog` web UI would be available at `https://mailhog.myapp.test` (which proxies to `localhost:1025`).

## Example: Adding Adminer for Database Management

Adminer is a popular single-file database management tool. You can easily add it to your project as a service and have Gantry give it a convenient URL.

1.  **Add Adminer to your `docker-compose.yml`**:

    ```yaml
    version: '3.8'

    services:
      app:
        # ... your application service
        ports:
          - "3000:3000"
        depends_on:
          - postgres

      postgres:
        image: postgres:15
        ports:
          - "5432:5432"
        environment:
          POSTGRES_USER: user
          POSTGRES_PASSWORD: password
          POSTGRES_DB: myapp_dev

      adminer:
        image: adminer
        ports:
          - "8080:8080" # Gantry will detect this port
    ```

2.  **Update your project**:
    If the project is already registered, run the `update` command to make Gantry aware of the new service.
    ```bash
    gantry update myapp
    ```
    Gantry will detect the new `adminer` service on port `8080` and regenerate the Caddyfile.

3.  **Access Adminer**:
    You can now access the Adminer web interface at `https://adminer.myapp.test`.

    When you log in through the Adminer interface:
    -   **System**: `PostgreSQL`
    -   **Server**: `postgres` (the service name from `docker-compose.yml`)
    -   **Username**: `user` (from your environment variables)
    -   **Password**: `password`
    -   **Database**: `myapp_dev`

This works because Docker Compose creates a network for your project, and services can reach each other using their service names as hostnames.
