import React from 'react';

// Cartoon character avatars. A profile with no picture gets one picked
// deterministically from its name, so the same person always looks the same.
const BGS = ['#d9ccff', '#b8efe3', '#ffe0a8', '#ffc4d0', '#bfdcff', '#d3f2b8', '#f3c9ff', '#ffd6b8'];
const INK = '#2b2140';

const Eye = ({ x, y, r = 3.2 }) => (
    <>
        <circle cx={x} cy={y} r={r} fill={INK} />
        <circle cx={x + r * 0.35} cy={y - r * 0.35} r={r * 0.36} fill="#fff" />
    </>
);
const Eyes = ({ y = 33, gap = 11, r }) => <><Eye x={32 - gap} y={y} r={r} /><Eye x={32 + gap} y={y} r={r} /></>;
const Cheeks = ({ y = 41, gap = 15 }) => (
    <>
        <circle cx={32 - gap} cy={y} r="3" fill="#ff8fa3" opacity=".5" />
        <circle cx={32 + gap} cy={y} r="3" fill="#ff8fa3" opacity=".5" />
    </>
);
const Smile = ({ y = 43, w = 5 }) => (
    <path d={`M${32 - w} ${y} q${w} ${w * 0.9} ${w * 2} 0`} stroke={INK} strokeWidth="2" fill="none" strokeLinecap="round" />
);

