import fs from "node:fs";
import path from "node:path";
import {openBrowser, renderMedia, selectComposition} from "@remotion/renderer";

type BatchJob = {spec: string; out: string};
type Args = {manifest: string; serveUrl: string; results: string};

const parseArgs = (): Args => {
  const values: Record<string, string> = {};
  const args = process.argv.slice(2);
  for (let index = 0; index < args.length; index += 2) {
    const key = args[index]?.replace(/^--/, "");
    const value = args[index + 1];
    if (key && value) values[key] = value;
  }
  if (!values.manifest || !values["serve-url"] || !values.results) {
    throw new Error(
      "Usage: npm run render-batch -- --manifest <jobs.json> --serve-url <bundle> --results <results.json>",
    );
  }
  return {
    manifest: values.manifest,
    serveUrl: values["serve-url"],
    results: values.results,
  };
};

const renderOne = async (
  job: BatchJob,
  serveUrl: string,
  browser: Awaited<ReturnType<typeof openBrowser>>,
) => {
  const started = Date.now();
  const specPath = path.resolve(job.spec);
  const outputPath = path.resolve(job.out);
  const sceneSpec = JSON.parse(fs.readFileSync(specPath, "utf-8"));
  const fps = Number(sceneSpec.fps || 30);
  const durationInFrames = Math.max(
    30,
    Math.round(Number(sceneSpec.duration_seconds || 6) * fps),
  );
  fs.mkdirSync(path.dirname(outputPath), {recursive: true});
  const composition = await selectComposition({
    serveUrl,
    id: "VisualScene",
    inputProps: {sceneSpec},
    puppeteerInstance: browser,
  });
  const renderOptions: any = {
    serveUrl,
    composition: {
      ...composition,
      width: Number(sceneSpec.width || composition.width),
      height: Number(sceneSpec.height || composition.height),
      fps,
      durationInFrames,
    },
    codec: sceneSpec.codec || "h264",
    outputLocation: outputPath,
    inputProps: {sceneSpec},
    overwrite: true,
    puppeteerInstance: browser,
    // Keep intermediate clips video-only; assembly owns the episode audio.
    muted: true,
  };
  if (sceneSpec.render_concurrency !== null && sceneSpec.render_concurrency !== undefined) {
    renderOptions.concurrency = Number(sceneSpec.render_concurrency);
  }
  if (sceneSpec.crf !== null && sceneSpec.crf !== undefined) {
    renderOptions.crf = Number(sceneSpec.crf);
  }
  if (sceneSpec.video_bitrate) renderOptions.videoBitrate = String(sceneSpec.video_bitrate);
  if (sceneSpec.x264_preset) renderOptions.x264Preset = String(sceneSpec.x264_preset);
  if (sceneSpec.pixel_format) renderOptions.pixelFormat = String(sceneSpec.pixel_format);
  if (sceneSpec.hardware_acceleration) {
    renderOptions.hardwareAcceleration = String(sceneSpec.hardware_acceleration);
  }
  await renderMedia(renderOptions);
  return {status: "rendered", elapsed_seconds: (Date.now() - started) / 1000};
};

const run = async () => {
  const args = parseArgs();
  const manifest = JSON.parse(fs.readFileSync(path.resolve(args.manifest), "utf-8"));
  const jobs: BatchJob[] = Array.isArray(manifest.jobs) ? manifest.jobs : [];
  const serveUrl = path.resolve(args.serveUrl);
  const browser = await openBrowser("chrome");
  const results: Array<Record<string, unknown>> = [];
  try {
    for (const job of jobs) {
      try {
        const result = await renderOne(job, serveUrl, browser);
        results.push({...job, ...result});
      } catch (error) {
        results.push({
          ...job,
          status: "failed",
          error: error instanceof Error ? error.stack || error.message : String(error),
        });
      }
    }
  } finally {
    await browser.close({silent: true});
  }
  fs.mkdirSync(path.dirname(path.resolve(args.results)), {recursive: true});
  fs.writeFileSync(path.resolve(args.results), JSON.stringify({results}, null, 2));
};

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
