// Palette for the Deploy tab, ported straight from design/deploy/Deploy.dc.html.
// Same approach as the Workflow Engine port: the design is dark-only and its
// semantic colours (live/building/failed) are deliberately outside the app's
// accent token set, so they live here rather than in index.css.
export const C = {
    bg: '#0e1117',
    panel: '#14161b',
    surface: '#161b22',
    raised: '#1c2128',
    void: '#0a0c10',
    border: '#30363d',
    borderSoft: '#22272e',
    borderStrong: '#3d444d',

    text: '#f0f3f6',
    textSoft: '#e8ebf0',
    textMuted: '#b1bac4',
    textDim: '#768390',
    textFaint: '#5a626c',

    info: '#38bdf8',
    infoText: '#7dd3fc',
    infoInk: '#04222f',
    good: '#2ecc71',
    goodText: '#9fd8b6',
    bad: '#f85149',
    badText: '#e0928d',
    warn: '#ff9800',
    teal: '#80cbc4',
};

export const MONO = "ui-monospace,'SF Mono','JetBrains Mono',Menlo,monospace";

// Injected once by the Deploy page; the pills and the preview frame rely on it.
export const DEPLOY_KEYFRAMES = `
@keyframes dpLivePulse{0%{transform:scale(1);opacity:.55}70%{transform:scale(2.6);opacity:0}100%{opacity:0}}
@keyframes dpSoftBlink{0%,100%{opacity:1}50%{opacity:.35}}
.dp-lp::after{content:"";position:absolute;inset:0;border-radius:50%;background:currentColor;animation:dpLivePulse 1.8s ease-out infinite}
.dp-blink{animation:dpSoftBlink 1.2s ease-in-out infinite}
.dp-stripe{background-image:repeating-linear-gradient(135deg,rgba(255,255,255,.022) 0 12px,transparent 12px 24px)}
`;

// Everything a status needs to render: pill colour, dot colour, label.
// `none` is not a backend status — it's the UI's stand-in for a branch that has
// never had a deployment.
export const STATUS = {
    queued: { label: 'Queued', color: C.textDim, tint: 'rgba(118,131,144,.12)', border: C.border },
    building: { label: 'Building', color: C.info, tint: 'rgba(56,189,248,.12)', border: 'rgba(56,189,248,.38)' },
    live: { label: 'Live', color: C.good, tint: 'rgba(46,204,113,.12)', border: 'rgba(46,204,113,.38)' },
    failed: { label: 'Failed', color: C.bad, tint: 'rgba(248,81,73,.12)', border: 'rgba(248,81,73,.38)' },
    crashed: { label: 'Crashed', color: C.bad, tint: 'rgba(248,81,73,.12)', border: 'rgba(248,81,73,.38)' },
    stopped: { label: 'Stopped', color: C.textDim, tint: 'transparent', border: C.textFaint, dashed: true },
    none: { label: 'No preview', color: C.textDim, tint: 'transparent', border: C.border, dashed: true },
};

export const IN_FLIGHT = new Set(['queued', 'building']);

export function statusOf(deployment) {
    return deployment?.status && STATUS[deployment.status] ? deployment.status : 'none';
}

// "2 min ago" from an ISO timestamp. Returns '' when there's nothing to show.
export function timeAgo(iso) {
    if (!iso) return '';
    const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    if (Number.isNaN(secs)) return '';
    if (secs < 45) return 'just now';
    const mins = Math.floor(secs / 60);
    if (mins < 60) return `${mins} min ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
}
