#!/usr/bin/env node
/*
  Validate a workflow YAML file using the repo's Node dependency `yaml`.
  Output JSON only (no secrets).

  Prints: {"ok":true,"id":"..."} or {"ok":false,"error":"..."}
*/

const fs = require("fs");
const YAML = require("yaml");

function main() {
  const p = process.argv[2];
  if (!p) {
    process.stdout.write(JSON.stringify({ ok: false, error: "missing_path" }) + "\n");
    return 0;
  }
  let txt = "";
  try {
    txt = fs.readFileSync(p, "utf8");
  } catch (e) {
    process.stdout.write(JSON.stringify({ ok: false, error: "read_failed" }) + "\n");
    return 0;
  }
  let obj;
  try {
    obj = YAML.parse(txt);
  } catch (e) {
    process.stdout.write(JSON.stringify({ ok: false, error: "yaml_parse_failed" }) + "\n");
    return 0;
  }
  let id = "";
  if (obj && typeof obj === "object" && typeof obj.id === "string") {
    id = obj.id.trim();
  }
  process.stdout.write(JSON.stringify({ ok: true, id }) + "\n");
  return 0;
}

process.exit(main());

