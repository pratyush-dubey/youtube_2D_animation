#!/usr/bin/env node
/**
 * CLI driver: renders one depth-displaced parallax shot to a PNG frame
 * sequence using headless Puppeteer + the Three.js scene in scene.js.
 *
 * Usage:
 *   node render_shot.js --image <path> --depth <path> --duration <sec>
 *     [--fps 30] [--width 1280] [--height 720] [--out <dir>]
 *     [--motion '{"type":"push_in","amount":0.06}'] [--segments 256]
 *     [--displacement 0.35]
 */
import fs from "node:fs";
import path from "node:path";
import http from "node:http";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token.startsWith("--")) {
      const key = token.slice(2);
      const next = argv[i + 1];
      if (next === undefined || next.startsWith("--")) {
        out[key] = true;
      } else {
        out[key] = next;
        i += 1;
      }
    }
  }
  return out;
}

const MIME = {
  ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript",
  ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
  ".json": "application/json",
};

function startStaticServer(rootDir) {
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      try {
        const urlPath = decodeURIComponent(req.url.split("?")[0]);
        const filePath = path.join(rootDir, urlPath);
        if (!filePath.startsWith(rootDir)) {
          res.writeHead(403); res.end("forbidden"); return;
        }
        const ext = path.extname(filePath);
        const data = fs.readFileSync(filePath);
        res.writeHead(200, { "Content-Type": MIME[ext] || "application/octet-stream" });
        res.end(data);
      } catch (err) {
        res.writeHead(404); res.end(String(err));
      }
    });
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => resolve(server));
  });
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const required = ["image", "depth", "duration", "out"];
  for (const key of required) {
    if (!args[key]) {
      console.error(`Missing required --${key}`);
      process.exit(1);
    }
  }

  const fps = parseInt(args.fps || "30", 10);
  const width = parseInt(args.width || "1280", 10);
  const height = parseInt(args.height || "720", 10);
  const duration = parseFloat(args.duration);
  const segments = parseInt(args.segments || "256", 10);
  const displacement = parseFloat(args.displacement || "0.35");
  const motion = args.motion || '{"type":"push_in","amount":0.06}';
  const outDir = path.resolve(args.out);
  fs.mkdirSync(outDir, { recursive: true });

  // Stage the source image/depth map inside the package dir so the static
  // server (rooted here, so it can also serve node_modules/three) can reach
  // them by relative URL regardless of where they actually live on disk.
  const jobId = crypto.randomUUID();
  const stageDir = path.join(__dirname, "_tmp", jobId);
  fs.mkdirSync(stageDir, { recursive: true });
  const srcExt = path.extname(args.image) || ".jpg";
  const stagedSrc = path.join(stageDir, `source${srcExt}`);
  const stagedDepth = path.join(stageDir, "depth.png");
  fs.copyFileSync(path.resolve(args.image), stagedSrc);
  fs.copyFileSync(path.resolve(args.depth), stagedDepth);

  const server = await startStaticServer(__dirname);
  const port = server.address().port;

  const browser = await puppeteer.launch({ headless: true, args: ["--no-sandbox"] });
  try {
    const page = await browser.newPage();
    await page.setViewport({ width, height, deviceScaleFactor: 1 });
    page.on("console", (msg) => {
      if (msg.type() === "error") console.error("[page]", msg.text());
    });

    const query = new URLSearchParams({
      src: `_tmp/${jobId}/source${srcExt}`,
      depth: `_tmp/${jobId}/depth.png`,
      width: String(width), height: String(height),
      duration: String(duration), segments: String(segments),
      displacement: String(displacement), motion,
    });
    await page.goto(`http://127.0.0.1:${port}/scene.html?${query.toString()}`, { waitUntil: "load" });
    await page.waitForFunction("window.__ready === true || window.__error !== undefined", { timeout: 30000 });
    const pageError = await page.evaluate(() => window.__error);
    if (pageError) throw new Error(`Three.js scene failed to initialise: ${pageError}`);

    const frameCount = Math.max(1, Math.round(duration * fps));
    for (let i = 0; i < frameCount; i += 1) {
      const t = i / fps;
      await page.evaluate((tt) => window.setShotTime(tt), t);
      const framePath = path.join(outDir, `frame_${String(i).padStart(5, "0")}.png`);
      await page.screenshot({ path: framePath });
    }

    console.log(JSON.stringify({ frames: frameCount, fps, width, height, out: outDir }));
  } finally {
    await browser.close();
    server.close();
    fs.rmSync(stageDir, { recursive: true, force: true });
  }
}

main().catch((err) => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
});
