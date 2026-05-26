/**
 * book-scene.js — Shared Three.js floating 3D book scene
 * libraire — used on hero and page-header sections site-wide
 *
 * Usage:
 *   import { initBookScene } from '/frontend/js/book-scene.js';
 *   const handle = initBookScene(canvas, container, { theme: 'dark' });
 *   handle?.stop();  // to clean up
 */

import * as THREE from 'three';

// ── Book library (ISBN-13 + title for canvas fallback) ─────────────────────
const BOOK_LIBRARY = [
  { isbn: '9780307387899', title: 'The Road (Vintage)' },
  { isbn: '9780062316097', title: 'Sapiens' },
  { isbn: '9780441013593', title: 'Dune' },
  { isbn: '9780061122415', title: 'The Alchemist' },
  { isbn: '9780451524935', title: '1984' },
  { isbn: '9780807014271', title: "Man's Search for Meaning" },
  { isbn: '9780857197689', title: 'Psychology of Money' },
  { isbn: '9780399590504', title: 'The Subtle Art of Not Giving a F*ck' },
  { isbn: '9780525564195', title: 'Where the Crawdads Sing' },
  { isbn: '9780593135228', title: 'The Midnight Library' },
  { isbn: '9780316769488', title: 'Catcher in the Rye' },
  { isbn: '9780143127749', title: 'The Power of Habit' },
  { isbn: '9780141439518', title: 'Pride and Prejudice' },
  { isbn: '9780671027032', title: 'Angels & Demons' },
  { isbn: '9780385737951', title: 'The Hunger Games' },
  { isbn: '9780439708180', title: "Harry Potter: Sorcerer's Stone" },
  { isbn: '9780618002221', title: 'The Fellowship of the Ring' },
  { isbn: '9780743273565', title: 'The Great Gatsby' },
  { isbn: '9780061743528', title: 'To Kill a Mockingbird' },
  { isbn: '9780062409850', title: 'Thinking, Fast and Slow' },
  { isbn: '9780553380163', title: 'A Brief History of Time' },
  { isbn: '9780062301239', title: 'Outliers' },
  { isbn: '9780553418026', title: 'Ready Player One' },
  { isbn: '9780307887436', title: 'Gone Girl' },
  { isbn: '9780307454546', title: 'The Road' },
  { isbn: '9781250301697', title: 'Normal People' },
  { isbn: '9780812974492', title: 'Educated' },
  { isbn: '9780525559474', title: 'Becoming' },
  { isbn: '9780385490818', title: "The Handmaid's Tale" },
  { isbn: '9780385544528', title: 'Little Fires Everywhere' },
  { isbn: '9780316346627', title: 'Big Little Lies' },
  { isbn: '9781501156700', title: 'The Glass Castle' },
  { isbn: '9780374533557', title: 'The Road Less Travelled' },
  { isbn: '9780062315007', title: 'The Power of Now' },
  { isbn: '9781982137274', title: 'Think Again' },
  { isbn: '9781250178602', title: 'Circe' },
  { isbn: '9780385547345', title: 'The Invisible Life of Addie LaRue' },
  { isbn: '9780735211292', title: 'Atomic Habits' },
  { isbn: '9780063204150', title: 'Fourth Wing' },
];

// ── Vibrant gradient palette for canvas-generated covers ──────────────────
const COVER_GRADIENTS = [
  ['#e63946', '#9d0208'],    // vivid crimson
  ['#4361ee', '#3a0ca3'],    // electric indigo
  ['#06d6a0', '#007f5f'],    // emerald teal
  ['#7209b7', '#560bad'],    // vivid violet
  ['#ff6d00', '#d62828'],    // fiery orange
  ['#f72585', '#b5179e'],    // hot magenta
  ['#ffd166', '#e07c00'],    // golden amber
  ['#00b4d8', '#0077b6'],    // ocean blue
  ['#55a630', '#1b4332'],    // forest green
  ['#8338ec', '#3a86ff'],    // purple–sky
  ['#fb5607', '#ffbe0b'],    // orange–gold
  ['#ef233c', '#4a4e69'],    // red–slate
  ['#0f3460', '#533483'],    // midnight indigo
  ['#2dc653', '#005f73'],    // neon green–teal
  ['#ff0054', '#ff9100'],    // hot red–orange
  ['#023e8a', '#48cae4'],    // deep–sky blue
  ['#6a040f', '#e85d04'],    // dark red–amber
  ['#6930c3', '#56cfe1'],    // violet–cyan
];

