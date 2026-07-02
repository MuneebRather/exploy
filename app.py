import docker
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = 'exploy-secret-key-2026'

# Connect to Docker daemon
client = docker.from_env()

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
        if username == 'admin' and password == 'admin123':
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('dashboard'))
        error = 'Invalid username or password.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    containers = client.containers.list(all=True)
    return render_template('dashboard.html', containers=containers)

@app.route('/deploy', methods=['POST'])
@login_required
def deploy():
    image = request.form.get('image')
    name = request.form.get('name')
    port = request.form.get('port')
    try:
        client.containers.run(
            image,
            name=name,
            ports={f'80/tcp': int(port)},
            detach=True
        )
    except Exception as e:
        return f"Error: {str(e)}"
    return redirect(url_for('dashboard'))

@app.route('/stop/<container_id>')
@login_required
def stop(container_id):
    try:
        container = client.containers.get(container_id)
        container.stop()
    except Exception as e:
        return f"Error: {str(e)}"
    return redirect(url_for('dashboard'))

@app.route('/restart/<container_id>')
@login_required
def restart(container_id):
    try:
        container = client.containers.get(container_id)
        container.restart()
    except Exception as e:
        return f"Error: {str(e)}"
    return redirect(url_for('dashboard'))

@app.route('/remove/<container_id>')
@login_required
def remove(container_id):
    try:
        container = client.containers.get(container_id)
        container.remove(force=True)
    except Exception as e:
        return f"Error: {str(e)}"
    return redirect(url_for('dashboard'))

@app.route('/logs/<container_id>')
@login_required
def logs(container_id):
    try:
        container = client.containers.get(container_id)
        logs = container.logs(tail=50).decode('utf-8')
    except Exception as e:
        logs = f"Error: {str(e)}"
    return render_template('logs.html', logs=logs,
                           container_id=container_id)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)