import sharp from 'sharp';
import { mkdirSync } from 'fs';

const W = 1280, H = 720;
const CW = 540, CH = 960;

function fillSolid(w, h, r, g, b, a = 255) {
  const buf = Buffer.alloc(w * h * 4);
  for (let i = 0; i < buf.length; i += 4) {
    buf[i] = r; buf[i+1] = g; buf[i+2] = b; buf[i+3] = a;
  }
  return buf;
}

// ─── HERO VIDEO SCENE ──────────────────────────
async function makeHero() {
  const layers = [];

  // Sky: gradient dark violet at top → purple mid → warm dark at bottom
  const sky = Buffer.alloc(W * H * 4);
  for (let y = 0; y < H; y++) {
    const t = y / H;
    const r = Math.round(25 + t * 80 - Math.max(0, t - 0.5) * 40);
    const g = Math.round(15 + t * 60 - Math.max(0, t - 0.5) * 40);
    const b = Math.round(50 + t * 80 - Math.max(0, t - 0.5) * 60);
    for (let x = 0; x < W; x++) {
      const i = (y * W + x) * 4;
      sky[i] = Math.max(0, Math.min(255, r));
      sky[i+1] = Math.max(0, Math.min(255, g));
      sky[i+2] = Math.max(0, Math.min(255, b));
      sky[i+3] = 255;
    }
  }
  layers.push({ input: sky, raw: { width: W, height: H, channels: 4 } });

  // Bright horizon glow (gold)
  for (let gx = 0; gx < 3; gx++) {
    const gbuf = Buffer.alloc(W * H * 4);
    for (let y = 0; y < H; y++) {
      const dy = y - (H * 0.32 + gx * 8);
      const t = Math.max(0, 1 - Math.abs(dy) / (H * 0.15));
      const a = Math.round(t * t * (80 - gx * 15));
      for (let x = 0; x < W; x++) {
        const i = (y * W + x) * 4;
        gbuf[i] = 255; gbuf[i+1] = 200; gbuf[i+2] = 60; gbuf[i+3] = a;
      }
    }
    layers.push({ input: gbuf, raw: { width: W, height: H, channels: 4 } });
  }

  // Purple aurora glow
  const aur = Buffer.alloc(W * H * 4);
  for (let y = 0; y < H; y++) {
    const dy = y - H * 0.22;
    const t = Math.max(0, 1 - Math.abs(dy) / (H * 0.18));
    const a = Math.round(t * t * 50);
    for (let x = 0; x < W; x++) {
      const i = (y * W + x) * 4;
      aur[i] = 180; aur[i+1] = 80; aur[i+2] = 255; aur[i+3] = a;
    }
  }
  layers.push({ input: aur, raw: { width: W, height: H, channels: 4 } });

  // Stars
  const stars = Buffer.alloc(W * H * 4);
  for (let i = 0; i < 200; i++) {
    const sx = Math.floor(Math.random() * W * 0.9 + W * 0.05);
    const sy = Math.floor(Math.random() * H * 0.4);
    const bright = 160 + Math.floor(Math.random() * 95);
    const sz = Math.random() > 0.92 ? 2 : 1;
    for (let dy = 0; dy < sz; dy++)
      for (let dx = 0; dx < sz; dx++) {
        const px = sx + dx, py = sy + dy;
        if (px < 0 || px >= W || py < 0 || py >= H) continue;
        const i = (py * W + px) * 4;
        stars[i] = bright; stars[i+1] = bright; stars[i+2] = 255; stars[i+3] = 220;
      }
  }
  layers.push({ input: stars, raw: { width: W, height: H, channels: 4 } });

  // Mountain range (dark purple silhouette)
  for (let mi = 0; mi < 2; mi++) {
    const mtn = Buffer.alloc(W * H * 4);
    const peaks = mi === 0
      ? [[0,H],[60,480],[160,420],[260,380],[380,400],[500,350],[630,370],[780,330],[900,360],[1020,340],[1140,370],[W,390]]
      : [[0,H],[90,540],[210,490],[340,510],[460,460],[580,480],[730,440],[880,470],[1000,450],[W,470]];
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        let inside = false;
        for (let i = 0; i < peaks.length - 1; i++) {
          const [x1,y1] = peaks[i], [x2,y2] = peaks[i+1];
          if ((y1 <= y && y2 > y) || (y2 <= y && y1 > y)) {
            if (x < x1 + (y - y1) / (y2 - y1) * (x2 - x1)) inside = !inside;
          }
        }
        if (inside && y > (mi === 0 ? 280 : 420)) {
          const i = (y * W + x) * 4;
          if (mi === 0) {
            const t = Math.min(1, (y - 280) / 250);
            mtn[i] = Math.round(35 + t * 15);
            mtn[i+1] = Math.round(25 + t * 12);
            mtn[i+2] = Math.round(50 + t * 20);
            mtn[i+3] = 230;
          } else {
            mtn[i] = 15; mtn[i+1] = 12; mtn[i+2] = 25; mtn[i+3] = 240;
          }
        }
      }
    }
    layers.push({ input: mtn, raw: { width: W, height: H, channels: 4 } });
  }

  // Large play button with vivid purple glow
  const cx = W / 2, cy = H / 2, r = 48;
  const btn = Buffer.alloc(W * H * 4);
  for (let y = cy - r - 12; y <= cy + r + 12; y++) {
    for (let x = cx - r - 12; x <= cx + r + 12; x++) {
      if (x < 0 || x >= W || y < 0 || y >= H) continue;
      const dist = Math.sqrt((x - cx) ** 2 + (y - cy) ** 2);
      const i = (y * W + x) * 4;
      if (dist > r && dist <= r + 12) {
        const t = (dist - r) / 12;
        btn[i] = 168; btn[i+1] = 85; btn[i+2] = 247; btn[i+3] = Math.round(50 * (1 - t));
      }
      if (dist <= r) {
        const t = dist / r;
        btn[i] = Math.round(168 - t * 80);
        btn[i+1] = Math.round(85 - t * 40);
        btn[i+2] = Math.round(247 - t * 100);
        btn[i+3] = Math.round(220 - t * 80);
      }
    }
  }
  layers.push({ input: btn, raw: { width: W, height: H, channels: 4 } });

  // Play triangle (bright white)
  const tx = cx + 8, ty = cy;
  const tri = Buffer.alloc(W * H * 4);
  const triPts = [[tx-16,ty-22],[tx-16,ty+22],[tx+24,ty]];
  for (let y = Math.max(0, ty-24); y < Math.min(H, ty+24); y++) {
    for (let x = Math.max(0, tx-18); x < Math.min(W, tx+26); x++) {
      let inside = true;
      for (let j = 0; j < 3; j++) {
        const [x1,y1] = triPts[j], [x2,y2] = triPts[(j+1)%3];
        if ((x2-x1)*(y-y1) - (y2-y1)*(x-x1) < 0) { inside = false; break; }
      }
      if (inside) {
        const i = (y * W + x) * 4;
        tri[i] = 255; tri[i+1] = 255; tri[i+2] = 255; tri[i+3] = 240;
      }
    }
  }
  layers.push({ input: tri, raw: { width: W, height: H, channels: 4 } });

  // Vignette
  const vig = Buffer.alloc(W * H * 4);
  for (let y = 0; y < H; y++) {
    const t = Math.max(0, Math.min(1, (y - H * 0.6) / (H * 0.4)));
    const a = Math.round(t * t * 180);
    for (let x = 0; x < W; x++) {
      const i = (y * W + x) * 4;
      vig[i] = 0; vig[i+1] = 0; vig[i+2] = 0; vig[i+3] = a;
    }
  }
  layers.push({ input: vig, raw: { width: W, height: H, channels: 4 } });

  await sharp({ create: { width: W, height: H, channels: 4, background: { r: 0, g: 0, b: 0, alpha: 0 } } })
    .composite(layers.map(l => ({ ...l, top: 0, left: 0 })))
    .webp({ quality: 90 })
    .toFile('assets/hero-video-scene.webp');
  console.log('hero-video-scene.webp created');
}