const CHARACTERS = [
    // cat
    () => <>
        <polygon points="13,30 15,8 30,19" fill="#f2994a" /><polygon points="51,30 49,8 34,19" fill="#f2994a" />
        <polygon points="17,26 18,14 26,20" fill="#ffc2b0" /><polygon points="47,26 46,14 38,20" fill="#ffc2b0" />
        <ellipse cx="32" cy="38" rx="21" ry="19" fill="#f2994a" />
        <path d="M32 19 v8 M26 20 l1 6 M38 20 l-1 6" stroke="#c9732a" strokeWidth="2" strokeLinecap="round" />
        <ellipse cx="32" cy="45" rx="9" ry="6.5" fill="#ffe9cf" />
        <Eyes y={36} gap={10} /><polygon points="29.5,41 34.5,41 32,44" fill="#ff7a93" /><Smile y={45.5} w={3.5} />
        <path d="M6 40 h10 M7 46 l9 -3 M58 40 h-10 M57 46 l-9 -3" stroke="#fff" strokeWidth="1.4" strokeLinecap="round" opacity=".9" />
    </>,
    // dog
    () => <>
        <ellipse cx="13" cy="33" rx="7" ry="14" fill="#8a5a33" transform="rotate(14 13 33)" />
        <ellipse cx="51" cy="33" rx="7" ry="14" fill="#8a5a33" transform="rotate(-14 51 33)" />
        <ellipse cx="32" cy="37" rx="19" ry="20" fill="#d9a066" />
        <path d="M32 17 q-6 6 -2 14 q4 -2 4 -14z" fill="#8a5a33" />
        <ellipse cx="32" cy="46" rx="11" ry="8.5" fill="#fbe8cc" />
        <Eyes y={34} gap={10} /><ellipse cx="32" cy="42" rx="4.2" ry="3" fill={INK} />
        <path d="M32 45 v3 M27 48 q5 4 10 0" stroke={INK} strokeWidth="1.8" fill="none" strokeLinecap="round" />
        <path d="M30 49 q2 6 4 0z" fill="#ff7a93" />
    </>,
    // bear
    () => <>
        <circle cx="14" cy="17" r="8" fill="#7a4e2d" /><circle cx="50" cy="17" r="8" fill="#7a4e2d" />
        <circle cx="14" cy="17" r="4" fill="#d9a77a" /><circle cx="50" cy="17" r="4" fill="#d9a77a" />
        <ellipse cx="32" cy="37" rx="21" ry="20" fill="#8f5e38" />
        <ellipse cx="32" cy="44" rx="10" ry="8" fill="#ecd2ab" />
        <Eyes y={34} gap={11} r={3} /><ellipse cx="32" cy="41" rx="4" ry="3" fill={INK} />
        <path d="M32 44 v2.5 M27.5 47 q4.5 3.5 9 0" stroke={INK} strokeWidth="1.8" fill="none" strokeLinecap="round" />
    </>,
    // panda
    () => <>
        <circle cx="14" cy="17" r="8" fill="#2b2140" /><circle cx="50" cy="17" r="8" fill="#2b2140" />
        <ellipse cx="32" cy="37" rx="21" ry="20" fill="#fff" />
        <ellipse cx="21.5" cy="34" rx="6" ry="7.5" fill="#2b2140" transform="rotate(-18 21.5 34)" />
        <ellipse cx="42.5" cy="34" rx="6" ry="7.5" fill="#2b2140" transform="rotate(18 42.5 34)" />
        <circle cx="22" cy="34" r="2.6" fill="#fff" /><circle cx="42" cy="34" r="2.6" fill="#fff" />
        <circle cx="22.4" cy="33.6" r="1.2" fill={INK} /><circle cx="41.6" cy="33.6" r="1.2" fill={INK} />
        <ellipse cx="32" cy="44" rx="3.6" ry="2.6" fill={INK} /><Smile y={47} w={4} />
    </>,
    // rabbit
    () => <>
        <ellipse cx="22" cy="14" rx="6" ry="14" fill="#fff" transform="rotate(-8 22 14)" />
        <ellipse cx="42" cy="14" rx="6" ry="14" fill="#fff" transform="rotate(8 42 14)" />
        <ellipse cx="22" cy="15" rx="2.8" ry="9.5" fill="#ffb3c4" transform="rotate(-8 22 15)" />
        <ellipse cx="42" cy="15" rx="2.8" ry="9.5" fill="#ffb3c4" transform="rotate(8 42 15)" />
        <ellipse cx="32" cy="40" rx="20" ry="18" fill="#fff" />
        <Eyes y={38} gap={10} /><Cheeks y={44} gap={14} />
        <polygon points="29.5,42.5 34.5,42.5 32,45.5" fill="#ff7a93" />
        <path d="M32 45.5 v2 M27 48 q5 3 10 0" stroke={INK} strokeWidth="1.6" fill="none" strokeLinecap="round" />
        <rect x="30" y="48" width="4" height="4" rx="1" fill="#fff" stroke={INK} strokeWidth="1" />
    </>,
    // fox
    () => <>
        <polygon points="11,28 14,6 30,19" fill="#e8662a" /><polygon points="53,28 50,6 34,19" fill="#e8662a" />
        <polygon points="16,24 16,13 25,19" fill="#2b2140" /><polygon points="48,24 48,13 39,19" fill="#2b2140" />
        <path d="M11 32 Q32 8 53 32 Q50 58 32 58 Q14 58 11 32z" fill="#e8662a" />
        <path d="M11 36 Q22 40 32 52 Q42 40 53 36 Q50 58 32 58 Q14 58 11 36z" fill="#fff" />
        <Eyes y={35} gap={10} /><ellipse cx="32" cy="50" rx="3.4" ry="2.6" fill={INK} />
    </>,
    // owl
    () => <>
        <polygon points="12,24 10,8 26,16" fill="#7a5a3c" /><polygon points="52,24 54,8 38,16" fill="#7a5a3c" />
        <ellipse cx="32" cy="37" rx="22" ry="21" fill="#9b7653" />
        <circle cx="22" cy="34" r="10" fill="#f6ead2" /><circle cx="42" cy="34" r="10" fill="#f6ead2" />
        <circle cx="22" cy="34" r="5" fill="#fff" stroke="#e0b25a" strokeWidth="2" /><circle cx="42" cy="34" r="5" fill="#fff" stroke="#e0b25a" strokeWidth="2" />
        <circle cx="22.5" cy="34.5" r="2.6" fill={INK} /><circle cx="41.5" cy="34.5" r="2.6" fill={INK} />
        <polygon points="29,41 35,41 32,48" fill="#f5a623" />
        <path d="M24 53 q3 3 6 0 M34 53 q3 3 6 0" stroke="#7a5a3c" strokeWidth="1.8" fill="none" strokeLinecap="round" />
    </>,
    // robot
    () => <>
        <line x1="32" y1="6" x2="32" y2="15" stroke="#7a8699" strokeWidth="2.4" strokeLinecap="round" /><circle cx="32" cy="6" r="3.4" fill="#ff6b81" />
        <rect x="8" y="30" width="5" height="12" rx="2.5" fill="#7a8699" /><rect x="51" y="30" width="5" height="12" rx="2.5" fill="#7a8699" />
        <rect x="12" y="15" width="40" height="38" rx="11" fill="#cdd6e3" />
        <rect x="17" y="24" width="30" height="14" rx="7" fill="#2b2140" />
        <circle cx="25" cy="31" r="3.6" fill="#5ef2e0" /><circle cx="39" cy="31" r="3.6" fill="#5ef2e0" />
        <circle cx="26" cy="30" r="1.1" fill="#fff" /><circle cx="40" cy="30" r="1.1" fill="#fff" />
        <rect x="23" y="43" width="18" height="5" rx="2.5" fill="#7a8699" />
        <path d="M27 43 v5 M32 43 v5 M37 43 v5" stroke="#cdd6e3" strokeWidth="1.2" />
    </>,
    // penguin
    () => <>
        <ellipse cx="32" cy="37" rx="21" ry="21" fill="#33425e" />
        <path d="M32 24 Q14 26 14 41 Q16 56 32 56 Q48 56 50 41 Q50 26 32 24z" fill="#fff" />
        <Eyes y={35} gap={8.5} r={2.9} />
        <path d="M26 41 Q32 38 38 41 Q36 48 32 48 Q28 48 26 41z" fill="#ffa940" />
        <Cheeks y={42} gap={14} />
    </>,
    // frog
    () => <>
        <circle cx="19" cy="20" r="9" fill="#5fbf4a" /><circle cx="45" cy="20" r="9" fill="#5fbf4a" />
        <ellipse cx="32" cy="40" rx="23" ry="18" fill="#6fd058" />
        <circle cx="19" cy="20" r="6" fill="#fff" /><circle cx="45" cy="20" r="6" fill="#fff" />
        <circle cx="19.8" cy="20.6" r="3" fill={INK} /><circle cx="44.2" cy="20.6" r="3" fill={INK} />
        <circle cx="20.8" cy="19.6" r="1" fill="#fff" /><circle cx="45.2" cy="19.6" r="1" fill="#fff" />
        <circle cx="29" cy="37" r="1.1" fill="#3d8a2e" /><circle cx="35" cy="37" r="1.1" fill="#3d8a2e" />
        <path d="M17 43 Q32 55 47 43" stroke={INK} strokeWidth="2.2" fill="none" strokeLinecap="round" />
        <Cheeks y={45} gap={17} />
    </>,
    // lion
    () => <>
        <circle cx="32" cy="35" r="26" fill="#b9692b" />
        <circle cx="12" cy="21" r="6" fill="#f0b968" /><circle cx="52" cy="21" r="6" fill="#f0b968" />
        <circle cx="32" cy="37" r="17.5" fill="#f4c37a" />
        <ellipse cx="32" cy="44" rx="9" ry="7" fill="#fdebc6" />
        <Eyes y={34} gap={8.5} r={3} /><polygon points="29,40 35,40 32,44" fill="#7a3d1a" />
        <path d="M32 44 v2.5 M27 47 q5 3.5 10 0" stroke={INK} strokeWidth="1.7" fill="none" strokeLinecap="round" />
    </>,
    // monkey
    () => <>
        <circle cx="10" cy="35" r="7" fill="#8a5a33" /><circle cx="54" cy="35" r="7" fill="#8a5a33" />
        <circle cx="10" cy="35" r="3.6" fill="#f1c9a0" /><circle cx="54" cy="35" r="3.6" fill="#f1c9a0" />
        <ellipse cx="32" cy="34" rx="20" ry="20" fill="#8a5a33" />
        <path d="M32 24 q-9 -4 -13 4 q-5 8 1 16 q5 8 12 8 q7 0 12 -8 q6 -8 1 -16 q-4 -8 -13 -4z" fill="#f1c9a0" />
        <Eyes y={34} gap={7.5} r={3} />
        <circle cx="29.5" cy="43" r="1" fill="#8a5a33" /><circle cx="34.5" cy="43" r="1" fill="#8a5a33" />
        <path d="M25 47 q7 6 14 0" stroke={INK} strokeWidth="2" fill="none" strokeLinecap="round" />
    </>,
];

