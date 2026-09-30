#!/usr/bin/env node
/*
 * Captures the console screenshots that the README and the
 * documentation show: the front page, and the top of one assessment
 * as a square with one category open on its brief, each in the light
 * and the dark theme, as JPEG files 1920 pixels wide at quality 75.
 * Every picture starts at the top of the page. It drives a headless
 * Chromium over the DevTools protocol, with nothing beyond the
 * WebSocket client built into Node 22 and later.
 *
 *   node capture-screenshots.mjs BASE_URL UPLOAD_ID CATEGORY OUT_DIR
 *
 * capture-screenshots.sh prepares the analyst and calls this. CHROME
 * names the browser binary when chromium or google-chrome on PATH is
 * not the one to use.
 */

import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { writeFile } from 'node:fs/promises';
import { delimiter, join } from 'node:path';

// The page is laid out WIDTH by HEIGHT CSS pixels and drawn at SCALE,
// the way a browser on a scaled display draws it, so a picture is
// WIDTH * SCALE = 1920 pixels wide.
const WIDTH = 1280;
const HEIGHT = 720;
const SCALE = 1.5;
const QUALITY = 75;
const TIMEOUT_MS = 30000;
const SCHEMES = ['light', 'dark'];

const [base, uploadId, category, outDir] = process.argv.slice(2);
if (!base || !uploadId || !category || !outDir) {
  console.error(
    'usage: node capture-screenshots.mjs BASE_URL UPLOAD_ID ' +
      'CATEGORY OUT_DIR',
  );
  process.exit(2);
}

const SHOTS = [
  {
    name: 'console-front-page',
    url: `${base}/`,
    // The list is filled in by a script after load; three rows is
    // what the script uploads.
    ready:
      "document.querySelectorAll('#pg-uploads-tbody tr " +
      "a.pg-list__host').length >= 3",
    height: HEIGHT,
  },
  {
    name: 'console-assessment',
    url: `${base}/upload?id=${encodeURIComponent(uploadId)}`,
    // The database section replaces its own container when it
    // renders, so readiness is read from the page as a whole.
    ready:
      "document.querySelectorAll('#pg-categories .pg-category')" +
      '.length === 5 && ' +
      "!!document.querySelector('#pg-snapshot-body .pg-kv') && " +
      "!document.body.textContent.includes('Loading')",
    // A square from the top of the page.
    height: WIDTH,
    prepare: `(() => {
      const card = [
        ...document.querySelectorAll('#pg-categories .pg-category'),
      ].find(
        (d) =>
          d.querySelector('.pg-category__title')?.textContent.trim() ===
          ${JSON.stringify(category)},
      );
      if (!card) return false;
      card.open = true;
      return true;
    })()`,
  },
];

function findChrome() {
  if (process.env.CHROME) return process.env.CHROME;
  const names = [
    'chromium',
    'chromium-browser',
    'google-chrome',
    'google-chrome-stable',
  ];
  for (const dir of (process.env.PATH ?? '').split(delimiter)) {
    for (const name of names) {
      const path = join(dir, name);
      if (existsSync(path)) return path;
    }
  }
  throw new Error(
    'no Chromium or Chrome on PATH; set CHROME to the binary',
  );
}

// Starts the browser and resolves with the DevTools WebSocket URL it
// prints once it is listening.
function launch(chrome) {
  const proc = spawn(
    chrome,
    [
      '--headless=new',
      '--disable-gpu',
      '--no-first-run',
      '--no-default-browser-check',
      '--hide-scrollbars',
      '--remote-debugging-port=0',
      'about:blank',
    ],
    { stdio: ['ignore', 'ignore', 'pipe'] },
  );
  const url = new Promise((resolve, reject) => {
    let seen = '';
    const timer = setTimeout(
      () => reject(new Error('the browser did not start')),
      TIMEOUT_MS,
    );
    proc.stderr.on('data', (chunk) => {
      seen += chunk;
      const match = /DevTools listening on (ws:\/\/\S+)/.exec(seen);
      if (match) {
        clearTimeout(timer);
        resolve(match[1]);
      }
    });
    proc.on('exit', (code) => {
      clearTimeout(timer);
      reject(new Error(`the browser exited with status ${code}`));
    });
  });
  return { proc, url };
}

