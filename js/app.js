/* ============================================================
 * Image & Video Generator
 * Images: free Pollinations.ai API (no key, no usage limits)
 * Videos: rendered entirely in the browser (canvas + MediaRecorder)
 * ============================================================ */

"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

/* ---------------- Tabs ---------------- */
$$(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".tab-btn").forEach((b) => b.classList.remove("active"));
    $$(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $("#tab-" + btn.dataset.tab).classList.add("active");
  });
});

/* ---------------- Gallery state ---------------- */
/** @type {{id:number, url:string, prompt:string, seed:number, selected:boolean}[]} */
const gallery = [];
let nextId = 1;

function updateGalleryCount() {
  $("#gallery-count").textContent = gallery.length;
}

function buildImageUrl(prompt, { width, height, seed, model, enhance }) {
  const params = new URLSearchParams({
    width: String(width),
    height: String(height),
    seed: String(seed),
    model,
    nologo: "true",
    enhance: enhance ? "true" : "false",
  });
  return `https://image.pollinations.ai/prompt/${encodeURIComponent(prompt)}?${params}`;
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Image failed to load"));
    img.src = url;
  });
}

async function downloadUrl(url, filename) {
  try {
    const res = await fetch(url);
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  } catch {
    window.open(url, "_blank"); // fallback
  }
}

function safeName(prompt, seed) {
  const slug = prompt.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 50);
  return `${slug || "image"}-${seed}.jpg`;
}

/* ---------------- Lightbox ---------------- */
function openLightbox(item) {
  $("#lightbox-img").src = item.url;
  const dl = $("#lightbox-download");
  dl.onclick = (e) => {
    e.preventDefault();
    downloadUrl(item.url, safeName(item.prompt, item.seed));
  };
  $("#lightbox").hidden = false;
}
$("#lightbox-close").addEventListener("click", () => ($("#lightbox").hidden = true));
$("#lightbox").addEventListener("click", (e) => {
  if (e.target === $("#lightbox")) $("#lightbox").hidden = true;
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") $("#lightbox").hidden = true;
});

/* ---------------- Gallery rendering ---------------- */
function renderGallery() {
  const grid = $("#gallery-grid");
  grid.innerHTML = "";
  for (const item of gallery) {
    const div = document.createElement("div");
    div.className = "thumb" + (item.selected ? " selected" : "");
    div.title = item.prompt;
    const img = document.createElement("img");
    img.src = item.url;
    img.alt = item.prompt;
    img.loading = "lazy";
    div.appendChild(img);
    div.addEventListener("click", () => {
      item.selected = !item.selected;
      div.classList.toggle("selected", item.selected);
    });
    div.addEventListener("dblclick", () => openLightbox(item));
    grid.appendChild(div);
  }
  updateGalleryCount();
}

$("#btn-select-all").addEventListener("click", () => {
  gallery.forEach((i) => (i.selected = true));
  renderGallery();
});
$("#btn-clear-selection").addEventListener("click", () => {
  gallery.forEach((i) => (i.selected = false));
  renderGallery();
});
$("#btn-delete-selected").addEventListener("click", () => {
  for (let i = gallery.length - 1; i >= 0; i--) {
    if (gallery[i].selected) gallery.splice(i, 1);
  }
  renderGallery();
});
$("#btn-download-selected").addEventListener("click", async () => {
  const selected = gallery.filter((i) => i.selected);
  for (const item of selected) {
    await downloadUrl(item.url, safeName(item.prompt, item.seed));
  }
});

/* ---------------- Image generation ---------------- */
$("#img-preset").addEventListener("change", () => {
  $("#custom-size-row").hidden = $("#img-preset").value !== "custom";
});

function getImageSize() {
  const preset = $("#img-preset").value;
  if (preset === "custom") {
    return { width: +$("#img-width").value || 1024, height: +$("#img-height").value || 1024 };
  }
  const [w, h] = preset.split("x").map(Number);
  return { width: w, height: h };
}

