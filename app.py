import os
import docker
import sys
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash
from dotenv import load_dotenv

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

    return render_template('dashboard.html', containers=containers,
                           running_count=running_count, stopped_count=stopped_count,
                           docker_error=docker_error, docker_available=docker_available)

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

    # ── Deploy ──────────────────────────────
    try:
        run_kwargs = {
            'image': image,
            'ports': {f'80/tcp': port_int},
            'detach': True
        }
        if name:
            run_kwargs['name'] = name

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