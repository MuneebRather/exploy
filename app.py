import os
import docker
import sys
import urllib.request
import json
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash
from dotenv import load_dotenv

# In-memory event store for push events
push_events = []

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')
if not app.secret_key:
    raise ValueError("No SECRET_KEY set. Please create a .env file with SECRET_KEY=your-key")

# ── Docker client (with fallback if daemon is down) ─────────────────
client = None
docker_available = False

try:
    client = docker.from_env()
    client.ping()  # quick health check
    docker_available = True
except Exception:
    docker_available = False

# ── Docker Hub helper ───────────────────────
def get_docker_hub_tags(repo, count=5):
    """Fetch latest image tags from Docker Hub API for a given repo."""
    if not repo:
        return []
    try:
        url = f'https://hub.docker.com/v2/repositories/{repo}/tags?page_size={count}'
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            tags = []
            for result in data.get('results', []):
                tags.append({
                    'name': result['name'],
                    'updated': result['last_updated'][:10] if result['last_updated'] else 'unknown',
                    'size': result.get('full_size', 0)
                })
            return tags
    except Exception:
        return []

# ── Auth decorator ────────────────────────────
def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return view_func(*args, **kwargs)
    return wrapped

# ── Routes ────────────────────────────────────
@app.route('/')
def root():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        expected_user = os.environ.get('EXPLOY_USER')
        expected_pass = os.environ.get('EXPLOY_PASS')
        if not expected_user or not expected_pass:
            raise ValueError("EXPLOY_USER and EXPLOY_PASS must be set in .env file")
        if username == expected_user and password == expected_pass:
            session['logged_in'] = True
            session['username'] = username
            flash('Welcome back, admin.', 'success')
            return redirect(url_for('dashboard'))
        error = 'Invalid username or password.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been signed out.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    containers = []
    running_count = 0
    stopped_count = 0
    docker_error = None

    if docker_available and client:
        try:
            containers = client.containers.list(all=True)
            running_count = sum(1 for c in containers if c.status == 'running')
            stopped_count = len(containers) - running_count
        except Exception as e:
            docker_error = str(e)
    else:
        docker_error = 'Docker daemon is not running or not accessible.'

    # Fetch Docker Hub tags for each unique linked repo
    docker_hub_tags = {}
    if docker_available:
        seen_repos = set()
        for c in containers:
            repo = c.labels.get('exploy.repo')
            if repo and repo not in seen_repos:
                seen_repos.add(repo)
                docker_repo = repo.replace('github.com/', '').replace('https://github.com/', '')
                docker_hub_tags[repo] = get_docker_hub_tags(docker_repo)

    # Get current running image tags for each linked repo
    current_tags = {}
    if docker_available:
        for c in containers:
            repo = c.labels.get('exploy.repo')
            if repo:
                current_image = c.image.tags[0] if c.image.tags else ''
                current_tag = current_image.split(':')[-1] if ':' in current_image else ''
                current_tags[repo] = current_tag

    # Check for new deploys since last visit
    show_deploy_notice = False
    deploy_events = [e for e in push_events if e.get('type') == 'deploy']
    if deploy_events:
        latest_deploy = deploy_events[-1]
        latest_deploy_time = latest_deploy['timestamp']
        last_seen = session.get('last_seen_deploy')

        if last_seen != latest_deploy_time:
            show_deploy_notice = True
            session['last_seen_deploy'] = latest_deploy_time

    return render_template('dashboard.html', containers=containers,
                           running_count=running_count, stopped_count=stopped_count,
                           docker_error=docker_error, docker_available=docker_available,
                           docker_hub_tags=docker_hub_tags, events=push_events,
                           show_deploy_notice=show_deploy_notice,
                           current_tags=current_tags)

