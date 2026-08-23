import * as THREE from "three";

// ---- query params (set by render_shot.js when it navigates the page) ----
const params = new URLSearchParams(window.location.search);
const srcUrl = params.get("src");
const depthUrl = params.get("depth");
const width = parseInt(params.get("width") || "1280", 10);
const height = parseInt(params.get("height") || "720", 10);
const duration = parseFloat(params.get("duration") || "5");
const segments = parseInt(params.get("segments") || "256", 10);
// Bounded per the rebuild spec: translation under ~5-8% of scene width,
// rotation under ~3-5 degrees. Bigger moves expose empty geometry at depth
// discontinuities since there is no inpainting of occluded regions.
const motion = JSON.parse(params.get("motion") || '{"type":"push_in","amount":0.06}');
const displacementScale = parseFloat(params.get("displacement") || "0.35");

window.__ready = false;

const canvas = document.createElement("canvas");
document.body.appendChild(canvas);
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
renderer.setSize(width, height, false);
renderer.setPixelRatio(1);

const camera = new THREE.PerspectiveCamera(35, width / height, 0.1, 100);
const cameraDistance = 4;
camera.position.set(0, 0, cameraDistance);
camera.lookAt(0, 0, 0);

const scene = new THREE.Scene();

const vertexShader = `
  uniform sampler2D depthMap;
  uniform float displacementScale;
  varying vec2 vUv;
  void main() {
    vUv = uv;
    float depth = texture2D(depthMap, uv).r; // 0 = far, 1 = near (Depth-Anything-V2 convention)
    vec3 displaced = position + normal * depth * displacementScale;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(displaced, 1.0);
  }
`;
const fragmentShader = `
  uniform sampler2D colorMap;
  varying vec2 vUv;
  void main() {
    gl_FragColor = texture2D(colorMap, vUv);
  }
`;

function loadTexture(url) {
  return new Promise((resolve, reject) => {
    new THREE.TextureLoader().load(
      url,
      (texture) => {
        texture.colorSpace = THREE.SRGBColorSpace;
        texture.minFilter = THREE.LinearFilter;
        texture.magFilter = THREE.LinearFilter;
        resolve(texture);
      },
      undefined,
      reject
    );
  });
}

let material = null;
let mesh = null;

async function init() {
  const [colorTex, depthTex] = await Promise.all([loadTexture(srcUrl), loadTexture(depthUrl)]);
  depthTex.colorSpace = THREE.NoColorSpace;

  // Size the plane in world units so it fills the camera frustum at z=0,
  // matching the output canvas aspect ratio (source image is expected to
  // already match that aspect ratio - the Python pipeline generates/crops
  // scene images to the render resolution before depth estimation), PLUS a
  // safety overscan margin. setShotTime translates/rotates the camera within
  // the spec's bounded motion (translation <=8% of scene width, rotation
  // <=5deg); a plane sized to exactly fill the frustum only at the camera's
  // rest position exposes its own rectangular edge as soon as the camera
  // moves off that position - visible as a black wedge creeping in from a
  // corner. The overscan factor below is generous enough to cover the
  // spec's max bounds with margin; texture UVs still span 0-1 across this
  // larger plane so displacement/parallax math is unaffected.
  const vFov = (camera.fov * Math.PI) / 180;
  const visibleHeight = 2 * Math.tan(vFov / 2) * cameraDistance;
  const visibleWidth = visibleHeight * (width / height);
  const overscan = 1.5;

  const geometry = new THREE.PlaneGeometry(visibleWidth * overscan, visibleHeight * overscan, segments, segments);
  material = new THREE.ShaderMaterial({
    uniforms: {
      colorMap: { value: colorTex },
      depthMap: { value: depthTex },
      displacementScale: { value: displacementScale },
    },
    vertexShader,
    fragmentShader,
  });
  mesh = new THREE.Mesh(geometry, material);
  scene.add(mesh);

  renderer.render(scene, camera);
  window.__ready = true;
}

function smoothstep(t) {
  const x = Math.max(0, Math.min(1, t));
  return x * x * (3 - 2 * x);
}

// Camera path: starts at the negative half of the configured motion bound,
// ends at the positive half, eased with smoothstep - this is deliberately a
// SMALL, single continuous move for the whole shot, not per-layer motion.
window.setShotTime = function setShotTime(t) {
  const p = smoothstep(duration > 0 ? t / duration : 0);
  const swing = p - 0.5; // -0.5 .. 0.5
  const baseDistance = cameraDistance;

  camera.position.set(0, 0, baseDistance);
  camera.rotation.set(0, 0, 0);
  camera.up.set(0, 1, 0);
  camera.lookAt(0, 0, 0);

  if (motion.type === "push_in") {
    const amount = motion.amount ?? 0.06;
    camera.position.z = baseDistance - baseDistance * amount * p;
  } else if (motion.type === "pan") {
    const amount = motion.amount ?? 0.06;
    camera.position.x = baseDistance * amount * swing * 2;
    camera.lookAt(0, 0, 0);
  } else if (motion.type === "tilt") {
    const degrees = motion.amount ?? 4;
    camera.rotation.z = (degrees * Math.PI / 180) * swing * 2;
  } else if (motion.type === "orbit") {
    const amount = motion.amount ?? 0.05;
    camera.position.x = baseDistance * amount * swing * 2;
    camera.position.z = baseDistance - baseDistance * 0.03 * p;
    camera.lookAt(0, 0, 0);
  }

  renderer.render(scene, camera);
};

init().catch((err) => {
  window.__error = String(err && err.stack ? err.stack : err);
});