export const PRESET_COUNT = CHARACTERS.length * 2;
export const presetValue = (i) => `preset:${i}`;

// Robot avatars for bots and agents: 8 designs x 2 colour variants.
const ROBOT_COLORS = [
    { body: '#cdd6e3', dark: '#7a8699', glow: '#5ef2e0' },
    { body: '#ffd9b0', dark: '#c0703a', glow: '#ff6b81' },
];
const Visor = ({ c, y = 24, h = 14 }) => <rect x="17" y={y} width="30" height={h} rx={h / 2} fill={INK} />;
const Glow = ({ c, y = 31, gap = 7, r = 3.6 }) => (
    <>
        <circle cx={32 - gap} cy={y} r={r} fill={c.glow} /><circle cx={32 + gap} cy={y} r={r} fill={c.glow} />
        <circle cx={32 - gap + 1} cy={y - 1} r={r * 0.3} fill="#fff" /><circle cx={32 + gap + 1} cy={y - 1} r={r * 0.3} fill="#fff" />
    </>
);
const Grille = ({ c, y = 43 }) => (
    <>
        <rect x="23" y={y} width="18" height="5" rx="2.5" fill={c.dark} />
        <path d={`M27 ${y} v5 M32 ${y} v5 M37 ${y} v5`} stroke={c.body} strokeWidth="1.2" />
    </>
);
const ROBOTS = [
    // classic: antenna + visor
    (c) => <>
        <line x1="32" y1="6" x2="32" y2="15" stroke={c.dark} strokeWidth="2.4" strokeLinecap="round" /><circle cx="32" cy="6" r="3.4" fill={c.glow} />
        <rect x="8" y="30" width="5" height="12" rx="2.5" fill={c.dark} /><rect x="51" y="30" width="5" height="12" rx="2.5" fill={c.dark} />
        <rect x="12" y="15" width="40" height="38" rx="11" fill={c.body} />
        <Visor c={c} /><Glow c={c} /><Grille c={c} />
    </>,
    // boxy: square head, round eyes, smile
    (c) => <>
        <rect x="14" y="10" width="36" height="6" rx="3" fill={c.dark} />
        <rect x="12" y="16" width="40" height="38" rx="4" fill={c.body} />
        <circle cx="23" cy="30" r="6" fill="#fff" /><circle cx="41" cy="30" r="6" fill="#fff" />
        <circle cx="23" cy="30" r="3" fill={INK} /><circle cx="41" cy="30" r="3" fill={INK} />
        <path d="M24 44 q8 7 16 0" stroke={INK} strokeWidth="2.4" fill="none" strokeLinecap="round" />
        <circle cx="16" cy="48" r="1.6" fill={c.dark} /><circle cx="48" cy="48" r="1.6" fill={c.dark} />
    </>,
    // cyclops: one big eye
    (c) => <>
        <line x1="22" y1="8" x2="22" y2="16" stroke={c.dark} strokeWidth="2.4" strokeLinecap="round" /><circle cx="22" cy="7" r="3" fill={c.glow} />
        <line x1="42" y1="8" x2="42" y2="16" stroke={c.dark} strokeWidth="2.4" strokeLinecap="round" /><circle cx="42" cy="7" r="3" fill={c.glow} />
        <rect x="10" y="16" width="44" height="38" rx="16" fill={c.body} />
        <circle cx="32" cy="32" r="11" fill="#fff" stroke={c.dark} strokeWidth="2.4" />
        <circle cx="32" cy="32" r="6" fill={c.glow} /><circle cx="32" cy="32" r="3" fill={INK} /><circle cx="34" cy="30" r="1.2" fill="#fff" />
        <path d="M25 47 h14" stroke={c.dark} strokeWidth="2.4" strokeLinecap="round" />
    </>,
    // headphones
    (c) => <>
        <path d="M12 34 Q12 8 32 8 Q52 8 52 34" stroke={c.dark} strokeWidth="3.5" fill="none" strokeLinecap="round" />
        <rect x="7" y="29" width="8" height="16" rx="4" fill={c.dark} /><rect x="49" y="29" width="8" height="16" rx="4" fill={c.dark} />
        <rect x="14" y="16" width="36" height="38" rx="12" fill={c.body} />
        <Visor c={c} y={26} h={12} /><Glow c={c} y={32} gap={7} r={3.2} />
        <path d="M26 46 q6 4 12 0" stroke={INK} strokeWidth="2" fill="none" strokeLinecap="round" />
    </>,
    // round: dome head with ear bolts
    (c) => <>
        <circle cx="32" cy="35" r="22" fill={c.body} />
        <rect x="6" y="30" width="6" height="10" rx="3" fill={c.dark} /><rect x="52" y="30" width="6" height="10" rx="3" fill={c.dark} />
        <circle cx="32" cy="9" r="3" fill={c.glow} /><path d="M32 12 v6" stroke={c.dark} strokeWidth="2.4" strokeLinecap="round" />
        <Eyes y={33} gap={9} /><Cheeks y={42} gap={14} /><Smile y={42} w={4.5} />
    </>,
    // twin antennas, wide screen
    (c) => <>
        <path d="M20 16 L14 6 M44 16 L50 6" stroke={c.dark} strokeWidth="2.4" strokeLinecap="round" />
        <circle cx="14" cy="6" r="2.8" fill={c.glow} /><circle cx="50" cy="6" r="2.8" fill={c.glow} />
        <rect x="9" y="16" width="46" height="36" rx="9" fill={c.body} />
        <rect x="14" y="22" width="36" height="20" rx="6" fill={INK} />
        <path d="M20 32 h5 l3 -5 l4 10 l3 -5 h9" stroke={c.glow} strokeWidth="2.2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        <rect x="26" y="46" width="12" height="3" rx="1.5" fill={c.dark} />
    </>,
    // sleepy: half-closed eyes
    (c) => <>
        <rect x="12" y="14" width="40" height="40" rx="14" fill={c.body} />
        <rect x="8" y="28" width="5" height="12" rx="2.5" fill={c.dark} /><rect x="51" y="28" width="5" height="12" rx="2.5" fill={c.dark} />
        <path d="M17 32 q6 -7 12 0 M35 32 q6 -7 12 0" stroke={INK} strokeWidth="2.6" fill="none" strokeLinecap="round" />
        <circle cx="23" cy="34" r="2.2" fill={c.glow} /><circle cx="41" cy="34" r="2.2" fill={c.glow} />
        <ellipse cx="32" cy="46" rx="4" ry="3" fill={INK} />
        <circle cx="48" cy="12" r="2" fill={c.glow} /><circle cx="53" cy="7" r="1.4" fill={c.glow} />
    </>,
    // mohawk / spiky top
    (c) => <>
        <polygon points="22,18 26,6 30,18" fill={c.glow} /><polygon points="30,18 34,4 38,18" fill={c.glow} /><polygon points="38,18 42,6 46,18" fill={c.glow} />
        <rect x="12" y="17" width="40" height="37" rx="10" fill={c.body} />
        <rect x="17" y="25" width="30" height="10" rx="3" fill={INK} />
        <rect x="21" y="28" width="7" height="4" rx="1.5" fill={c.glow} /><rect x="36" y="28" width="7" height="4" rx="1.5" fill={c.glow} />
        <rect x="20" y="42" width="24" height="7" rx="3" fill={c.dark} />
        <path d="M26 42 v7 M32 42 v7 M38 42 v7" stroke={c.body} strokeWidth="1.4" />
    </>,
];

