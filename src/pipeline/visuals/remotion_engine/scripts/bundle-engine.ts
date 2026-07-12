import fs from "node:fs";
import path from "node:path";
import {bundle} from "@remotion/bundler";

type Args = {
  out: string;
  publicDir: string;
};

const parseArgs = (): Args => {
  const args = process.argv.slice(2);
  const parsed: Record<string, string> = {};
  for (let index = 0; index < args.length; index += 2) {
    const key = args[index]?.replace(/^--/, "");
    const value = args[index + 1];
    if (key && value) parsed[key] = value;
  }
  if (!parsed.out || !parsed["public-dir"]) {
    console.error("Usage: npm run bundle-engine -- --public-dir <dir> --out <bundle-dir>");
    process.exit(1);
  }
  return {out: parsed.out, publicDir: parsed["public-dir"]};
};

const run = async () => {
  const args = parseArgs();
  const outDir = path.resolve(args.out);
  const publicDir = path.resolve(args.publicDir);
  fs.rmSync(outDir, {recursive: true, force: true});
  fs.mkdirSync(publicDir, {recursive: true});
  await bundle({
    entryPoint: path.join(process.cwd(), "src", "index.tsx"),
    outDir,
    publicDir,
  });
  if (!fs.existsSync(path.join(outDir, "index.html"))) {
    throw new Error(`Remotion bundle did not create index.html under ${outDir}`);
  }
  console.log(outDir);
};

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
