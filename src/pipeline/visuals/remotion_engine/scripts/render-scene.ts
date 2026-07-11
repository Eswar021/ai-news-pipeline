import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";

type Args = {
  spec: string;
  out: string;
};

const parseArgs = (): Args => {
  const args = process.argv.slice(2);
  const parsed: Record<string, string> = {};
  for (let index = 0; index < args.length; index += 2) {
    const key = args[index]?.replace(/^--/, "");
    const value = args[index + 1];
    if (key && value) parsed[key] = value;
  }
  if (!parsed.spec || !parsed.out) {
    console.error("Usage: npm run render-scene -- --spec <scene.json> --out <scene.mp4>");
    process.exit(1);
  }
  return { spec: parsed.spec, out: parsed.out };
};

const run = async () => {
  const args = parseArgs();
  const specPath = path.resolve(args.spec);
  const outputPath = path.resolve(args.out);
  const sceneSpec = JSON.parse(fs.readFileSync(specPath, "utf-8"));
  const publicDir = fs.mkdtempSync(path.join(os.tmpdir(), "pipeline-remotion-public-"));
  try {
    prepareRuntimeAsset(sceneSpec, publicDir);
    const fps = Number(sceneSpec.fps || 30);
    const durationInFrames = Math.max(30, Math.round(Number(sceneSpec.duration_seconds || 6) * fps));
    fs.mkdirSync(path.dirname(outputPath), { recursive: true });

    const serveUrl = await bundle({
      entryPoint: path.join(process.cwd(), "src", "index.tsx"),
      publicDir
    });
    const composition = await selectComposition({
      serveUrl,
      id: "VisualScene",
      inputProps: { sceneSpec }
    });

    const renderOptions: any = {
      serveUrl,
      composition: {
        ...composition,
        width: Number(sceneSpec.width || composition.width),
        height: Number(sceneSpec.height || composition.height),
        fps,
        durationInFrames
      },
      codec: sceneSpec.codec || "h264",
      outputLocation: outputPath,
      inputProps: { sceneSpec }
    };

    if (sceneSpec.crf !== null && sceneSpec.crf !== undefined) {
      renderOptions.crf = Number(sceneSpec.crf);
    }
    if (sceneSpec.video_bitrate) {
      renderOptions.videoBitrate = String(sceneSpec.video_bitrate);
    }
    if (sceneSpec.x264_preset) {
      renderOptions.x264Preset = String(sceneSpec.x264_preset);
    }
    if (sceneSpec.pixel_format) {
      renderOptions.pixelFormat = String(sceneSpec.pixel_format);
    }

    await renderMedia(renderOptions);
  } finally {
    fs.rmSync(publicDir, { recursive: true, force: true });
  }
};

const prepareRuntimeAsset = (sceneSpec: any, publicDir: string) => {
  const asset = sceneSpec?.scene?.resolved_asset;
  if (!asset || asset.asset_type !== "broll_video" || !asset.asset_path) {
    return;
  }
  const sourcePath = path.resolve(String(asset.asset_path));
  if (!fs.existsSync(sourcePath)) {
    throw new Error(`B-roll asset does not exist: ${sourcePath}`);
  }
  const extension = path.extname(sourcePath) || ".mp4";
  const sceneId = String(sceneSpec?.scene?.scene_id || "scene").replace(/[^a-zA-Z0-9_-]/g, "_");
  const filename = `${sceneId}${extension}`;
  fs.copyFileSync(sourcePath, path.join(publicDir, filename));
  asset.asset_public_path = filename;
};

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