// ── Canvas cover generator ─────────────────────────────────────────────────
/**
 * Creates a Three.js CanvasTexture that looks like a designed book cover.
 * Used as fallback when OpenLibrary returns no image or a 1×1 placeholder.
 */
function makeCanvasCover(title, gradA, gradB) {
  const W = 128, H = 192;
  const cvs = document.createElement('canvas');
  cvs.width = W;
  cvs.height = H;
  const ctx = cvs.getContext('2d');

  // — Background gradient —
  const grad = ctx.createLinearGradient(0, 0, W * 0.7, H);
  grad.addColorStop(0, gradA);
  grad.addColorStop(1, gradB);
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, W, H);

  // — Diagonal highlight stripe —
  ctx.save();
  ctx.globalAlpha = 0.13;
  ctx.fillStyle = '#ffffff';
  ctx.beginPath();
  ctx.moveTo(W * 0.50, 0);
  ctx.lineTo(W, 0);
  ctx.lineTo(W, H * 0.42);
  ctx.closePath();
  ctx.fill();
  ctx.restore();

  // — Bottom subtle fill —
  const botGrad = ctx.createLinearGradient(0, H * 0.65, 0, H);
  botGrad.addColorStop(0, 'rgba(0,0,0,0)');
  botGrad.addColorStop(1, 'rgba(0,0,0,0.30)');
  ctx.fillStyle = botGrad;
  ctx.fillRect(0, H * 0.65, W, H * 0.35);

  // — Outer border —
  ctx.strokeStyle = 'rgba(255,255,255,0.32)';
  ctx.lineWidth = 2.5;
  ctx.strokeRect(5, 5, W - 10, H - 10);

  // — Inner accent line —
  ctx.strokeStyle = 'rgba(255,255,255,0.16)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(10, H * 0.68);
  ctx.lineTo(W - 10, H * 0.68);
  ctx.stroke();

  // — Decorative dots row —
  ctx.fillStyle = 'rgba(255,255,255,0.22)';
  for (let d = 0; d < 5; d++) {
    ctx.beginPath();
    ctx.arc(15 + d * 10, H * 0.74, 2, 0, Math.PI * 2);
    ctx.fill();
  }

  // — Title text (word-wrapped) —
  ctx.fillStyle = '#ffffff';
  ctx.textAlign = 'center';
  ctx.shadowColor = 'rgba(0,0,0,0.50)';
  ctx.shadowBlur = 5;

  const words = title.split(' ');
  const lines = [];
  let cur = '';
  ctx.font = 'bold 12px Arial, sans-serif';
  const maxTW = W - 20;
  for (const w of words) {
    const test = cur ? cur + ' ' + w : w;
    if (ctx.measureText(test).width > maxTW && cur) {
      lines.push(cur);
      cur = w;
    } else {
      cur = test;
    }
  }
  if (cur) lines.push(cur);

  const lineH = 16;
  const startY = H * 0.38 - ((lines.length - 1) * lineH) / 2;
  ctx.font = 'bold 12px Arial, sans-serif';
  lines.forEach((l, i) => ctx.fillText(l, W / 2, startY + i * lineH));

  // — Branding at bottom —
  ctx.shadowBlur = 0;
  ctx.font = '7px Arial, sans-serif';
  ctx.fillStyle = 'rgba(255,255,255,0.40)';
  ctx.fillText('libraire', W / 2, H - 12);

  const tex = new THREE.CanvasTexture(cvs);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

// ── Default book positions ────────────────────────────────────────────────

