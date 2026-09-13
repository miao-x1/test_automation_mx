const SKIP_DIRS = new Set([
  '.git', 'node_modules', 'dist', 'build', 'venv', '.venv', '__pycache__',
  '.next', 'coverage', 'vendor', '.idea', '.vscode', 'target', 'bin', 'obj',
]);

const MAX_ZIP = 40 * 1024 * 1024;
const MAX_FILE = 5 * 1024 * 1024;

function crc32(data: Uint8Array): number {
  let crc = 0xffffffff;
  for (let i = 0; i < data.length; i += 1) {
    crc ^= data[i];
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function put32(view: DataView, offset: number, value: number) {
  view.setUint32(offset, value, true);
}

function put16(view: DataView, offset: number, value: number) {
  view.setUint16(offset, value, true);
}

function shouldSkip(rel: string): boolean {
  return rel.split(/[/\\]/).some((part) => SKIP_DIRS.has(part));
}

function folderNameOf(files: File[]): string {
  const rel = files[0]?.webkitRelativePath || '';
  return rel.split(/[/\\]/)[0] || 'project';
}

function buildZip(entries: { path: string; data: Uint8Array }[]): Blob {
  const chunks: Uint8Array[] = [];
  const centrals: Uint8Array[] = [];
  let offset = 0;

  entries.forEach((entry) => {
    const name = new TextEncoder().encode(entry.path);
    const crc = crc32(entry.data);
    const local = new Uint8Array(30 + name.length);
    const localView = new DataView(local.buffer);
    put32(localView, 0, 0x04034b50);
    put16(localView, 4, 20);
    put16(localView, 6, 0x0800);
    put16(localView, 8, 0);
    put16(localView, 10, 0);
    put16(localView, 12, 0);
    put32(localView, 14, crc);
    put32(localView, 18, entry.data.length);
    put32(localView, 22, entry.data.length);
    put16(localView, 26, name.length);
    put16(localView, 28, 0);
    local.set(name, 30);
    chunks.push(local, entry.data);

    const central = new Uint8Array(46 + name.length);
    const centralView = new DataView(central.buffer);
    put32(centralView, 0, 0x02014b50);
    put16(centralView, 4, 20);
    put16(centralView, 6, 20);
    put16(centralView, 8, 0x0800);
    put16(centralView, 10, 0);
    put16(centralView, 12, 0);
    put16(centralView, 14, 0);
    put32(centralView, 16, crc);
    put32(centralView, 20, entry.data.length);
    put32(centralView, 24, entry.data.length);
    put16(centralView, 28, name.length);
    put16(centralView, 30, 0);
    put16(centralView, 32, 0);
    put16(centralView, 34, 0);
    put16(centralView, 36, 0);
    put32(centralView, 38, 0);
    put32(centralView, 42, offset);
    central.set(name, 46);
    centrals.push(central);
    offset += local.length + entry.data.length;
  });

  const centralSize = centrals.reduce((sum, item) => sum + item.length, 0);
  const end = new Uint8Array(22);
  const endView = new DataView(end.buffer);
  put32(endView, 0, 0x06054b50);
  put16(endView, 8, entries.length);
  put16(endView, 10, entries.length);
  put32(endView, 12, centralSize);
  put32(endView, 16, offset);
  put16(endView, 20, 0);

  return new Blob([...chunks, ...centrals, end], { type: 'application/zip' });
}

export async function zipPickedFolder(files: FileList | File[]): Promise<File> {
  const picked = Array.from(files);
  const name = `${folderNameOf(picked)}.zip`;
  const entries: { path: string; data: Uint8Array }[] = [];

  for (const file of picked) {
    const rel = (file.webkitRelativePath || file.name).replace(/\\/g, '/');
    if (!rel || shouldSkip(rel) || file.size > MAX_FILE) continue;
    entries.push({ path: rel, data: new Uint8Array(await file.arrayBuffer()) });
  }

  if (!entries.length) throw new Error('这个文件夹里没有可导入的文件');
  const blob = buildZip(entries);
  if (blob.size > MAX_ZIP) throw new Error('打包后超过 40MB，请去掉依赖目录后再试');
  return new File([blob], name, { type: 'application/zip' });
}

export function pickedFolderName(files: FileList | File[]): string {
  return folderNameOf(Array.from(files));
}
