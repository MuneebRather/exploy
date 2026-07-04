# Exploy 🚀

A self-built deployment platform that automates container delivery — from code push to running application.

## Overview

Exploy is a custom DevOps deployment platform designed to automate the lifecycle of containerized application delivery.

It connects a CI pipeline to a deployment system, detecting new Docker images on Docker Hub and automatically updating running containers by pulling the latest version, stopping the old container, and starting a new one.

This removes the need for manual deployment steps after every build and simulates a real-world CI/CD workflow in a simplified, controlled environment.

The project is built in progressive levels, where each stage introduces a new component of a production-style deployment pipeline, eventually forming a complete end-to-end automation system.

In simple terms: Exploy works like a deployment agent that watches for new Docker image versions and automatically updates the running application whenever a new build is available.

## Tech Stack

**Current**
- Python + Flask — core platform backend
- Docker — container runtime and management
- GitHub Actions — CI pipeline for automated builds
- Docker Hub — image registry

**Planned**
- Terraform — infrastructure provisioning
- Kubernetes + Minikube — container orchestration
- LocalStack — local AWS services simulation

## Architecture

```
Developer pushes code to GitHub
            │
            ▼
GitHub Actions builds Docker image
            │
            ▼
Image pushed to Docker Hub
            │
            ▼
Exploy detects new image version
            │
            ▼
Exploy pulls latest image
            │
            ▼
Old container stopped → New container started
            │
            ▼
Updated application is live
```

## Roadmap

### Level 1 — Core Platform (Completed)✅
- Project setup and authentication
- Docker daemon integration
- Deploy containers via dashboard
- View, stop and restart containers
- Basic deployment logs

### Level 2 — CI Integration (Completed)✅
- GitHub repository integration
- Detect code pushes automatically
- Trigger Docker image builds via GitHub Actions

### Level 3 — CD Automation (In Progress)
- Monitor Docker Hub for new image versions
- Auto pull and deploy on image update
- Deployment history and logs

### Level 4 — Advanced Deployment Strategies (Planned)
- Rolling updates
- Blue-green deployments
- Health checks
- Automatic rollback on failure

### Level 5 — Infrastructure Automation (Planned)
- Terraform-based infrastructure provisioning
- Automated environment setup

### Level 6 — Kubernetes Integration (Planned)
- Kubernetes deployment manifests
- Auto-scaling support
- Declarative container management

## Progress

### Level 1 — Core Platform ✅
- [x] Project setup
- [x] Authentication system
- [x] Docker daemon integration
- [x] Container deployment via UI
- [x] Container management and logs

Level 1 establishes a functional container management dashboard built with Flask and the Docker SDK. Containers are displayed in a card-based interface with real-time status indicators and support full lifecycle operations, including deploy, start, stop, restart, and remove. A dedicated logs viewer enables inspection of container output. The application verifies Docker daemon connectivity during startup and handles daemon unavailability gracefully. All management routes are protected using a login_required decorator, and a settings page provides platform information along with Docker Engine status.

### Level 2 — CI Integration ✅

- [x] GitHub repository integration
- [x] Detect code pushes automatically
- [x] Trigger Docker image builds via GitHub Actions

Linked containers to their corresponding GitHub repositories
using Docker labels and implemented a webhook endpoint to receive GitHub push events. Added an Activity page to display deployment history, including repository, branch, commit hash, author, and event status. Configured a GitHub Actions workflow to automatically build and push Docker images to Docker Hub whenever code is pushed to the main branch. Images are tagged with the Git commit SHA to ensure version traceability and reproducible deployments.

### Level 3 — CD Automation (In Progress)

- [x] Monitor Docker Hub for new image versions
- [ ] Connect Exploy to Docker Hub for image pulling
- [ ] Auto pull and deploy new images
- [ ] Webhook notification from GitHub Actions to Exploy
- [ ] Deployment history and logs

## Design Approach

Exploy is built to simulate a real-world deployment workflow in a modular and progressive way. Each level introduces a new component of the pipeline, from manual container management to fully automated CI/CD with infrastructure provisioning.

The focus is on understanding how deployment systems work internally rather than relying on existing tools like Jenkins or ArgoCD.

## Author

Muneeb Rather