$("#btn-generate-images").addEventListener("click", async () => {
  const prompt = $("#img-prompt").value.trim();
  if (!prompt) {
    $("#img-status").textContent = "Enter a prompt first.";
    return;
  }

  const { width, height } = getImageSize();
  const model = $("#img-model").value;
  const enhance = $("#img-enhance").checked;
  const count = Math.max(1, Math.min(12, +$("#img-count").value || 1));
  const baseSeed = $("#img-seed").value
    ? +$("#img-seed").value
    : Math.floor(Math.random() * 1e9);

  const btn = $("#btn-generate-images");
  btn.disabled = true;
  $("#img-status").textContent = `Generating ${count} image${count > 1 ? "s" : ""}…`;

  const results = $("#img-results");
  results.innerHTML = "";

  let done = 0;
  const jobs = [];
  for (let i = 0; i < count; i++) {
    const seed = baseSeed + i;
    const url = buildImageUrl(prompt, { width, height, seed, model, enhance });

    const thumb = document.createElement("div");
    thumb.className = "thumb";
    thumb.innerHTML = '<div class="spinner"></div>';
    results.appendChild(thumb);

    jobs.push(
      loadImage(url)
        .then(() => {
          const item = { id: nextId++, url, prompt, seed, selected: false };
          gallery.push(item);
          thumb.innerHTML = "";
          const img = document.createElement("img");
          img.src = url;
          img.alt = prompt;
          thumb.appendChild(img);
          thumb.addEventListener("click", () => openLightbox(item));
          renderGalleryCountOnly();
        })
        .catch(() => {
          thumb.classList.add("error");
          thumb.innerHTML = '<div class="error-msg">Failed — try again or change the prompt</div>';
        })
        .finally(() => {
          done++;
          $("#img-status").textContent = `Generated ${done}/${count}`;
        })
    );
  }

  await Promise.allSettled(jobs);
  renderGallery();
  btn.disabled = false;
  $("#img-status").textContent = `Done — ${count} image${count > 1 ? "s" : ""} added to your gallery.`;
});

function renderGalleryCountOnly() {
  updateGalleryCount();
}

/* ---------------- Video generation ---------------- */
$("#vid-mode").addEventListener("change", () => {
  const mode = $("#vid-mode").value;
  $("#vid-ai-controls").hidden = mode !== "ai-frames";
  $("#vid-slideshow-controls").hidden = mode !== "slideshow";
});

function setVideoProgress(frac, msg) {
  $("#vid-progress-wrap").hidden = false;
  $("#vid-progress").style.width = `${Math.round(frac * 100)}%`;
  if (msg !== undefined) $("#vid-status").textContent = msg;
}

/** Draw an image onto ctx with cover fit + optional pan/zoom transform. */
function drawFrame(ctx, img, W, H, effect, t, panDir) {
  let zoom = 1;
  let panX = 0;
  let panY = 0;

  if (effect === "kenburns") {
    zoom = 1.08 + 0.12 * t;
    panX = panDir.x * t * 0.08;
    panY = panDir.y * t * 0.08;
  } else if (effect === "zoom") {
    zoom = 1 + 0.15 * t;
  }

  const scale = Math.max(W / img.width, H / img.height) * zoom;
  const dw = img.width * scale;
  const dh = img.height * scale;
  const dx = (W - dw) / 2 - panX * W;
  const dy = (H - dh) / 2 - panY * H;
  ctx.drawImage(img, dx, dy, dw, dh);
}

