// The Ghost Over London — spectral 3D scene.
// Real OSM geometry as luminous wireframe; modelled PM2.5 as the only solid
// thing in the frame; the agent's errors rise off the stations as wisps.
import * as THREE from 'three';
import { OrbitControls } from '/static/vendor/OrbitControls.js';
import { EffectComposer } from '/static/vendor/postprocessing/EffectComposer.js';
import { RenderPass } from '/static/vendor/postprocessing/RenderPass.js';
import { UnrealBloomPass } from '/static/vendor/postprocessing/UnrealBloomPass.js';
import { OutputPass } from '/static/vendor/postprocessing/OutputPass.js';

// ---------- projection: local tangent-plane, metres ----------
const LAT0 = 51.515, LON0 = -0.165;
const M_LAT = 111320, M_LON = 111320 * Math.cos(LAT0 * Math.PI / 180);
const X = lon => (lon - LON0) * M_LON;
const Z = lat => -(lat - LAT0) * M_LAT;

// ---------- palette ----------
const COL = {
  bg: 0x02030a,   // darker — OutputPass sRGB lifts the blacks a touch
  buildings: 0x5f6cff,
  towers: 0x8fa8ff,
  roads: 0x1f6f7a,
  beacon: 0x67e8f9,
  wisp: 0xe9d5ff,
};

const WIND_VIS_SPEED = 9;   // real direction, dramatized pace
const HAZE_N = 15000;

// ---------- data ----------
async function j(url, opts) { const r = await fetch(url, opts); if (!r.ok) throw new Error(url); return r.json(); }

const [city, windField, aqField, sceneState] = await Promise.all([
  j('/static/london-city.json'), j('/wind-field'), j('/aq-field'), j('/scene-state'),
]);

const wind = {
  u: windField.records[0].data, v: windField.records[1].data,
  h: windField.records[0].header,
};
const aq = { pm: aqField.pm25, nx: aqField.nx, ny: aqField.ny, b: aqField.bbox };

document.getElementById('sources').innerHTML =
  `<span>geometry <b>${city.source || 'OpenStreetMap'}</b></span>` +
  `<span>wind <b>${windField.source}</b></span>` +
  `<span>haze <b>${aqField.kind} · ${aqField.source}</b></span>`;

// ---------- bilinear field samplers (lat/lon space) ----------
function bilinear(arr, nx, ny, bbox, lat, lon) {
  const fx = Math.min(Math.max((lon - bbox.west) / (bbox.east - bbox.west), 0), 1) * (nx - 1);
  const fy = Math.min(Math.max((bbox.north - lat) / (bbox.north - bbox.south), 0), 1) * (ny - 1);
  const x0 = Math.floor(fx), y0 = Math.floor(fy);
  const x1 = Math.min(x0 + 1, nx - 1), y1 = Math.min(y0 + 1, ny - 1);
  const tx = fx - x0, ty = fy - y0;
  const a = arr[y0 * nx + x0], b = arr[y0 * nx + x1];
  const c = arr[y1 * nx + x0], d = arr[y1 * nx + x1];
  return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty;
}
const wb = { west: wind.h.lo1, east: wind.h.lo2, south: wind.h.la2, north: wind.h.la1 };
const windAt = (x, z) => {           // world metres → lat/lon → (u,v) m/s
  const lon = x / M_LON + LON0, lat = -z / M_LAT + LAT0;
  return [bilinear(wind.u, wind.h.nx, wind.h.ny, wb, lat, lon),
          bilinear(wind.v, wind.h.nx, wind.h.ny, wb, lat, lon)];
};
const pm25At = (x, z) => {
  const lon = x / M_LON + LON0, lat = -z / M_LAT + LAT0;
  return bilinear(aq.pm, aq.nx, aq.ny, aq.b, lat, lon);
};

// ---------- renderer / scene ----------
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.setClearColor(COL.bg);
document.getElementById('scene').appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.fog = new THREE.Fog(COL.bg, 3500, 17000);
const camera = new THREE.PerspectiveCamera(55, innerWidth / innerHeight, 1, 60000);
camera.position.set(-4500, 6500, 5200);

// bloom — the spectral glow. threshold keeps the void dark; beacons + haze bloom
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth, innerHeight), 0.55, 0.55, 0.32);
composer.addPass(bloom);
composer.addPass(new OutputPass());

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0, 0);
controls.enableDamping = true;
controls.dampingFactor = 0.06;
controls.maxPolarAngle = Math.PI * 0.495;
controls.maxDistance = 22000;

// ---------- city geometry → merged line segments ----------
function ringSegs(ring, y, out, step = 1) {
  for (let i = 0; i < ring.length - step; i += step) {
    const a = ring[i], b = ring[i + step];
    out.push(X(a[0]), y, Z(a[1]), X(b[0]), y, Z(b[1]));
  }
}