export const BOT_PRESET_COUNT = ROBOTS.length * ROBOT_COLORS.length;
export const botPresetValue = (i) => `bot:${i}`;

function hash(str) {
    let h = 0;
    for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0;
    return h;
}

export function CartoonFace({ index, size }) {
    const n = Math.abs(Number(index)) || 0;
    const Character = CHARACTERS[n % CHARACTERS.length];
    return (
        <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" style={{ display: 'block' }}>
            <rect width="64" height="64" fill={BGS[(n * 5) % BGS.length]} />
            <Character />
        </svg>
    );
}

export function RobotFace({ index, size }) {
    const n = Math.abs(Number(index)) || 0;
    const Robot = ROBOTS[n % ROBOTS.length];
    const colors = ROBOT_COLORS[Math.floor(n / ROBOTS.length) % ROBOT_COLORS.length];
    return (
        <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" data-robot="true" style={{ display: 'block' }}>
            <rect width="64" height="64" fill={BGS[(n * 5) % BGS.length]} />
            <Robot {...colors} />
        </svg>
    );
}

const isBot = (profile) => profile?.account_type === 'agentira_agent' || profile?.account_type === 'external_agent';

// Renders a profile's picture: uploaded image, chosen preset, or a default
// cartoon derived from the name. `profile` needs avatar_url + name/display_name.
export function UserAvatar({ profile, name, avatarUrl, size = 28, radius = '50%', title }) {
    const label = name || profile?.display_name || profile?.name || '?';
    const url = avatarUrl ?? profile?.avatar_url ?? '';
    const isPreset = url.startsWith('preset:');
    const isRobot = url.startsWith('bot:') || (!isPreset && !url && isBot(profile));
    const isImage = !isPreset && !isRobot && /^(https?:|data:image\/)/.test(url);
    const hashed = hash(profile?.name || label);
    const index = isPreset ? Number(url.slice(7)) || 0 : url.startsWith('bot:') ? Number(url.slice(4)) || 0 : hashed % (isRobot ? BOT_PRESET_COUNT : PRESET_COUNT);
    return (
        <span
            data-testid="user-avatar"
            title={title}
            style={{ width: size, height: size, borderRadius: radius, flexShrink: 0, overflow: 'hidden', display: 'inline-block', lineHeight: 0 }}
        >
            {isImage
                ? <img src={url} alt={label} style={{ width: size, height: size, objectFit: 'cover', display: 'block' }} />
                : isRobot ? <RobotFace index={index} size={size} /> : <CartoonFace index={index} size={size} />}
        </span>
    );
}

// Downscale an uploaded picture to a small square JPEG data URL (kept tiny
// because it is stored on the profile itself).
export function resizeImageToDataUrl(file, px = 128) {
    return new Promise((resolve, reject) => {
        if (!file.type.startsWith('image/')) { reject(new Error('Choose an image file.')); return; }
        const img = new Image();
        const src = URL.createObjectURL(file);
        img.onload = () => {
            const side = Math.min(img.width, img.height);
            const canvas = document.createElement('canvas');
            canvas.width = canvas.height = px;
            canvas.getContext('2d').drawImage(img, (img.width - side) / 2, (img.height - side) / 2, side, side, 0, 0, px, px);
            URL.revokeObjectURL(src);
            resolve(canvas.toDataURL('image/jpeg', 0.85));
        };
        img.onerror = () => { URL.revokeObjectURL(src); reject(new Error('Could not read that image.')); };
        img.src = src;
    });
}
