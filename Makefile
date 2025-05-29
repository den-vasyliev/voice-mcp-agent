# Makefile for LiveKit Agent with MCP Tools
#
# To install Node.js/npx (required for running sample MCP servers):
#   make nodejs-macos   # for macOS (Homebrew)

.PHONY: help run test install uv venv certs-macos certs-linux nodejs-macos run-mcp-server

help:
	@echo "Available targets:"
	@echo "  uv           - Install uv (Python package manager) for macOS/Linux"
	@echo "  venv         - Create a Python virtual environment in ./venv"
	@echo "  install      - Install Python dependencies using uv (in venv if activated)"
	@echo "  run          - Run the LiveKit agent (requires OPENAI_API_KEY and ELEVENLABS_API_KEY env vars)"
	@echo "  test         - Run all tests with pytest (requires env vars if needed)"
	@echo "  certs-macos  - Fix SSL certificate issues on macOS (run Install Certificates.command)"
	@echo "  certs-linux  - Fix SSL certificate issues on Linux (install ca-certificates)"
	@echo "  nodejs-macos  - Install Node.js/npx for macOS (Homebrew)"
	@echo "  run-mcp-server - Run a sample MCP server (requires npx)"

uv:
	@echo "Installing uv..."
	@curl -Ls https://astral.sh/uv/install.sh | sh

venv:
	uv venv .venv

install:
	uv pip install -r requirements.txt

# Troubleshooting: SSL certificate errors (CERTIFICATE_VERIFY_FAILED)
certs-macos:
	@echo "Running Install Certificates.command for your Python version..."
	@/Applications/Python\ $$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')/Install\ Certificates.command || echo "Please adjust the path for your Python version."

certs-linux:
	sudo apt-get update && sudo apt-get install -y ca-certificates

run: venv install
	uv run main.py console

test:
	@# SSL certificate check for macOS
	@if [ "$(shell uname)" = "Darwin" ]; then \
	  CERT_CMD="/Applications/Python $$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')/Install Certificates.command"; \
	  if [ ! -f "$$CERT_CMD" ]; then \
	    echo "[WARNING] Install Certificates.command not found. If you get SSL errors, run 'make certs-macos' and check your Python version."; \
	  fi; \
	fi
	@# SSL certificate check for Linux
	@if [ "$(shell uname)" = "Linux" ]; then \
	  if ! dpkg -s ca-certificates >/dev/null 2>&1; then \
	    echo "[WARNING] ca-certificates not installed. If you get SSL errors, run 'make certs-linux'."; \
	  fi; \
	fi
	pytest 

nodejs-macos:
	brew install node

# Sample MCP server run (requires npx):
run-mcp-server:
	ALLOW_ONLY_NON_DESTRUCTIVE_TOOLS=true ENABLE_UNSAFE_SSE_TRANSPORT=1 PORT=8092 npx mcp-server-kubernetes 