@app.route('/deploy', methods=['POST'])
@login_required
def deploy():
    if not docker_available:
        flash('Docker daemon is not running. Cannot deploy.', 'error')
        return redirect(url_for('dashboard'))

    image = request.form.get('image', '').strip()
    name = request.form.get('name', '').strip()
    port = request.form.get('port', '').strip()
    repo = request.form.get('repo', '').strip()

    # ── Validation ──────────────────────────
    if not image:
        flash('Docker image is required.', 'error')
        return redirect(url_for('dashboard'))

    if not port:
        flash('Host port is required.', 'error')
        return redirect(url_for('dashboard'))

    try:
        port_int = int(port)
        if not (1 <= port_int <= 65535):
            raise ValueError
    except ValueError:
        flash('Port must be a number between 1 and 65535.', 'error')
        return redirect(url_for('dashboard'))

    # Check for port conflicts with running containers
    try:
        for c in client.containers.list():
            if c.ports:
                for port_bindings in c.ports.values():
                    if port_bindings:
                        for binding in port_bindings:
                            if binding.get('HostPort') == str(port_int):
                                flash(f'Port {port_int} is already in use by container "{c.name}".', 'error')
                                return redirect(url_for('dashboard'))
    except Exception:
        pass

    # ── Pull image if not local ─────────────
    try:
        client.images.get(image)
    except docker.errors.ImageNotFound:
        try:
            client.images.pull(image)
            flash(f'Pulled {image} from Docker Hub and deployed.', 'success')
        except Exception as e:
            flash(f'Failed to pull {image}: {str(e)}', 'error')
            return redirect(url_for('dashboard'))

    # ── Deploy ──────────────────────────────
    try:
        run_kwargs = {
            'image': image,
            'ports': {'80/tcp': port_int},
            'detach': True
        }
        if name:
            run_kwargs['name'] = name
        if repo:
            run_kwargs['labels'] = {'exploy.repo': repo}

        container = client.containers.run(**run_kwargs)
        msg = f'Container "{container.name}" deployed successfully on port {port_int}.'
        if repo:
            msg += f' Linked to {repo}.'
        flash(msg, 'success')
    except docker.errors.ImageNotFound:
        flash(f'Image "{image}" not found. Pull it first or check the name.', 'error')
    except docker.errors.APIError as e:
        if 'port is already allocated' in str(e).lower():
            flash(f'Port {port_int} is already allocated on the host.', 'error')
        elif 'conflict' in str(e).lower() and 'container name' in str(e).lower():
            flash(f'Container name "{name}" is already in use.', 'error')
        else:
            flash(f'Docker API error: {str(e)}', 'error')
    except Exception as e:
        flash(f'Deployment failed: {str(e)}', 'error')

    return redirect(url_for('dashboard'))

@app.route('/stop/<container_id>')
@login_required
def stop(container_id):
    if not docker_available:
        flash('Docker daemon is not running.', 'error')
        return redirect(url_for('dashboard'))
    try:
        container = client.containers.get(container_id)
        container.stop()
        flash(f'Container "{container.name}" stopped.', 'info')
    except docker.errors.NotFound:
        flash('Container not found.', 'error')
    except Exception as e:
        flash(f'Error stopping container: {str(e)}', 'error')
    return redirect(url_for('dashboard'))

@app.route('/restart/<container_id>')
@login_required
def restart(container_id):
    if not docker_available:
        flash('Docker daemon is not running.', 'error')
        return redirect(url_for('dashboard'))
    try:
        container = client.containers.get(container_id)
        container.restart()
        flash(f'Container "{container.name}" restarted.', 'success')
    except docker.errors.NotFound:
        flash('Container not found.', 'error')
    except Exception as e:
        flash(f'Error restarting container: {str(e)}', 'error')
    return redirect(url_for('dashboard'))

@app.route('/remove/<container_id>')
@login_required
def remove(container_id):
    if not docker_available:
        flash('Docker daemon is not running.', 'error')
        return redirect(url_for('dashboard'))
    try:
        container = client.containers.get(container_id)
        name = container.name
        container.remove(force=True)
        flash(f'Container "{name}" removed.', 'info')
    except docker.errors.NotFound:
        flash('Container not found.', 'error')
    except Exception as e:
        flash(f'Error removing container: {str(e)}', 'error')
    return redirect(url_for('dashboard'))

