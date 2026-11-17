// 3D-монета ₸ (бордо и золото) на Three.js.
// Исходник; собранный файл — app/static/coin3d.js (см. frontend/README.md).
// Монета медленно вращается, поворачивается за курсором, её можно покрутить мышью или пальцем.
// Анимация останавливается, когда монету не видно, и не запускается, если в системе
// выключены анимации (prefers-reduced-motion) — тогда монета просто стоит под углом.

import {
  ACESFilmicToneMapping,
  CanvasTexture,
  CylinderGeometry,
  DirectionalLight,
  Group,
  Mesh,
  MeshStandardMaterial,
  PerspectiveCamera,
  PMREMGenerator,
  RepeatWrapping,
  Scene,
  SRGBColorSpace,
  WebGLRenderer,
} from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

const GOLD = "#d4ad55";
const WINE = "#4f1222";
const S = 512;

function tenge(ctx, cx, cy, s) {
  ctx.fillRect(cx - s / 2, cy - s * 0.56, s, s * 0.13);
  ctx.fillRect(cx - s / 2, cy - s * 0.3, s, s * 0.13);
  ctx.fillRect(cx - s * 0.075, cy - s * 0.3, s * 0.15, s * 0.86);
}

function layer(fill) {
  const c = document.createElement("canvas");
  c.width = c.height = S;
  const ctx = c.getContext("2d");
  ctx.fillStyle = fill;
  ctx.fillRect(0, 0, S, S);
  return [c, ctx];
}

function texture(canvas, color) {
  const t = new CanvasTexture(canvas);
  if (color) t.colorSpace = SRGBColorSpace;
  t.anisotropy = 4;
  t.center.set(0.5, 0.5);
  t.rotation = Math.PI / 2; // крышка цилиндра повёрнута — выравниваем знак
  return t;
}

// Лицевая сторона: цвет, рельеф и где металл, а где эмаль
function faceMaterial() {
  const C = S / 2;
  const [col, cc] = layer(GOLD);
  const [bump, bc] = layer("#555");
  const [metal, mc] = layer("#fff");
  const g = cc.createRadialGradient(C * 0.8, C * 0.7, 20, C, C, C);
  g.addColorStop(0, "#e2bf6c");
  g.addColorStop(0.6, "#c99d45");
  g.addColorStop(1, "#8a6a1f");
  cc.fillStyle = g;
  cc.fillRect(0, 0, S, S);
  // бортик
  bc.lineWidth = 23;
  bc.strokeStyle = "#fff";
  bc.beginPath();
  bc.arc(C, C, C - 15, 0, 7);
  bc.stroke();
  // бордовая эмаль внутри
  const inner = C - 32;
  for (const [ctx, fill] of [[cc, WINE], [mc, "#222"], [bc, "#3a3a3a"]]) {
    ctx.fillStyle = fill;
    ctx.beginPath();
    ctx.arc(C, C, inner, 0, 7);
    ctx.fill();
  }
  // золотые точки по кругу
  for (let i = 0; i < 48; i++) {
    const a = (i / 48) * Math.PI * 2;
    const r = C - 50;
    for (const [ctx, fill] of [[cc, GOLD], [bc, "#fff"], [mc, "#fff"]]) {
      ctx.fillStyle = fill;
      ctx.beginPath();
      ctx.arc(C + Math.cos(a) * r, C + Math.sin(a) * r, 4.5, 0, 7);
      ctx.fill();
    }
  }
  // знак тенге
  const size = 215;
  const dy = size * 0.15;
  cc.fillStyle = "#e7c46f";
  tenge(cc, C, C + dy, size);
  bc.fillStyle = "#fff";
  tenge(bc, C, C + dy, size);
  mc.fillStyle = "#fff";
  tenge(mc, C, C + dy, size);

  return new MeshStandardMaterial({
    map: texture(col, true),
    bumpMap: texture(bump),
    bumpScale: 3,
    metalness: 1,
    metalnessMap: texture(metal),
    roughness: 0.28,
  });
}

function edgeMaterial() {
  const c = document.createElement("canvas");
  c.width = 256;
  c.height = 4;
  const ctx = c.getContext("2d");
  for (let i = 0; i < 256; i += 4) {
    ctx.fillStyle = i % 8 ? "#fff" : "#333";
    ctx.fillRect(i, 0, 4, 4);
  }
  const t = new CanvasTexture(c);
  t.wrapS = RepeatWrapping;
  t.repeat.set(6, 1);
  return new MeshStandardMaterial({ color: GOLD, metalness: 1, roughness: 0.35, bumpMap: t, bumpScale: 2 });
}

/**
 * Вставляет монету в box (элемент с заданными шириной и высотой).
 * Возвращает true, если получилось; false — если WebGL недоступен.
 */
export function mountCoin(box) {
  let renderer;
  try {
    renderer = new WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
  } catch {
    return false;
  }
  const canvas = renderer.domElement;
  canvas.className = "coin3d";
  canvas.setAttribute("aria-hidden", "true");
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.toneMapping = ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;

  const scene = new Scene();
  const pmrem = new PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  pmrem.dispose();
  const light = new DirectionalLight(0xfff1d6, 1.6);
  light.position.set(2, 3, 4);
  scene.add(light);

  const camera = new PerspectiveCamera(30, 1, 0.1, 50);
  camera.position.set(0, 0, 4.7);

  const face = faceMaterial();
  const mesh = new Mesh(new CylinderGeometry(1, 1, 0.16, 96, 1), [edgeMaterial(), face, face]);
  mesh.rotation.x = Math.PI / 2;
  const coin = new Group();
  coin.add(mesh);
  scene.add(coin);

  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let tx = 0;
  let ty = 0;
  let spin = reduce ? -0.45 : 0;
  let dragX = null;
  let visible = true;

  const resize = () => {
    const size = box.clientWidth || 130;
    renderer.setSize(size, size, false);
  };
  resize();
  box.append(canvas);

  const frame = () => {
    const t = performance.now() / 1000;
    if (!reduce && dragX === null) spin += 0.008;
    coin.rotation.y += (spin + tx * 1.2 - coin.rotation.y) * 0.08;
    coin.rotation.x += (ty - coin.rotation.x) * 0.08;
    coin.position.y = reduce ? 0 : Math.sin(t * 1.4) * 0.04;
    renderer.render(scene, camera);
  };
  const run = () => renderer.setAnimationLoop(visible && !document.hidden ? frame : null);

  if (reduce) {
    coin.rotation.y = spin;
    renderer.render(scene, camera);
  } else {
    new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      run();
    }).observe(box);
    document.addEventListener("visibilitychange", run);
    run();
  }

  canvas.addEventListener("pointermove", (e) => {
    const r = canvas.getBoundingClientRect();
    tx = ((e.clientX - r.left) / r.width - 0.5) * 0.9;
    ty = ((e.clientY - r.top) / r.height - 0.5) * 0.7;
    if (dragX !== null) {
      spin += (e.clientX - dragX) * 0.012;
      dragX = e.clientX;
    }
    if (reduce) {
      coin.rotation.set(ty, spin + tx * 1.2, 0);
      renderer.render(scene, camera);
    }
  });
  canvas.addEventListener("pointerleave", () => {
    tx = ty = 0;
    dragX = null;
  });
  canvas.addEventListener("pointerdown", (e) => {
    dragX = e.clientX;
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointerup", () => {
    dragX = null;
  });
  window.addEventListener("resize", resize);
  return true;
}
