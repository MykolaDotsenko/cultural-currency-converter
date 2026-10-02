import { readdir, readFile } from "node:fs/promises";
import { extname, join, relative, resolve } from "node:path";

const STYLE_ROOT = resolve(process.cwd(), "src/styles");

async function collectCssFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await collectCssFiles(path)));
    } else if (entry.isFile() && extname(entry.name) === ".css") {
      files.push(path);
    }
  }

  return files.sort();
}

const files = await collectCssFiles(STYLE_ROOT);
const defined = new Set();
const uses = [];

for (const file of files) {
  const css = await readFile(file, "utf8");

  for (const match of css.matchAll(/(--[a-z0-9-]+)\s*:/gi)) {
    defined.add(match[1]);
  }

  const lines = css.split("\n");
  lines.forEach((line, index) => {
    for (const match of line.matchAll(/var\(\s*(--[a-z0-9-]+)/gi)) {
      uses.push({
        name: match[1],
        file: relative(process.cwd(), file),
        line: index + 1,
      });
    }
  });
}

const unresolved = uses.filter(({ name }) => !defined.has(name));

if (unresolved.length > 0) {
  console.error("Undefined CSS custom properties detected:");
  for (const item of unresolved) {
    console.error(`- ${item.name} at ${item.file}:${item.line}`);
  }
  process.exitCode = 1;
} else {
  console.log(
    `CSS custom-property contract ok: ${defined.size} definitions, ${uses.length} uses across ${files.length} files.`,
  );
}
