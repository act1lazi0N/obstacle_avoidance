let aiEnabled = true;

async function pollState() {
    try {
        const res = await fetch('/api/state');
        const data = await res.json();
        updateUI(data);
    } catch (e) {
        console.error('Poll error:', e);
    }
}

function updateUI(data) {
    // Connection dots
    document.getElementById('piDot').className =
        'dot' + (data.system.pi_connected ? ' online' : '');
    document.getElementById('aiDot').className =
        'dot' + (data.system.ai_connected ? ' online' : '');

    // FSM Badge
    const badge = document.getElementById('fsmBadge');
    const state = data.fsm.state;
    badge.textContent = state.toUpperCase().replace('_', ' ');
    badge.className = 'fsm-badge ' + state;

    // Danger meter
    const danger = data.brain.danger_level;
    const fill = document.getElementById('dangerFill');
    const pct = Math.round(danger * 100);
    fill.style.width = pct + '%';
    document.getElementById('dangerLabel').textContent = pct + '%';
    
    // Set dynamic glow and color based on danger level
    if (danger < 0.2) {
        fill.style.backgroundColor = 'var(--green)';
        fill.style.boxShadow = '0 0 10px var(--green)';
    } else if (danger < 0.5) {
        fill.style.backgroundColor = 'var(--yellow)';
        fill.style.boxShadow = '0 0 10px var(--yellow)';
    } else if (danger < 0.8) {
        fill.style.backgroundColor = 'var(--orange)';
        fill.style.boxShadow = '0 0 10px var(--orange)';
    } else {
        fill.style.backgroundColor = 'var(--red)';
        fill.style.boxShadow = '0 0 10px var(--red)';
    }

    // Stats
    document.getElementById('ultrasonicVal').textContent =
        data.brain.ultrasonic_cm < 999 ?
        data.brain.ultrasonic_cm.toFixed(1).padStart(5, '0') : '—';
    document.getElementById('obstacleCount').textContent =
        String(data.brain.camera_obstacles || 0).padStart(3, '0');
    document.getElementById('speedVal').textContent = String(data.fsm.speed || 0).padStart(3, '0');
    
    const steer = data.fsm.steer || 0.0;
    const sign = steer < 0 ? '-' : (steer > 0 ? '+' : ' ');
    document.getElementById('steerVal').textContent = sign + Math.abs(steer).toFixed(1).padStart(3, '0');

    // Motor command
    const cmd = data.brain.motor_command;
    if (cmd && cmd.action) {
        document.getElementById('motorCmd').textContent =
            `${cmd.action} | spd=${cmd.speed || 0} | str=${(cmd.steer || 0).toFixed(2)}`;
    }

    // Research State Details
    const setBadge = (id, text, colorClass) => {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = String(text).toUpperCase();
            el.className = 'state-badge ' + colorClass;
        }
    };

    const cameraStatus = data.sensors?.camera_status || data.brain.camera_status || 'unknown';
    const cameraColor = (cameraStatus === 'ok' || cameraStatus === 'synthetic' || cameraStatus === 'webcam') ? 'green' : 'yellow';
    setBadge('cameraStatus', cameraStatus, cameraColor);

    const behavior = data.decision?.selected_behavior || data.brain.selected_behavior || 'waiting';
    setBadge('selectedBehavior', behavior, behavior === 'waiting' ? 'yellow' : 'blue');

    const reason = data.decision?.reason || data.brain.decision_reason || 'waiting';
    setBadge('decisionReason', reason, 'blue');

    const estop = Boolean(data.safety?.emergency_stop) || data.fsm.state === 'emergency_stop';
    setBadge('estopStatus', estop ? 'ACTIVE' : 'CLEAR', estop ? 'red' : 'green');

    const mqttAge = data.system.latest_mqtt_age_s;
    const ageText = mqttAge === null || mqttAge === undefined ? '—' : `${mqttAge.toFixed(2)}s`;
    const ageColor = (mqttAge !== null && mqttAge > 2.0) ? 'red' : 'green';
    setBadge('mqttAge', ageText, ageColor);

    const event = data.event || {};
    const eventText = event.type && event.message ? `${event.type}: ${event.message}` : 'NONE';
    setBadge('latestEvent', eventText, event.type === 'error' ? 'red' : 'green');
}

async function emergencyStop() {
    await fetch('/api/estop', { method: 'POST' });
}

async function resetEstop() {
    await fetch('/api/reset', { method: 'POST' });
}

async function toggleAI() {
    aiEnabled = !aiEnabled;
    await fetch('/api/ai/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: aiEnabled }),
    });
    const btn = document.getElementById('btnAI');
    btn.textContent = aiEnabled ? 'AI ON' : 'AI OFF';
    btn.className = 'btn btn-ai' + (aiEnabled ? '' : ' off');
}

// Start polling at 500ms intervals
setInterval(pollState, 500);
pollState();

function updateTime() {
    const now = new Date();
    const el = document.getElementById('sysTimestamp');
    if (el) {
        el.textContent = now.toLocaleTimeString('en-US', { hour12: false });
    }
}
setInterval(updateTime, 1000);
updateTime();
