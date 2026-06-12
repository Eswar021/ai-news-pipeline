import fs from "node:fs";
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
  const fps = Number(sceneSpec.fps || 30);
  const durationInFrames = Math.max(30, Math.round(Number(sceneSpec.duration_seconds || 6) * fps));
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });

  const serveUrl = await bundle({
    entryPoint: path.join(process.cwd(), "src", "index.tsx")
  });
  const composition = await selectComposition({
    serveUrl,
    id: "VisualScene",
    inputProps: { sceneSpec }
  });

  await renderMedia({
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
  });
};

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
