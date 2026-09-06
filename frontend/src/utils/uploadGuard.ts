/** 与后端 app.core.upload_security 对齐的前端上传预检。 */

export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

export const ALLOWED_UPLOAD_EXTS = new Set([
  '.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp',
  '.pdf', '.doc', '.docx',
  '.mp4', '.avi', '.mov', '.mkv',
  '.json', '.yaml', '.yml',
  '.sql', '.ddl',
]);

const CATEGORY_EXTS: Record<string, string[]> = {
  image: ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'],
  pdf: ['.pdf'],
  word: ['.doc', '.docx'],
  video: ['.mp4', '.avi', '.mov', '.mkv'],
  swagger: ['.json', '.yaml', '.yml'],
  schema: ['.sql', '.ddl'],
};

function fileExt(name: string): string {
  const i = name.lastIndexOf('.');
  if (i < 0) return '';
  return name.slice(i).toLowerCase();
}

function startsWith(bytes: Uint8Array, sig: number[]): boolean {
  if (bytes.length < sig.length) return false;
  return sig.every((b, i) => bytes[i] === b);
}

function detectCategory(bytes: Uint8Array, ext: string): string | null {
  if (startsWith(bytes, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) return 'image';
  if (startsWith(bytes, [0xff, 0xd8, 0xff])) return 'image';
  if (startsWith(bytes, [0x47, 0x49, 0x46, 0x38, 0x37, 0x61]) || startsWith(bytes, [0x47, 0x49, 0x46, 0x38, 0x39, 0x61])) return 'image';
  if (bytes.length >= 12 && bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46
      && bytes[8] === 0x57 && bytes[9] === 0x45 && bytes[10] === 0x42 && bytes[11] === 0x50) return 'image';
  if (startsWith(bytes, [0x42, 0x4d]) && ext === '.bmp') return 'image';
  if (startsWith(bytes, [0x25, 0x50, 0x44, 0x46])) return 'pdf';
  if (startsWith(bytes, [0xd0, 0xcf, 0x11, 0xe0])) return 'word';
  if (startsWith(bytes, [0x50, 0x4b]) && ext === '.docx') return 'word';
  if (bytes.length >= 8 && bytes[4] === 0x66 && bytes[5] === 0x74 && bytes[6] === 0x79 && bytes[7] === 0x70) return 'video';
  if (['.json', '.yaml', '.yml', '.sql', '.ddl'].includes(ext)) return ext === '.sql' || ext === '.ddl' ? 'schema' : 'swagger';
  return null;
}

export function formatUploadError(err: unknown): string {
  const anyErr = err as { response?: { data?: { detail?: unknown; message?: string } }; message?: string; detail?: unknown };
  const detail = anyErr?.response?.data?.detail ?? anyErr?.detail ?? anyErr?.response?.data?.message ?? anyErr?.message;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => (typeof item === 'string' ? item : JSON.stringify(item))).join('; ');
  }
  return '上传失败';
}

export async function assertUploadAllowed(file: File, category = 'auto'): Promise<void> {
  if (!file || file.size <= 0) {
    throw new Error('空文件不能上传');
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    throw new Error('文件大小超出限制（最大 10MB）');
  }

  const ext = fileExt(file.name || '');
  if (!ALLOWED_UPLOAD_EXTS.has(ext)) {
    throw new Error(`不支持的文件类型: ${ext || '无扩展名'}`);
  }

  if (category && category !== 'auto') {
    const allowed = CATEGORY_EXTS[category];
    if (allowed && !allowed.includes(ext)) {
      throw new Error('文件扩展名与声明类别不一致');
    }
  }

  const head = new Uint8Array(await file.slice(0, 16).arrayBuffer());
  const detected = detectCategory(head, ext);
  if (!detected) {
    throw new Error('文件内容与扩展名不符，已拒绝（禁止伪造扩展名）');
  }
  const mapped = CATEGORY_EXTS[detected];
  if (mapped && !mapped.includes(ext)) {
    throw new Error('文件真实类型与扩展名不一致');
  }
}
