FROM mcr.microsoft.com/devcontainers/base:ubuntu24.04

USER vscode
WORKDIR /home/vscode

RUN curl -fsSL https://claude.ai/install.sh | bash

ENV PATH=/home/vscode/.local/bin:$PATH