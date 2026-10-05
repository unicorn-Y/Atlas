// electron-builder afterPack hook: write the Atlas icon into Atlas.exe.
//
// `signAndEditExecutable` is off (electron-builder's resource editing pulls the winCodeSign
// bundle, whose symlinks fail to extract on a normal Windows account), which also skipped
// the icon: the exe and every shortcut showed Electron's default icon. resedit is pure JS
// (already installed with electron-builder), so the icon is embedded here instead.
const fs = require('node:fs');
const path = require('node:path');
const ResEdit = require('resedit');

exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== 'win32') return;
  const exePath = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.exe`);
  const icoPath = path.join(context.packager.projectDir, 'assets', 'icon', 'icon.ico');
  const exe = ResEdit.NtExecutable.from(fs.readFileSync(exePath), { ignoreCert: true });
  const resources = ResEdit.NtExecutableResource.from(exe);
  const icons = ResEdit.Data.IconFile.from(fs.readFileSync(icoPath)).icons.map((item) => item.data);
  const groups = ResEdit.Resource.IconGroupEntry.fromEntries(resources.entries);
  const target = groups[0] ?? { id: 1, lang: 1033 };
  ResEdit.Resource.IconGroupEntry.replaceIconsForResource(resources.entries, target.id, target.lang, icons);
  resources.outputResource(exe);
  fs.writeFileSync(exePath, Buffer.from(exe.generate()));
  console.log(`  • embedded Atlas icon into ${path.basename(exePath)} (${icons.length} sizes)`);
};