function buildCity(city) {
  const lo = [], hi = [];               // verts: low buildings vs towers
  for (const b of city.buildings) {
    const r = b.ring, h = b.h, tgt = h >= 35 ? hi : lo;
    ringSegs(r, 0.5, tgt);              // base
    ringSegs(r, h, tgt);                // roofline
    if (h >= 12) {                      // verticals only on taller buildings
      const step = Math.max(1, Math.floor(r.length / 5));
      for (let i = 0; i < r.length - 1; i += step) {
        const p = r[i];
        tgt.push(X(p[0]), 0.5, Z(p[1]), X(p[0]), h, Z(p[1]));
      }
    }
  }
  const mk = (verts, color, opacity) => {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
    const m = new THREE.LineSegments(g, new THREE.LineBasicMaterial({
      color, transparent: true, opacity,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    scene.add(m); return m;
  };
  mk(lo, COL.buildings, 0.10);
  mk(hi, COL.towers, 0.22);

  const rv = [];
  for (const rd of city.roads) {
    const pts = rd.line;
    for (let i = 0; i < pts.length - 1; i++) {
      rv.push(X(pts[i][0]), 0.4, Z(pts[i][1]), X(pts[i + 1][0]), 0.4, Z(pts[i + 1][1]));
    }
  }
  mk(rv, COL.roads, 0.16);
}
buildCity(city);

// ---------- soft sprite texture ----------
function softDot(size = 64, inner = 'rgba(255,255,255,1)') {
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, inner);
  g.addColorStop(0.35, 'rgba(255,255,255,.55)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  const t = new THREE.CanvasTexture(c);
  return t;
}
const dotTex = softDot();

// ---------- the ghost: PM2.5 haze advected by real wind ----------
const hazePos = new Float32Array(HAZE_N * 3);
const hazeCol = new Float32Array(HAZE_N * 3);
const hazeAge = new Float32Array(HAZE_N);
const hazeTTL = new Float32Array(HAZE_N);
const tmpC = new THREE.Color();

function spectral(t) {          // 0..1 → dim violet → hot magenta
  tmpC.setHSL(0.78 - 0.12 * t, 0.85, 0.28 + 0.35 * t);
  return tmpC;
}
// spawn within the CITY bbox so the ghost hangs over the streets, not the void
const cb = city.bbox;
function respawn(i) {
  hazePos[i * 3] = X(cb.west) + Math.random() * (X(cb.east) - X(cb.west));
  hazePos[i * 3 + 1] = 10 + Math.pow(Math.random(), 2.4) * 140;
  hazePos[i * 3 + 2] = Z(cb.south) + Math.random() * (Z(cb.north) - Z(cb.south));
  hazeAge[i] = 0;
  hazeTTL[i] = 8 + Math.random() * 14;
}
for (let i = 0; i < HAZE_N; i++) { respawn(i); hazeAge[i] = Math.random() * hazeTTL[i]; }

const hazeGeo = new THREE.BufferGeometry();
hazeGeo.setAttribute('position', new THREE.BufferAttribute(hazePos, 3));
hazeGeo.setAttribute('color', new THREE.BufferAttribute(hazeCol, 3));
const haze = new THREE.Points(hazeGeo, new THREE.PointsMaterial({
  size: 105, map: dotTex, vertexColors: true, transparent: true, opacity: 0.6,
  blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true,
}));
scene.add(haze);

const xMin = X(cb.west), xMax = X(cb.east);
const zMin = Z(cb.north), zMax = Z(cb.south);   // Z decreases northward

function updateHaze(dt) {
  for (let i = 0; i < HAZE_N; i++) {
    const ix = i * 3;
    const x = hazePos[ix], y = hazePos[ix + 1], z = hazePos[ix + 2];
    const [u, v] = windAt(x, z);
    hazePos[ix] = x + u * dt * WIND_VIS_SPEED;
    hazePos[ix + 2] = z - v * dt * WIND_VIS_SPEED;   // v is northward; z shrinks north
    hazeAge[i] += dt;
    const out = hazePos[ix] < xMin - 300 || hazePos[ix] > xMax + 300 ||
                hazePos[ix + 2] < zMin - 300 || hazePos[ix + 2] > zMax + 300;
    if (out || hazeAge[i] > hazeTTL[i]) { respawn(i); continue; }
    const pm = pm25At(hazePos[ix], hazePos[ix + 2]);
    const t = Math.min(1, pm / 35);                   // ~35 µg/m³ = heavy
    const fade = Math.min(1, hazeAge[i] / 2, (hazeTTL[i] - hazeAge[i]) / 2);
    const c = spectral(t);
    const k = (0.45 + 0.75 * t) * fade;
    hazeCol[ix] = c.r * k; hazeCol[ix + 1] = c.g * k; hazeCol[ix + 2] = c.b * k;
  }
  hazeGeo.attributes.position.needsUpdate = true;
  hazeGeo.attributes.color.needsUpdate = true;
}

// ---------- stations: beacons, rings, labels, wisps ----------
const stations = [];
const labelSprites = [];

function textSprite(lines, color = '#cfd6ee', size = 34) {
  const c = document.createElement('canvas');
  c.width = 512; c.height = 128;
  const ctx = c.getContext('2d');
  ctx.font = `600 ${size}px "Avenir Next", system-ui, sans-serif`;
  ctx.textAlign = 'center';
  ctx.shadowColor = 'rgba(0,0,0,.9)'; ctx.shadowBlur = 12;
  ctx.fillStyle = color;
  lines.forEach((l, i) => ctx.fillText(l, 256, 46 + i * 44));
  const t = new THREE.CanvasTexture(c);
  const s = new THREE.Sprite(new THREE.SpriteMaterial({
    map: t, transparent: true, depthWrite: false, opacity: 0.95 }));
  s.scale.set(700, 175, 1);
  s.material.opacity = 1;
  return s;
}

const beaconMats = [];
function buildStations(state) {
  for (const st of state.stations) {
    const x = X(st.lon), z = Z(st.lat);
    const grp = new THREE.Group();
    grp.position.set(x, 0, z);

    const shaftMat = new THREE.MeshBasicMaterial({
      color: COL.beacon, transparent: true, opacity: 0.3,
      blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide,
    });
    const shaft = new THREE.Mesh(new THREE.CylinderGeometry(8, 22, 900, 14, 1, true), shaftMat);
    shaft.position.y = 450;
    grp.add(shaft);
    beaconMats.push(shaftMat);

    const ring = new THREE.Mesh(
      new THREE.RingGeometry(60, 90, 48),
      new THREE.MeshBasicMaterial({ color: COL.beacon, transparent: true, opacity: 0.5,
        blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }));
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 1;
    grp.add(ring);

    const label = textSprite(
      [st.id.replace(/_/g, ' '),
       st.error != null ? `err ${st.error > 0 ? '+' : ''}${st.error.toFixed(1)} µg/m³` : 'awaiting truth'],
      st.error != null && Math.abs(st.error) > 3 ? '#f0abfc' : '#9fd8e8');
    label.position.y = 980;
    label.scale.set(1100, 275, 1);
    grp.add(label);
    labelSprites.push(label);

    // wisps — the agent's error, rising off the monitor
    let wisp = null;
    if (st.error != null && Math.abs(st.error) > 0.3) {
      const n = 60, wp = new Float32Array(n * 3), wc = new Float32Array(n * 3), seed = new Float32Array(n);
      for (let i = 0; i < n; i++) { seed[i] = Math.random(); wp[i * 3] = (Math.random() - 0.5) * 26; wp[i * 3 + 2] = (Math.random() - 0.5) * 26; }
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(wp, 3));
      g.setAttribute('color', new THREE.BufferAttribute(wc, 3));
      const pts = new THREE.Points(g, new THREE.PointsMaterial({
        size: 26, map: dotTex, vertexColors: true, transparent: true, opacity: 0.9,
        blending: THREE.AdditiveBlending, depthWrite: false }));
      grp.add(pts);
      wisp = { geo: g, seed, n, strength: Math.min(1, Math.abs(st.error) / 6) };
    }

    stations.push({ grp, wisp, st });
    scene.add(grp);
  }
}
buildStations(sceneState);

// ---------- film mode ----------
const FILM = [
  { dur: 7,  pos: [-4200, 6800, 5200], look: [0, 0, 0],
    cap: "Somewhere over the Atlantic, a ghost drifts east." },
  { dur: 7,  pos: [-900, 2600, 2100], look: [0, 120, -200],
    cap: "London. A city rendered from memory — every building real, every street true." },
  { dur: 6,  pos: [350, 900, 700], look: [X(-0.1546), 250, Z(51.5226)],
    cap: "Four monitors keep watch. One agent keeps score." },
  { dur: 6,  pos: [X(-0.1546) - 260, 120, Z(51.5226) + 420], look: [X(-0.1546), 320, Z(51.5226)],
    cap: "It predicts the haze — then waits for the truth to arrive." },
  { dur: 6,  pos: [1200, 3400, 2800], look: [0, 0, 0],
    cap: "When the truth lands, the error rises as a wisp. It learns — or it becomes a ghost itself." },
  { dur: 8,  pos: [-4500, 6500, 5200], look: [0, 0, 0],
    cap: "AeroLoop. The machine remembers every mistake." },
];

const capEl = document.getElementById('caption');
const verdictEl = document.getElementById('verdict');
let filming = false, filmT = 0;

function flashVerdict(text, rejected) {
  verdictEl.textContent = text;
  verdictEl.className = rejected ? 'rejected' : '';
  verdictEl.style.opacity = 1;
  setTimeout(() => verdictEl.style.opacity = 0, 2200);
}

document.getElementById('btnFilm').onclick = () => {
  filming = !filming;
  filmT = 0;
  controls.enabled = !filming;
  document.getElementById('btnFilm').textContent = filming ? '■ stop film' : '▶ play the film';
  document.getElementById('btnFilm').classList.toggle('active', filming);
  if (!filming) capEl.style.opacity = 0;
};

document.getElementById('btnLabels').onclick = (e) => {
  const on = !labelSprites[0]?.visible;
  labelSprites.forEach(s => s.visible = on);
  e.target.classList.toggle('active', on);
};

document.getElementById('btnDemo').onclick = async () => {
  const d = await j('/demo-day?hours=24', { method: 'POST' });
  capEl.textContent = `The agent gained ${d.simulated_pairs} memories across ${d.stations.length} stations.`;
  capEl.style.opacity = 1;
  setTimeout(() => { if (!filming) capEl.style.opacity = 0; }, 5000);
};

const smooth = t => t * t * (3 - 2 * t);
function playFilm(dt) {
  filmT += dt;
  let acc = 0;
  for (const k of FILM) {
    if (filmT < acc + k.dur) {
      const i = FILM.indexOf(k);
      const prev = i ? FILM[i - 1] : { pos: k.pos, look: k.look };
      const t = smooth(Math.min(1, (filmT - acc) / Math.min(3, k.dur)));
      camera.position.set(
        prev.pos[0] + (k.pos[0] - prev.pos[0]) * t,
        prev.pos[1] + (k.pos[1] - prev.pos[1]) * t,
        prev.pos[2] + (k.pos[2] - prev.pos[2]) * t);
      const lx = prev.look[0] + (k.look[0] - prev.look[0]) * t;
      const ly = prev.look[1] + (k.look[1] - prev.look[1]) * t;
      const lz = prev.look[2] + (k.look[2] - prev.look[2]) * t;
      camera.lookAt(lx, ly, lz);
      capEl.textContent = k.cap;
      capEl.style.opacity = (filmT - acc) > 0.6 && (filmT - acc) < k.dur - 0.8 ? 1 : 0;
      if (i === 4 && !playFilm._v4) {
        playFilm._v4 = true;
        // stamp the REAL latest verdict — the ghost story is honest either way
        const last = sceneState.strategies.at(-1);
        if (last) flashVerdict(last.kept ? `${last.version} — KEPT` : `${last.version} — REJECTED`, !last.kept);
      }
      return;
    }
    acc += k.dur;
  }
  filming = false;
  playFilm._v4 = false;
  controls.enabled = true;
  capEl.style.opacity = 0;
  document.getElementById('btnFilm').textContent = '▶ play the film';
  document.getElementById('btnFilm').classList.remove('active');
}

// ---------- loop ----------
const clock = new THREE.Clock();
let t0 = 0;
function tick() {
  requestAnimationFrame(tick);
  const dt = Math.min(0.05, clock.getDelta());
  t0 += dt;
  updateHaze(dt);
  beaconMats.forEach((m, i) => m.opacity = 0.18 + 0.12 * (0.5 + 0.5 * Math.sin(t0 * 1.8 + i * 1.3)));
  for (const s of stations) {
    if (!s.wisp) continue;
    const { geo, seed, n, strength } = s.wisp;
    const pos = geo.attributes.position.array, col = geo.attributes.color.array;
    for (let i = 0; i < n; i++) {
      const ph = (t0 * 0.14 + seed[i]) % 1;            // rise cycle
      pos[i * 3 + 1] = ph * 150;
      const k = strength * (1 - ph) * Math.min(1, ph * 8);
      col[i * 3] = 0.91 * k; col[i * 3 + 1] = 0.84 * k; col[i * 3 + 2] = 1.0 * k;
    }
    geo.attributes.position.needsUpdate = true;
    geo.attributes.color.needsUpdate = true;
  }
  if (filming) playFilm(dt); else controls.update();
  composer.render();
}
tick();

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
  composer.setSize(innerWidth, innerHeight);
});

const lo = document.getElementById('loading');
lo.style.opacity = 0;
setTimeout(() => lo.remove(), 1300);