// ─── CLIP IMAGE — simple but bold ──────────────
async function makeClip(name, cr, cg, cb) {
  const layers = [];

  // Solid background with slight gradient vignette
  const bg = Buffer.alloc(CW * CH * 4);
  for (let y = 0; y < CH; y++) {
    for (let x = 0; x < CW; x++) {
      const dx = (x - CW/2) / (CW/2), dy = (y - CH/2) / (CH/2);
      const vig = 1 - (dx*dx + dy*dy) * 0.15;
      const i = (y * CW + x) * 4;
      bg[i] = Math.min(255, Math.round(cr * (0.3 + vig * 0.7)));
      bg[i+1] = Math.min(255, Math.round(cg * (0.3 + vig * 0.7)));
      bg[i+2] = Math.min(255, Math.round(cb * (0.3 + vig * 0.7)));
      bg[i+3] = 255;
    }
  }
  layers.push({ input: bg, raw: { width: CW, height: CH, channels: 4 } });

  // Darker top/bottom bars (letterbox)
  for (const [yStart, h] of [[0, CH*0.12], [CH*0.88, CH*0.12]]) {
    const bar = Buffer.alloc(CW * CH * 4);
    for (let y = yStart; y < yStart + h; y++) {
      for (let x = 0; x < CW; x++) {
        const i = (y * CW + x) * 4;
        bar[i] = bar[i+1] = bar[i+2] = 0; bar[i+3] = 140;
      }
    }
    layers.push({ input: bar, raw: { width: CW, height: CH, channels: 4 } });
  }

  // Large content circle (like a face/object in frame)
  const circ = Buffer.alloc(CW * CH * 4);
  const ccx = CW * 0.5, ccy = CH * 0.35, crad = 120;
  for (let y = Math.max(0, ccy - crad); y < Math.min(CH, ccy + crad); y++) {
    for (let x = Math.max(0, ccx - crad); x < Math.min(CW, ccx + crad); x++) {
      const dist = Math.sqrt((x - ccx) ** 2 + (y - ccy) ** 2);
      if (dist <= crad) {
        const t = dist / crad;
        const i = (y * CW + x) * 4;
        const bright = Math.round(200 - t * 100);
        circ[i] = Math.min(255, cr + bright);
        circ[i+1] = Math.min(255, cg + bright);
        circ[i+2] = Math.min(255, cb + bright);
        circ[i+3] = Math.round(180 * (1 - t * t));
      }
    }
  }
  layers.push({ input: circ, raw: { width: CW, height: CH, channels: 4 } });

  // Second smaller circle
  const circ2 = Buffer.alloc(CW * CH * 4);
  const ccx2 = CW * 0.35, ccy2 = CH * 0.55, crad2 = 70;
  for (let y = Math.max(0, ccy2 - crad2); y < Math.min(CH, ccy2 + crad2); y++) {
    for (let x = Math.max(0, ccx2 - crad2); x < Math.min(CW, ccx2 + crad2); x++) {
      const dist = Math.sqrt((x - ccx2) ** 2 + (y - ccy2) ** 2);
      if (dist <= crad2) {
        const t = dist / crad2;
        const i = (y * CW + x) * 4;
        circ2[i] = Math.min(255, Math.round(cr * 0.5 + 120 * (1 - t)));
        circ2[i+1] = Math.min(255, Math.round(cg * 0.5 + 120 * (1 - t)));
        circ2[i+2] = Math.min(255, Math.round(cb * 0.5 + 120 * (1 - t)));
        circ2[i+3] = Math.round(130 * (1 - t * t));
      }
    }
  }
  layers.push({ input: circ2, raw: { width: CW, height: CH, channels: 4 } });

  // Text bars (simulated caption/content)
  const textBars = [
    { y: 0.72, w: 0.65, h: 10, a: 100 },
    { y: 0.78, w: 0.45, h: 10, a: 80 },
    { y: 0.84, w: 0.55, h: 10, a: 90 },
  ];
  for (const bar of textBars) {
    const b = Buffer.alloc(CW * CH * 4);
    const bx = Math.round(CW * 0.15), bw = Math.round(CW * bar.w);
    const by = Math.round(CH * bar.y), bh = Math.round(bar.h);
    for (let y = by; y < Math.min(CH, by + bh); y++) {
      for (let x = bx; x < Math.min(CW, bx + bw); x++) {
        const i = (y * CW + x) * 4;
        b[i] = 255; b[i+1] = 255; b[i+2] = 255; b[i+3] = bar.a;
      }
    }
    layers.push({ input: b, raw: { width: CW, height: CH, channels: 4 } });
  }

  // Progress bar at bottom
  const prog = Buffer.alloc(CW * CH * 4);
  const py = CH - 8;
  for (let x = 0; x < CW; x++) {
    const i = (py * CW + x) * 4;
    prog[i] = 255; prog[i+1] = 255; prog[i+2] = 255; prog[i+3] = 15;
  }
  const progFill = Math.round(CW * 0.35);
  for (let x = 0; x < progFill; x++) {
    const i = (py * CW + x) * 4;
    prog[i] = cr; prog[i+1] = cg; prog[i+2] = cb; prog[i+3] = 180;
  }
  layers.push({ input: prog, raw: { width: CW, height: CH, channels: 4 } });

  // Big play button overlay
  const pcy = CH * 0.5, pcx = CW * 0.5, pr = 40;
  const pb = Buffer.alloc(CW * CH * 4);
  for (let y = pcy - pr - 10; y <= pcy + pr + 10; y++) {
    for (let x = pcx - pr - 10; x <= pcx + pr + 10; x++) {
      if (x < 0 || x >= CW || y < 0 || y >= CH) continue;
      const dist = Math.sqrt((x - pcx) ** 2 + (y - pcy) ** 2);
      const i = (y * CW + x) * 4;
      if (dist > pr && dist <= pr + 10) {
        const t = (dist - pr) / 10;
        pb[i] = 255; pb[i+1] = 255; pb[i+2] = 255; pb[i+3] = Math.round(25 * (1 - t));
      }
      if (dist <= pr) {
        const t = dist / pr;
        pb[i] = Math.round(255 - t * 80);
        pb[i+1] = Math.round(255 - t * 80);
        pb[i+2] = Math.round(255 - t * 80);
        pb[i+3] = Math.round(90 - t * 60);
      }
    }
  }
  layers.push({ input: pb, raw: { width: CW, height: CH, channels: 4 } });

  // Play triangle
  const pt = Buffer.alloc(CW * CH * 4);
  const ptx = pcx + 6, pty = pcy;
  const pts = [[ptx-14, pty-18], [ptx-14, pty+18], [ptx+20, pty]];
  for (let y = Math.max(0, pty-20); y < Math.min(CH, pty+20); y++) {
    for (let x = Math.max(0, ptx-16); x < Math.min(CW, ptx+22); x++) {
      let inside = true;
      for (let j = 0; j < 3; j++) {
        const [x1,y1] = pts[j], [x2,y2] = pts[(j+1)%3];
        if ((x2-x1)*(y-y1) - (y2-y1)*(x-x1) < 0) { inside = false; break; }
      }
      if (inside) {
        const i = (y * CW + x) * 4;
        pt[i] = 255; pt[i+1] = 255; pt[i+2] = 255; pt[i+3] = 230;
      }
    }
  }
  layers.push({ input: pt, raw: { width: CW, height: CH, channels: 4 } });

  // Corner vignette
  const vg = Buffer.alloc(CW * CH * 4);
  for (let y = 0; y < CH; y++) {
    for (let x = 0; x < CW; x++) {
      const dx = (x - CW/2) / (CW/2), dy = (y - CH/2) / (CH/2);
      const dist = dx*dx + dy*dy;
      const a = Math.round(Math.max(0, dist - 0.7) * 50);
      if (a > 0) {
        const i = (y * CW + x) * 4;
        vg[i] = 0; vg[i+1] = 0; vg[i+2] = 0; vg[i+3] = Math.min(255, a);
      }
    }
  }
  layers.push({ input: vg, raw: { width: CW, height: CH, channels: 4 } });

  await sharp({ create: { width: CW, height: CH, channels: 4, background: { r: 0, g: 0, b: 0, alpha: 0 } } })
    .composite(layers.map(l => ({ ...l, top: 0, left: 0 })))
    .webp({ quality: 88 })
    .toFile(`assets/${name}.webp`);
  console.log(`${name}.webp created`);
}

mkdirSync('assets', { recursive: true });
await makeHero();
await makeClip('clip-1', 200, 50, 50);
await makeClip('clip-2', 30, 130, 230);
await makeClip('clip-3', 40, 180, 90);
console.log('All images generated');
