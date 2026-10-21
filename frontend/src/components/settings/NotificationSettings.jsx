import React, { useEffect, useState } from 'react';
import { api } from '../../api';

const EVENTS = [
    ['task.created', 'New task'],
    ['bug.created', 'New bug'],
    ['epic.created', 'New epic'],
];
const CHANNELS = [
    ['in_app', 'In the app'],
    ['email', 'Email'],
    ['push', 'Phone / browser'],
];

const b64ToBytes = (s) => {
    const raw = atob((s + '='.repeat((4 - (s.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/'));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
};

const pushSupported = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;

export function NotificationSettings() {
    const [prefs, setPrefs] = useState(null);
    const [error, setError] = useState('');
    const [deviceOn, setDeviceOn] = useState(false);

    useEffect(() => {
        api.getNotificationPrefs().then(setPrefs).catch((e) => setError(e.message));
        if (pushSupported()) {
            navigator.serviceWorker.getRegistration('/sw.js')
                .then((r) => r && r.pushManager.getSubscription())
                .then((s) => setDeviceOn(!!s))
                .catch(() => {});
        }
    }, []);

    const toggle = async (ev, ch) => {
        const next = !prefs[ev][ch];
        setPrefs({ ...prefs, [ev]: { ...prefs[ev], [ch]: next } });
        try {
            setPrefs(await api.setNotificationPrefs({ [ev]: { [ch]: next } }));
            setError('');
        } catch (e) {
            setPrefs(prefs);
            setError(e.message);
        }
    };

    const enableDevice = async () => {
        try {
            const { key } = await api.getPushPublicKey();
            if (!key) { setError('Phone notifications are not set up on this server yet.'); return; }
            if ((await Notification.requestPermission()) !== 'granted') {
                setError('Notifications are blocked for this site in your browser settings.');
                return;
            }
            const reg = await navigator.serviceWorker.register('/sw.js');
            const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(key) });
            await api.pushSubscribe(sub.toJSON());
            setDeviceOn(true);
            setError('');
        } catch (e) {
            setError(e.message || 'Could not turn on notifications for this device.');
        }
    };

    const disableDevice = async () => {
        try {
            const reg = await navigator.serviceWorker.getRegistration('/sw.js');
            const sub = reg && (await reg.pushManager.getSubscription());
            if (sub) {
                await api.pushUnsubscribe(sub.endpoint);
                await sub.unsubscribe();
            }
            setDeviceOn(false);
        } catch (e) {
            setError(e.message);
        }
    };

    const cell = { padding: '10px 12px', textAlign: 'center', fontSize: 12.5, color: 'var(--text-primary)' };

    return (
        <div style={{ maxWidth: 580 }}>
            <h2 style={{ fontSize: 17, fontWeight: 600, margin: '0 0 4px', color: 'var(--text-primary)' }}>Notifications</h2>
            <p style={{ fontSize: 12.5, color: 'var(--text-muted)', margin: '0 0 20px' }}>
                Choose what you hear about when someone on your projects adds something new, and where.
            </p>
            {error && <div style={{ color: '#f87171', fontSize: 12.5, marginBottom: 12 }}>{error}</div>}
            {prefs && (
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                        <tr>
                            <th />
                            {CHANNELS.map(([k, label]) => (
                                <th key={k} style={{ ...cell, fontWeight: 600, color: 'var(--text-muted)' }}>{label}</th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {EVENTS.map(([ev, label]) => (
                            <tr key={ev} style={{ borderTop: '1px solid var(--border-default)' }}>
                                <td style={{ ...cell, textAlign: 'left' }}>{label}</td>
                                {CHANNELS.map(([ch, chLabel]) => (
                                    <td key={ch} style={cell}>
                                        <input type="checkbox" aria-label={`${label} — ${chLabel}`}
                                            checked={!!prefs[ev][ch]} onChange={() => toggle(ev, ch)} />
                                    </td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
            <div style={{ marginTop: 24, fontSize: 12.5, color: 'var(--text-muted)' }}>
                <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>This device</div>
                {!pushSupported() ? (
                    <p style={{ margin: 0 }}>This browser can't receive phone notifications. On iPhone, add Agentira to your Home Screen first.</p>
                ) : deviceOn ? (
                    <p style={{ margin: 0 }}>Notifications are on for this device. <button onClick={disableDevice} style={{ color: '#8ab4f8', background: 'none', border: 'none', cursor: 'pointer' }}>Turn off</button></p>
                ) : (
                    <p style={{ margin: 0 }}>Get alerts on this phone or browser, even when Agentira is closed. <button onClick={enableDevice} style={{ color: '#8ab4f8', background: 'none', border: 'none', cursor: 'pointer' }}>Turn on</button></p>
                )}
            </div>
        </div>
    );
}
