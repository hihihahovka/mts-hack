#!/bin/bash
# Revert Dockerfile.openwebui to remove the COPY open-webui/build instruction totally
sed -i.bak '/COPY open-webui\/build \/app\/build/d' Dockerfile.openwebui
docker compose down
docker compose up -d --build