class DevTools {
  constructor(url) {
    this.socket = new WebSocket(url);
    this.nextId = 0;
    this.pending = new Map();
  }

  async open() {
    await new Promise((resolve, reject) => {
      this.socket.onopen = resolve;
      this.socket.onerror = () =>
        reject(new Error('could not reach the browser'));
    });
    this.socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      const waiter = this.pending.get(message.id);
      if (!waiter) return;
      this.pending.delete(message.id);
      if (message.error)
        waiter.reject(new Error(message.error.message));
      else waiter.resolve(message.result);
    };
  }

  send(method, params = {}, sessionId = undefined) {
    const id = ++this.nextId;
    this.socket.send(JSON.stringify({ id, method, params, sessionId }));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
  }

  close() {
    this.socket.close();
  }
}

async function evaluate(page, expression) {
  const { result, exceptionDetails } = await page('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (exceptionDetails) {
    throw new Error(`page script failed: ${exceptionDetails.text}`);
  }
  return result.value;
}

async function waitFor(page, expression, what) {
  const deadline = Date.now() + TIMEOUT_MS;
  while (Date.now() < deadline) {
    if ((await evaluate(page, expression)) === true) return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`${what} did not finish rendering`);
}

// Opens SHOT in SCHEME, ready to capture.
async function open(page, shot, scheme) {
  await page('Emulation.setDeviceMetricsOverride', {
    width: WIDTH,
    height: shot.height,
    deviceScaleFactor: SCALE,
    mobile: false,
  });
  await page('Emulation.setEmulatedMedia', {
    features: [{ name: 'prefers-color-scheme', value: scheme }],
  });
  await page('Page.navigate', { url: shot.url });
  await waitFor(page, shot.ready, shot.name);
  if (shot.prepare && (await evaluate(page, shot.prepare)) !== true) {
    throw new Error(`${shot.name}: the ${category} card is missing`);
  }
  await evaluate(page, 'document.fonts.ready.then(() => true)');
  // One frame for the layout that opening a card causes.
  await evaluate(
    page,
    'new Promise((r) => requestAnimationFrame(() => r(true)))',
  );
}

// Captures the top of SHOT's page, WIDTH by its height, in every
// scheme.
async function capture(page, shot) {
  for (const scheme of SCHEMES) {
    await open(page, shot, scheme);
    const { data } = await page('Page.captureScreenshot', {
      format: 'jpeg',
      quality: QUALITY,
      clip: { x: 0, y: 0, width: WIDTH, height: shot.height, scale: 1 },
    });
    const path = join(outDir, `${shot.name}-${scheme}.jpg`);
    await writeFile(path, Buffer.from(data, 'base64'));
    console.log(`wrote ${path}: ${WIDTH * SCALE}x${shot.height * SCALE}`);
  }
}

const { proc, url } = launch(findChrome());
let tools;
try {
  tools = new DevTools(await url);
  await tools.open();
  const { targetId } = await tools.send('Target.createTarget', {
    url: 'about:blank',
  });
  const { sessionId } = await tools.send('Target.attachToTarget', {
    targetId,
    flatten: true,
  });
  const page = (method, params) =>
    tools.send(method, params, sessionId);
  await page('Page.enable');
  for (const shot of SHOTS) {
    await capture(page, shot);
  }
} catch (error) {
  console.error(`capture-screenshots: ${error.message}`);
  process.exitCode = 1;
} finally {
  // Closing through the protocol also works where the binary is a
  // wrapper, such as a snap, whose process cannot be signalled.
  await tools?.send('Browser.close').catch(() => {});
  tools?.close();
  try {
    proc.kill();
  } catch {
    // Already gone, or not ours to signal.
  }
}
