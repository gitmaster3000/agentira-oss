import React from 'react';

// Cartoon avatar presets: bg colour, skin colour, eyes, mouth. A profile with
// no picture gets one picked deterministically from its name, so the same
// person always looks the same everywhere.
const BGS = ['#c9b8ff', '#9be7d8', '#ffd08a', '#ffa8b8', '#a8d4ff', '#c6f0a4', '#f6b3ff', '#ffc9a0'];
const SKINS = ['#ffe0bd', '#f6c9a0', '#e0a878', '#b9814f', '#8a5a3a', '#fff0c8'];

const EYES = [
    (c) => <><circle cx="21" cy="26" r="3" fill={c} /><circle cx="43" cy="26" r="3" fill={c} /></>,
    (c) => <><path d="M17 27 q4 -6 8 0" stroke={c} strokeWidth="2.6" fill="none" strokeLinecap="round" /><path d="M39 27 q4 -6 8 0" stroke={c} strokeWidth="2.6" fill="none" strokeLinecap="round" /></>,
    (c) => <><circle cx="21" cy="26" r="4.5" fill="#fff" /><circle cx="22" cy="27" r="2.4" fill={c} /><circle cx="43" cy="26" r="4.5" fill="#fff" /><circle cx="44" cy="27" r="2.4" fill={c} /></>,
    (c) => <><rect x="17" y="25" width="8" height="2.6" rx="1.3" fill={c} /><rect x="39" y="25" width="8" height="2.6" rx="1.3" fill={c} /></>,
];
const MOUTHS = [
    (c) => <path d="M22 40 q10 10 20 0" stroke={c} strokeWidth="2.8" fill="none" strokeLinecap="round" />,
    (c) => <path d="M24 42 q8 5 16 0" stroke={c} strokeWidth="2.8" fill="none" strokeLinecap="round" />,
    (c) => <ellipse cx="32" cy="42" rx="4.5" ry="3.5" fill={c} />,
    (c) => <path d="M22 39 q10 12 20 0 z" fill={c} />,
];

function preset(key) {
    const n = Number(key);
    return {
        bg: BGS[n % BGS.length],
        skin: SKINS[(n >> 3) % SKINS.length],
        eyes: EYES[(n >> 1) % EYES.length],
        mouth: MOUTHS[(n >> 2) % MOUTHS.length],
    };
}

export const PRESET_COUNT = 24;
export const presetValue = (i) => `preset:${i}`;

function hash(str) {
    let h = 0;
    for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0;
    return h;
}

export function CartoonFace({ index, size }) {
    const { bg, skin, eyes, mouth } = preset(index);
    return (
        <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" style={{ display: 'block' }}>
            <rect width="64" height="64" fill={bg} />
            <circle cx="32" cy="34" r="22" fill={skin} />
            {eyes('#2b2140')}
            {mouth('#2b2140')}
            <circle cx="14" cy="36" r="3.5" fill="#ff8fa3" opacity=".45" />
            <circle cx="50" cy="36" r="3.5" fill="#ff8fa3" opacity=".45" />
        </svg>
    );
}

// Renders a profile's picture: uploaded image, chosen preset, or a default
// cartoon derived from the name. `profile` needs avatar_url + name/display_name.
export function UserAvatar({ profile, name, avatarUrl, size = 28, radius = '50%', title }) {
    const label = name || profile?.display_name || profile?.name || '?';
    const url = avatarUrl ?? profile?.avatar_url ?? '';
    const isPreset = url.startsWith('preset:');
    const isImage = !isPreset && /^(https?:|data:image\/)/.test(url);
    const index = isPreset ? Number(url.slice(7)) || 0 : hash(profile?.name || label) % PRESET_COUNT;
    return (
        <span
            data-testid="user-avatar"
            title={title}
            style={{ width: size, height: size, borderRadius: radius, flexShrink: 0, overflow: 'hidden', display: 'inline-block', lineHeight: 0 }}
        >
            {isImage
                ? <img src={url} alt={label} style={{ width: size, height: size, objectFit: 'cover', display: 'block' }} />
                : <CartoonFace index={index} size={size} />}
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
