# Using Ubuntu as a standard dev environment target
FROM ubuntu:22.04

# Prevent interactive prompts during apt install
ENV DEBIAN_FRONTEND=noninteractive
# Ensure Python output is sent straight to terminal without buffering
ENV PYTHONUNBUFFERED=1

# Install dependencies needed by Gantry and its tests
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    dnsmasq \
    curl \
    docker.io \
    sudo \
    libnss3-tools \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

# Set up a passwordless sudo for the root/default user
# This allows us to test the sudo-wrapped DNS commands
RUN echo "ALL ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

WORKDIR /app

# Copy the project files
COPY . .

# Install Gantry in editable mode with dev dependencies
RUN pip3 install -e ".[dev]"

# Set the environment variable to trigger integration tests
ENV GANTRY_INTEGRATION_TEST=1

# Default command runs the integration suite with verbose output
# -v: Verbose output (shows test names)
# -s: Don't capture stdout (shows your print statements and logs)
CMD ["pytest", "-v", "-s", "tests/integration"]