/** Wide-hero (dark, ~±10 units horizontal) — books clustered at edges */
const DARK_HERO_POS = [
  { pos: [-6.2,  2.5, -1.8], rot: [-0.12,  0.55,  0.17], scale: 0.88 },
  { pos: [ 6.4,  2.2, -2.1], rot: [ 0.09, -0.52,  0.14], scale: 0.84 },
  { pos: [-6.6, -0.2, -1.2], rot: [ 0.21,  0.45, -0.10], scale: 0.76 },
  { pos: [ 6.5, -0.6, -1.6], rot: [-0.10, -0.44,  0.23], scale: 0.80 },
  { pos: [-5.0, -2.6, -1.4], rot: [ 0.19,  0.32, -0.14], scale: 0.71 },
  { pos: [ 5.2, -2.3, -2.0], rot: [-0.13, -0.30,  0.12], scale: 0.75 },
  { pos: [-2.4,  3.2, -3.0], rot: [ 0.05,  0.22,  0.09], scale: 0.64 },
  { pos: [ 2.6,  3.0, -2.9], rot: [ 0.07, -0.20,  0.08], scale: 0.66 },
  { pos: [-3.8, -0.8, -3.4], rot: [ 0.08,  0.16,  0.04], scale: 0.58 },
  { pos: [ 4.0,  1.0, -3.3], rot: [ 0.04, -0.16,  0.05], scale: 0.60 },
  { pos: [-7.2,  0.8, -2.6], rot: [ 0.14,  0.38, -0.08], scale: 0.68 },
  { pos: [ 7.4, -1.5, -2.4], rot: [-0.09, -0.42,  0.17], scale: 0.70 },
];

/** Page-header (light, narrower vertical space) */
const LIGHT_HEADER_POS = [
  { pos: [-7.5,  1.2, -1.0], rot: [-0.08,  0.45,  0.10], scale: 0.62 },
  { pos: [ 7.7,  0.8, -1.5], rot: [ 0.06, -0.48,  0.09], scale: 0.64 },
  { pos: [-8.2, -0.8, -0.8], rot: [ 0.15,  0.38, -0.07], scale: 0.55 },
  { pos: [ 8.4, -1.0, -1.2], rot: [-0.07, -0.38,  0.14], scale: 0.58 },
  { pos: [-5.5,  1.8, -2.0], rot: [ 0.04,  0.28,  0.06], scale: 0.50 },
  { pos: [ 5.8,  1.5, -2.0], rot: [ 0.05, -0.25,  0.05], scale: 0.52 },
  { pos: [-6.8, -1.5, -1.8], rot: [ 0.10,  0.20, -0.05], scale: 0.48 },
  { pos: [ 7.0, -1.8, -1.6], rot: [-0.08, -0.22,  0.07], scale: 0.50 },
  { pos: [-4.3,  0.3, -2.6], rot: [ 0.06,  0.14,  0.04], scale: 0.44 },
  { pos: [ 4.5, -0.2, -2.5], rot: [ 0.05, -0.15,  0.05], scale: 0.45 },
  { pos: [-2.0,  1.6, -3.2], rot: [ 0.03,  0.10,  0.02], scale: 0.40 },
  { pos: [ 2.2,  1.2, -3.1], rot: [ 0.04, -0.10,  0.03], scale: 0.41 },
];

// ── Main export ───────────────────────────────────────────────────────────

/**
 * @param {HTMLCanvasElement} canvas
 * @param {HTMLElement}       container  — used for sizing & ResizeObserver
 * @param {object}            [opts]
 * @param {'dark'|'light'}    [opts.theme='dark']
 * @param {number}            [opts.bookCount=8]
 * @param {number}            [opts.particleCount=140]
 * @param {boolean}           [opts.enableMouse=true]
 * @param {number}            [opts.minWidth=768]
 * @param {Array}             [opts.bookPositions]  — override default positions
 * @param {string[]}          [opts.isbns]          — override default ISBNs
 * @returns {{ stop(): void } | null}
 */
