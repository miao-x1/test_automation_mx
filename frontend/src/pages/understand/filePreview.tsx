import { getCurrentProjectId } from '@/pages/product/projectStore';
import { fetchProjectFile } from '@/services/projectExplorer';

export async function filePreviewBody(path: string) {
  const projectId = getCurrentProjectId();
  if (!projectId || !path) return <p>没有可预览的文件</p>;
  try {
    const file = await fetchProjectFile(projectId, path);
    const text = file?.content || file?.text || file?.source || file?.snippet || '';
    return <pre className="uw-code" style={{ height: 420, whiteSpace: 'pre-wrap' }}>{text || '文件是空的'}</pre>;
  } catch {
    return <p>读不到 {path}</p>;
  }
}