@app.route('/logs/<container_id>')
@login_required
def logs(container_id):
    if not docker_available:
        return render_template('logs.html', logs='Error: Docker daemon is not running.',
                               container_id=container_id)
    try:
        container = client.containers.get(container_id)
        logs_data = container.logs(tail=200).decode('utf-8')
    except docker.errors.NotFound:
        logs_data = "Error: Container not found."
    except Exception as e:
        logs_data = f"Error: {str(e)}"
    return render_template('logs.html', logs=logs_data,
                           container_id=container_id)

@app.route('/logs/<container_id>/raw')
@login_required
def logs_raw(container_id):
    if not docker_available:
        return 'Error: Docker daemon is not running.', 503

    try:
        container = client.containers.get(container_id)
        logs_data = container.logs(tail=200).decode('utf-8', errors='replace')
    except docker.errors.NotFound:
        return 'Error: Container not found.', 404
    except Exception as e:
        return f'Error: {str(e)}', 500

    from flask import Response
    return Response(logs_data, mimetype='text/plain')

@app.route('/webhook/github', methods=['POST'])
def github_webhook():
    """Receive GitHub push events (simulated via curl for local testing)"""
    data = request.get_json() or {}

    event = {
        'type': 'push',
        'repo': data.get('repository', {}).get('full_name', 'unknown/repo'),
        'branch': data.get('ref', 'unknown').replace('refs/heads/', ''),
        'commit': data.get('after', 'unknown')[:7],
        'author': data.get('pusher', {}).get('name', 'unknown'),
        'timestamp': __import__('datetime').datetime.now().isoformat()
    }

    push_events.append(event)
    # Keep only last 50 events
    if len(push_events) > 50:
        push_events.pop(0)

    return {'status': 'ok', 'event': event}, 200

@app.route('/webhook/deploy', methods=['POST'])
def deploy_webhook():
    """Receive deploy trigger from GitHub Actions"""
    data = request.get_json() or {}

    repo = data.get('repo', '')
    tag = data.get('tag', '')

    if not repo or not tag:
        return {'status': 'error', 'message': 'Missing repo or tag'}, 400

    if not docker_available or not client:
        return {'status': 'error', 'message': 'Docker not available'}, 503

    deployed = []
    try:
        for c in client.containers.list(all=True):
            container_repo = c.labels.get('exploy.repo', '')
            if container_repo and repo in container_repo:
                docker_repo = repo.replace('github.com/', '').replace('https://github.com/', '')
                new_image = f'{docker_repo}:{tag}'

                old_ports = c.attrs.get('HostConfig', {}).get('PortBindings', {})
                ports = {}
                for container_port, host_bindings in old_ports.items():
                    if host_bindings:
                        host_port = host_bindings[0].get('HostPort')
                        ports[container_port] = int(host_port)

                c.stop()
                c.remove(force=True)

                try:
                    client.images.get(new_image)
                except docker.errors.ImageNotFound:
                    client.images.pull(new_image)

                run_kwargs = {
                    'image': new_image,
                    'ports': ports,
                    'name': c.name,
                    'detach': True,
                    'labels': {'exploy.repo': container_repo}
                }

                client.containers.run(**run_kwargs)
                deployed.append(c.name)
    except Exception as e:
        return {'status': 'error', 'message': str(e)}, 500

    # Log deploy events to activity
    for name in deployed:
        push_events.append({
            'type': 'deploy',
            'repo': repo,
            'tag': tag,
            'container': name,
            'timestamp': __import__('datetime').datetime.now().isoformat()
        })
        if len(push_events) > 50:
            push_events.pop(0)

    return {'status': 'ok', 'deployed': deployed}, 200

@app.route('/activity')
@login_required
def activity():
    return render_template('activity.html', events=push_events)

@app.route('/settings')
@login_required
def settings():
    docker_version = None
    container_count = 0

    if docker_available and client:
        try:
            docker_version = client.version().get('Version', 'Unknown')
            container_count = len(client.containers.list(all=True))
        except Exception:
            pass

    return render_template('settings.html',
                           docker_available=docker_available,
                           docker_version=docker_version,
                           container_count=container_count,
                           python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                           flask_version=__import__('flask').__version__)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)