export function initBookScene(canvas, container, opts = {}) {
  const {
    theme         = 'dark',
    bookCount     = 8,
    particleCount = 140,
    enableMouse   = true,
    minWidth      = 768,
    bookPositions = null,
    isbns         = null,
  } = opts;

  if (!canvas || !container) return null;
  if (window.innerWidth < minWidth) return null;

  const isDark   = theme === 'dark';
  const library  = BOOK_LIBRARY;
  const defaultP = isDark ? DARK_HERO_POS : LIGHT_HEADER_POS;
  const configs  = (bookPositions || defaultP).slice(0, bookCount);

  // ── Renderer ─────────────────────────────────────────────────────────────
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x000000, 0);

  let W = Math.max(container.clientWidth,  1);
  let H = Math.max(container.clientHeight, 1);
  renderer.setSize(W, H);

  // ── Scene & camera ────────────────────────────────────────────────────────
  const scene  = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(60, W / H, 0.1, 100);
  camera.position.set(0, 0, 8);

  // ── Lighting ──────────────────────────────────────────────────────────────
  if (isDark) {
    scene.add(new THREE.AmbientLight(0xffe0cc, 0.90));
    const dl = new THREE.DirectionalLight(0xfff8ee, 1.7);
    dl.position.set(4, 6, 5);
    scene.add(dl);
    const rl = new THREE.DirectionalLight(0xd97706, 0.60);
    rl.position.set(-5, -3, 2);
    scene.add(rl);
    // Extra fill to reveal cover colors
    const fl = new THREE.DirectionalLight(0xffffff, 0.40);
    fl.position.set(0, 0, 10);
    scene.add(fl);
  } else {
    scene.add(new THREE.AmbientLight(0xffffff, 1.5));
    const dl = new THREE.DirectionalLight(0xfffbf0, 1.2);
    dl.position.set(3, 5, 6);
    scene.add(dl);
    const rl = new THREE.DirectionalLight(0xf59e0b, 0.30);
    rl.position.set(-4, -2, 2);
    scene.add(rl);
    const fl = new THREE.DirectionalLight(0xffffff, 0.50);
    fl.position.set(0, 0, 10);
    scene.add(fl);
  }

  // ── Books ─────────────────────────────────────────────────────────────────
  const loader = new THREE.TextureLoader();
  const books  = [];

  configs.forEach((cfg, i) => {
    // Cycle through the full library, shuffled by offset
    const libIdx    = (i * 3 + 7) % library.length; // non-sequential spread
    const book      = library[libIdx];
    const coverUrl  = `https://covers.openlibrary.org/b/isbn/${book.isbn}-M.jpg`;
    const gradient  = COVER_GRADIENTS[i % COVER_GRADIENTS.length];

    // Spine and page edge materials
    const spineMat = new THREE.MeshStandardMaterial({
      color: isDark ? 0x3d1f00 : 0x7c3a00, roughness: 0.72,
    });
    const pageMat = new THREE.MeshStandardMaterial({
      color: isDark ? 0xfef3c7 : 0xfefce8, roughness: 0.90,
    });

    // Pre-build canvas cover as immediate fallback (visible before fetch completes)
    const canvasTex = makeCanvasCover(book.title, gradient[0], gradient[1]);
    const canvasMat = new THREE.MeshStandardMaterial({
      map: canvasTex, roughness: 0.50, metalness: 0.06,
    });
    const canvasMatBack = new THREE.MeshStandardMaterial({
      map: canvasTex, roughness: 0.62, metalness: 0.04,
      opacity: 0.55, transparent: true,
    });

    // [+x spine, -x pages, +y top, -y bottom, +z cover, -z back]
    const mats = [spineMat, pageMat, pageMat, pageMat, canvasMat, canvasMatBack];

    const geo  = new THREE.BoxGeometry(1.35, 2.05, 0.14);
    const mesh = new THREE.Mesh(geo, [...mats]); // spread so we can swap per-slot
    mesh.position.set(...cfg.pos);
    mesh.rotation.set(...cfg.rot);
    mesh.scale.setScalar(cfg.scale);

    // Try to load real cover — upgrade to photo texture if it's a real image
    loader.load(
      coverUrl,
      (tex) => {
        // OpenLibrary returns a 1×1 grey pixel when no cover exists
        if (tex.image.width <= 1 || tex.image.height <= 1) return;
        tex.colorSpace = THREE.SRGBColorSpace;
        const realMat = new THREE.MeshStandardMaterial({
          map: tex, roughness: 0.48, metalness: 0.05,
        });
        const realBack = new THREE.MeshStandardMaterial({
          map: tex, roughness: 0.60, metalness: 0.04,
          opacity: 0.50, transparent: true,
        });
        mesh.material[4] = realMat;
        mesh.material[5] = realBack;
      },
      undefined,
      () => { /* error — keep canvas fallback already applied */ }
    );

    scene.add(mesh);
    books.push({
      mesh,
      basePos: [...cfg.pos],
      baseRot: [...cfg.rot],
      speed:   0.24 + i * 0.055,
      phase:   i * 1.27,
    });
  });

  // ── Particles ─────────────────────────────────────────────────────────────
  let partMesh = null;
  if (particleCount > 0) {
    const spread = isDark ? 16 : 20;
    const pos    = new Float32Array(particleCount * 3);
    for (let i = 0; i < particleCount; i++) {
      pos[i * 3]     = (Math.random() - 0.5) * spread;
      pos[i * 3 + 1] = (Math.random() - 0.5) * 10;
      pos[i * 3 + 2] = (Math.random() - 0.5) * 6 - 1;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    partMesh = new THREE.Points(
      geo,
      new THREE.PointsMaterial({
        color:       isDark ? 0xffc355 : 0xf59e0b,
        size:        isDark ? 0.036   : 0.028,
        transparent: true,
        opacity:     isDark ? 0.50    : 0.30,
      })
    );
    scene.add(partMesh);
  }

  // ── Mouse parallax ────────────────────────────────────────────────────────
  let mx = 0, my = 0;
  let onMM = null;
  if (enableMouse) {
    onMM = (e) => {
      mx = (e.clientX / window.innerWidth  - 0.5) * 2;
      my = (e.clientY / window.innerHeight - 0.5) * 2;
    };
    document.addEventListener('mousemove', onMM, { passive: true });
  }

  // ── Resize ────────────────────────────────────────────────────────────────
  const ro = new ResizeObserver(() => {
    W = Math.max(container.clientWidth,  1);
    H = Math.max(container.clientHeight, 1);
    renderer.setSize(W, H);
    camera.aspect = W / H;
    camera.updateProjectionMatrix();
  });
  ro.observe(container);

  // ── Render loop ───────────────────────────────────────────────────────────
  let rafId;
  (function loop() {
    rafId = requestAnimationFrame(loop);
    const t   = performance.now() * 0.001;
    const pmx = mx * (isDark ? 0.40 : 0.25);
    const pmy = my * (isDark ? 0.18 : 0.12);

    books.forEach((b, i) => {
      // gentle float
      b.mesh.position.y = b.basePos[1] + Math.sin(t * b.speed + b.phase) * 0.13;
      // mouse parallax (closer books move more)
      const depth = Math.abs(b.basePos[2]);
      const para  = 1 / (1 + depth * 0.3);
      b.mesh.position.x = b.basePos[0] + pmx * para * (1 + (i % 3) * 0.25);
      // subtle rotation oscillation
      b.mesh.rotation.y = b.baseRot[1] + Math.sin(t * 0.18 + b.phase) * 0.07 + mx * 0.06;
      b.mesh.rotation.z = b.baseRot[2] + Math.cos(t * 0.13 + b.phase * 0.7) * 0.025;
    });

    if (partMesh) {
      partMesh.rotation.y = t * 0.030;
      partMesh.rotation.x = Math.sin(t * 0.045) * 0.035 - pmy * 0.8;
    }

    renderer.render(scene, camera);
  })();

  // ── Cleanup handle ────────────────────────────────────────────────────────
  return {
    stop() {
      cancelAnimationFrame(rafId);
      ro.disconnect();
      if (onMM) document.removeEventListener('mousemove', onMM);
      renderer.dispose();
    },
  };
}
