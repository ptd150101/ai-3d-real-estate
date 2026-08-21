import fs from "node:fs";

const reportPath = process.argv[2];
if (!reportPath) {
  console.error("Usage: node scripts/check-mobile-audit.mjs <npm-audit.json>");
  process.exit(2);
}

const report = JSON.parse(fs.readFileSync(reportPath, "utf8"));
const vulnerabilities = report.vulnerabilities ?? {};

// image-size currently has no patched npm release for these two advisories.
// Keep this allowlist advisory-specific so any new HIGH/CRITICAL finding still fails CI.
const allowedAdvisories = new Set([
  "GHSA-w3rx-r6r6-pgpr",
  "GHSA-5p2g-fcmc-qvqq",
]);

// npm reports these two as meta-vulnerabilities that only inherit the image-size finding,
// but omits the advisory object entirely. Allow them only while they have no advisory ID;
// a future direct advisory on either package will still fail below.
const allowedEmptyMetaPackages = new Set([
  "metro-config",
  "metro-transform-worker",
]);

const highSeverities = new Set(["high", "critical"]);
const memo = new Map();

function advisoryIdsFor(packageName, stack = new Set()) {
  if (memo.has(packageName)) return memo.get(packageName);
  if (stack.has(packageName)) return new Set();

  const nextStack = new Set(stack);
  nextStack.add(packageName);
  const entry = vulnerabilities[packageName];
  const ids = new Set();

  for (const via of entry?.via ?? []) {
    if (typeof via === "string") {
      for (const id of advisoryIdsFor(via, nextStack)) ids.add(id);
      continue;
    }

    const url = String(via?.url ?? "");
    const match = url.match(/GHSA-[A-Za-z0-9-]+/);
    if (match) {
      ids.add(match[0]);
    } else {
      ids.add(`unknown:${via?.source ?? via?.name ?? packageName}`);
    }
  }

  memo.set(packageName, ids);
  return ids;
}

const blocked = [];
const allowed = [];

for (const [packageName, entry] of Object.entries(vulnerabilities)) {
  if (!highSeverities.has(entry.severity)) continue;

  const advisoryIds = advisoryIdsFor(packageName);
  const unsupported = [...advisoryIds].filter((id) => !allowedAdvisories.has(id));
  const allowedEmptyMeta = advisoryIds.size === 0 && allowedEmptyMetaPackages.has(packageName);

  if ((!allowedEmptyMeta && advisoryIds.size === 0) || unsupported.length > 0) {
    blocked.push({
      packageName,
      severity: entry.severity,
      advisories: [...advisoryIds],
    });
  } else {
    allowed.push({
      packageName,
      severity: entry.severity,
      advisories: [...advisoryIds],
      metaOnly: allowedEmptyMeta,
    });
  }
}

if (blocked.length > 0) {
  console.error("Unapproved HIGH/CRITICAL mobile dependency vulnerabilities:");
  console.error(JSON.stringify(blocked, null, 2));
  process.exit(1);
}

if (allowed.length > 0) {
  console.warn("Allowed upstream-unfixed mobile advisories:");
  console.warn(JSON.stringify(allowed, null, 2));
}

console.log("Mobile dependency audit passed.");
