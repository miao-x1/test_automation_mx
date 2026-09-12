import { useCallback, useEffect, useState } from 'react';
import { Button, Input, Table, Tag, Typography, message } from 'antd';
import { getCurrentProjectId, PROJECT_CHANGED } from './projectStore';
import {
  askProjectAgentFromAnywhere,
  PROJECT_MEMORY_CHANGED,
  fetchProjectIndex,
  fetchProjectMemory,
  fetchProjectOverview,
  importGithubRepo,
  importSampleRepo,
  type CodeHit,
} from '@/services/projectExplorer';

const { Title, Paragraph, Text } = Typography;

export default function ProjectUnderstandPage() {
  const [repoUrl, setRepoUrl] = useState('');
  const [overview, setOverview] = useState<any>(null);
  const [files, setFiles] = useState<CodeHit[]>([]);
  const [symbols, setSymbols] = useState<CodeHit[]>([]);
  const [memory, setMemory] = useState<any>(null);
  const [keyword, setKeyword] = useState('');
  const [quick, setQuick] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    const [ov, fileRows, symbolRows, mem] = await Promise.all([
      fetchProjectOverview(projectId),
      fetchProjectIndex(projectId, { kind: 'file' }),
      fetchProjectIndex(projectId, { keyword: keyword || undefined }),
      fetchProjectMemory(projectId),
    ]);
    setOverview(ov);
    setFiles(Array.isArray(fileRows) ? fileRows : []);
    setSymbols((Array.isArray(symbolRows) ? symbolRows : []).filter((item) => item.kind !== 'file' && item.kind !== 'module'));
    setMemory(mem);
  }, [keyword]);

  useEffect(() => {
    load().catch(() => undefined);
    const reload = () => { void load(); };
    window.addEventListener(PROJECT_CHANGED, reload);
    window.addEventListener(PROJECT_MEMORY_CHANGED, reload);
    return () => {
      window.removeEventListener(PROJECT_CHANGED, reload);
      window.removeEventListener(PROJECT_MEMORY_CHANGED, reload);
    };
  }, [load]);

  const importGithub = async () => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    setLoading(true);
    try {
      await importGithubRepo(projectId, repoUrl);
      message.success('已导入并建立代码索引');
      await load();
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '导入失败');
    } finally {
      setLoading(false);
    }
  };

  const importSample = async () => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    setLoading(true);
    try {
      await importSampleRepo(projectId);
      message.success('已导入示例代码并建立索引');
      await load();
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '导入失败');
    } finally {
      setLoading(false);
    }
  };

  const ov = overview?.overview || {};

  return (
    <div className="product-shell product-wide">
      <div className="product-hero">
        <p>项目理解</p>
        <Title level={2} style={{ margin: 0 }}>Codebase Explorer</Title>
        <Paragraph type="secondary">导入真实仓库后建立可复用索引。问答走右侧同一个项目 Agent，不另开聊天。</Paragraph>
      </div>

      <div className="product-card">
        <Text strong>导入 GitHub 项目</Text>
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <Input
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            placeholder="https://github.com/owner/repo"
          />
          <Button type="primary" loading={loading} onClick={() => void importGithub()}>导入并索引</Button>
          <Button loading={loading} onClick={() => void importSample()}>导入示例项目</Button>
        </div>
      </div>

      <div className="product-card">
        <Title level={4} style={{ marginTop: 0 }}>项目概览</Title>
        {overview?.imported ? (
          <div>
            <p>仓库：{overview.repo_url || overview.repo_name}</p>
            <p>文件 {overview.file_count} · 符号 {overview.symbol_count} · 分支 {overview.branch || '-'}</p>
            <div>
              {(ov.stack || []).map((item: string) => <Tag key={item}>{item}</Tag>)}
              {(ov.modules || []).slice(0, 12).map((item: string) => <Tag key={item} color="blue">{item}</Tag>)}
            </div>
            {ov.apis?.length ? <Paragraph type="secondary" style={{ marginTop: 8 }}>API：{ov.apis.slice(0, 8).join(' / ')}</Paragraph> : null}
          </div>
        ) : (
          <Paragraph type="secondary">还没有项目索引。导入 GitHub 仓库后才能做文件和函数定位。</Paragraph>
        )}
      </div>

      <div className="product-card">
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 12 }}>
          <Title level={4} style={{ margin: 0 }}>文件 / 模块 / 代码定位</Title>
          <Input.Search placeholder="搜索函数、组件、API、路径" allowClear onSearch={setKeyword} style={{ width: 280 }} />
        </div>
        <Table
          rowKey={(row) => `${row.kind}-${row.path}-${row.name}-${row.line_start}`}
          size="small"
          dataSource={symbols.slice(0, 40)}
          pagination={false}
          onRow={(row) => ({
            onClick: () => askProjectAgentFromAnywhere(`${row.name} 在哪个文件？负责什么？`),
          })}
          columns={[
            { title: '符号', dataIndex: 'name', width: 180 },
            { title: '类型', dataIndex: 'kind', width: 100 },
            { title: '文件', dataIndex: 'path' },
            { title: '行号', dataIndex: 'line_start', width: 80 },
            { title: '模块', dataIndex: 'module', width: 160 },
          ]}
        />
        <Paragraph type="secondary" style={{ marginTop: 8 }}>
          已索引文件 {files.length} 个。点击一行会把问题交给右侧项目 Agent。
        </Paragraph>
      </div>

      <div className="product-card">
        <Title level={4} style={{ marginTop: 0 }}>Project Memory</Title>
        <p>关注模块：{(memory?.focus || []).map((item: any) => item.title).join('、') || '暂无'}</p>
        <p>已确认：{(memory?.confirmed || []).map((item: any) => item.title).join('、') || '暂无'}</p>
        <p>分析结论：{(memory?.conclusions || []).map((item: any) => item.title).join('、') || '暂无'}</p>
      </div>

      <div className="project-quick-ask">
        <Input
          value={quick}
          onChange={(e) => setQuick(e.target.value)}
          placeholder="导入项目后，你可以询问任何关于这个项目的问题"
          onPressEnter={() => {
            if (quick.trim()) {
              askProjectAgentFromAnywhere(quick.trim());
              setQuick('');
            }
          }}
        />
        <Button type="primary" onClick={() => {
          if (quick.trim()) {
            askProjectAgentFromAnywhere(quick.trim());
            setQuick('');
          }
        }}>问 Agent</Button>
      </div>
    </div>
  );
}
