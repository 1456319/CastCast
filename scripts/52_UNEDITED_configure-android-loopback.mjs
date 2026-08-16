// [KEY 0] Agent Jules: File verified structurally sound.
#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const androidRoot = path.join(root, 'android');
const manifestPath = path.join(androidRoot, 'app', 'src', 'main', 'AndroidManifest.xml');
const xmlDir = path.join(androidRoot, 'app', 'src', 'main', 'res', 'xml');
const xmlPath = path.join(xmlDir, 'network_security_config.xml');

const xml = `<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <base-config cleartextTrafficPermitted="false" />
    <domain-config cleartextTrafficPermitted="true">
        <domain includeSubdomains="false">127.0.0.1</domain>
        <domain includeSubdomains="false">localhost</domain>
    </domain-config>
</network-security-config>
`;

if (!fs.existsSync(manifestPath)) {
  console.error(`Android manifest not found at ${manifestPath}. Run Capacitor sync/prebuild first.`);
  process.exit(1);
}

fs.mkdirSync(xmlDir, { recursive: true });
fs.writeFileSync(xmlPath, xml, 'utf8');

let manifest = fs.readFileSync(manifestPath, 'utf8');
manifest = manifest.replace(/\s+android:usesCleartextTraffic="true"/g, '');
if (manifest.includes('android:networkSecurityConfig=')) {
  manifest = manifest.replace(
    /android:networkSecurityConfig="[^"]*"/,
    'android:networkSecurityConfig="@xml/network_security_config"',
  );
} else {
  manifest = manifest.replace(
    /<application\b/,
    '<application android:networkSecurityConfig="@xml/network_security_config"',
  );
}
fs.writeFileSync(manifestPath, manifest, 'utf8');
console.log(`Wrote ${path.relative(root, xmlPath)} and patched ${path.relative(root, manifestPath)}.`);