async function renderVideo(images, opts) {
  const { width: W, height: H, fps, secondsPerFrame, effect } = opts;
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d");

  const stream = canvas.captureStream(fps);
  const mimeCandidates = [
    "video/webm;codecs=vp9",
    "video/webm;codecs=vp8",
    "video/webm",
    "video/mp4",
  ];
  const mimeType = mimeCandidates.find((m) => MediaRecorder.isTypeSupported(m)) || "";
  const recorder = new MediaRecorder(stream, {
    mimeType,
    videoBitsPerSecond: 8_000_000,
  });
  const chunks = [];
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  const stopped = new Promise((res) => (recorder.onstop = res));
  recorder.start();

  const framesPerImage = Math.round(secondsPerFrame * fps);
  const fadeFrames = Math.min(Math.round(fps * 0.5), Math.floor(framesPerImage / 2));
  const totalFrames = images.length * framesPerImage;
  const frameDuration = 1000 / fps;

  // Random but stable pan direction per image, for Ken Burns variety
  const panDirs = images.map((_, i) => ({
    x: (i % 2 === 0 ? 1 : -1) * (0.5 + Math.random() * 0.5),
    y: (i % 3 === 0 ? 1 : -1) * (0.3 + Math.random() * 0.5),
  }));

  let frame = 0;
  let last = performance.now();
  for (let i = 0; i < images.length; i++) {
    for (let f = 0; f < framesPerImage; f++) {
      const t = f / framesPerImage;
      ctx.fillStyle = "#000";
      ctx.fillRect(0, 0, W, H);
      ctx.globalAlpha = 1;
      drawFrame(ctx, images[i], W, H, effect, t, panDirs[i]);

      // Crossfade into the next image at the end of each segment
      if (i < images.length - 1 && f >= framesPerImage - fadeFrames) {
        const ft = (f - (framesPerImage - fadeFrames)) / fadeFrames;
        ctx.globalAlpha = ft;
        drawFrame(ctx, images[i + 1], W, H, effect, 0, panDirs[i + 1]);
        ctx.globalAlpha = 1;
      }

      frame++;
      setVideoProgress(frame / totalFrames, `Rendering frame ${frame}/${totalFrames}…`);

      // Pace rendering in real time so MediaRecorder captures every frame
      const elapsed = performance.now() - last;
      const wait = Math.max(0, frameDuration - elapsed);
      await new Promise((r) => setTimeout(r, wait));
      last = performance.now();
    }
  }

  recorder.stop();
  await stopped;
  return new Blob(chunks, { type: mimeType || "video/webm" });
}

$("#btn-generate-video").addEventListener("click", async () => {
  const btn = $("#btn-generate-video");
  const mode = $("#vid-mode").value;
  const [W, H] = $("#vid-res").value.split("x").map(Number);
  const fps = +$("#vid-fps").value;
  const secondsPerFrame = +$("#vid-seconds-per").value || 2;
  const effect = $("#vid-effect").value;

  btn.disabled = true;
  $("#vid-preview").hidden = true;
  $("#vid-download").hidden = true;

  try {
    let images = [];

    if (mode === "ai-frames") {
      const prompt = $("#vid-prompt").value.trim();
      if (!prompt) {
        setVideoProgress(0, "Enter a prompt first.");
        btn.disabled = false;
        return;
      }
      const nFrames = Math.max(2, Math.min(30, +$("#vid-frames").value || 6));
      const model = $("#vid-model").value;
      const baseSeed = Math.floor(Math.random() * 1e9);

      setVideoProgress(0, `Generating ${nFrames} keyframes…`);
      let loaded = 0;
      images = await Promise.all(
        Array.from({ length: nFrames }, (_, i) => {
          const url = buildImageUrl(prompt, {
            width: W,
            height: H,
            seed: baseSeed + i,
            model,
            enhance: true,
          });
          return loadImage(url).then((img) => {
            loaded++;
            setVideoProgress((loaded / nFrames) * 0.5, `Keyframe ${loaded}/${nFrames} ready…`);
            return img;
          });
        })
      );
    } else {
      const source = gallery.filter((i) => i.selected).length
        ? gallery.filter((i) => i.selected)
        : gallery;
      if (!source.length) {
        setVideoProgress(0, "Your gallery is empty — generate some images first.");
        btn.disabled = false;
        return;
      }
      setVideoProgress(0.1, `Loading ${source.length} gallery images…`);
      images = await Promise.all(source.map((i) => loadImage(i.url)));
    }

    const blob = await renderVideo(images, { width: W, height: H, fps, secondsPerFrame, effect });

    const url = URL.createObjectURL(blob);
    const preview = $("#vid-preview");
    preview.src = url;
    preview.hidden = false;
    $("#vid-placeholder").style.display = "none";

    const ext = blob.type.includes("mp4") ? "mp4" : "webm";
    const dl = $("#vid-download");
    dl.href = url;
    dl.download = `generated-video.${ext}`;
    dl.hidden = false;

    setVideoProgress(1, "Done! Preview your video or download it.");
  } catch (err) {
    setVideoProgress(0, `Error: ${err.message}. Try fewer frames or a smaller resolution.`);
  } finally {
    btn.disabled = false;
  }
});
