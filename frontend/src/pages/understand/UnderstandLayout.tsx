import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Button, Drawer, Dropdown, Input, Modal, Popover, Space, Upload, message } from 'antd';
import { zipPickedFolder } from '@/utils/projectZip';
import { getCurrentProjectId, PROJECT_CHANGED } from '@/pages/product/projectStore';
import {
  analyzeProject,
  apiError,
  fetchProjectUnderstanding,
  importGitRepo,
  importProjectArchive,
  importSampleRepo,
  openProjectAgent,
} from '@/services/projectExplorer';
import { STATUS_TEXT, searchUnderstanding } from './understanding';
import './understand.css';

type DrawerState = { title: string; body: any } | null;

type UnderstandingState = {
  data: any;
  loading: boolean;
  reload: (refresh?: boolean) => Promise<void>;
  ask: (question: string) => void;
  openDrawer: (title: string, body: any) => void;
};

const UnderstandingContext = createContext<UnderstandingState | null>(null);

export function useUnderstanding() {
  const ctx = useContext(UnderstandingContext);
  if (!ctx) throw new Error('useUnderstanding');
  return ctx;
}

export default function UnderstandLayout() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [repoUrl, setRepoUrl] = useState('');
  const [query, setQuery] = useState('');
  const [drawer, setDrawer] = useState<DrawerState>(null);
  const folderRef = useRef<HTMLInputElement>(null);

  const status = data?.imported ? (data.status || 'partial') : 'empty';

  const reload = useCallback(async (refresh = false) => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    setLoading(true);
    try {
      setData(await fetchProjectUnderstanding(projectId, refresh));
    } catch (err: any) {
      message.error(apiError(err, '加载项目理解失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
    const onChange = () => { void reload(); };
    window.addEventListener(PROJECT_CHANGED, onChange);
    return () => window.removeEventListener(PROJECT_CHANGED, onChange);
  }, [reload]);

  const ask = (question: string) => openProjectAgent(question);

  const runAnalyze = async (mode: 'incremental' | 'full') => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    setLoading(true);
    try {
      await analyzeProject(projectId, mode);
      message.success(mode === 'full' ? '已完成全量分析' : '已完成增量分析');
      await reload(true);
    } catch (err: any) {
      message.error(apiError(err, '重新分析失败'));
    } finally {
      setLoading(false);
    }
  };

  const hits = useMemo(() => searchUnderstanding(data, query), [data, query]);

  return (
    <UnderstandingContext.Provider value={{ data, loading, reload, ask, openDrawer: (title, body) => setDrawer({ title, body }) }}>
      <div className="uw">
        <header className="uw-top">
          <Popover
            trigger="click"
            content={(
              <div style={{ width: 220, fontSize: 13, lineHeight: 1.7 }}>
                <div>最后分析：{data?.updated_at ? data.updated_at.replace('T', ' ').slice(0, 16) : '-'}</div>
                <div>文件：{data?.file_count ?? data?.scale?.files ?? 0}</div>
                <div>代码：{data?.scale?.loc ?? 0} 行</div>
                <div>索引：{data?.progress ?? 0}%</div>
              </div>
            )}
          >
            <button className="uw-status" type="button">
              <i className={`uw-dot ${status === 'ready' ? 'ok' : status === 'partial' || status === 'analyzing' ? 'warn' : 'empty'}`} />
              {STATUS_TEXT[status] || status}
            </button>
          </Popover>
          <div className="uw-search">
            <Dropdown
              trigger={['click']}
              open={query.trim().length > 0 && hits.length > 0}
              menu={{
                items: hits.map((item, index) => ({
                  key: `${item.to}-${index}`,
                  label: <div><b>{item.kind}</b>　{item.title}<div style={{ color: '#656d76' }}>{item.desc}</div></div>,
                  onClick: () => {
                    setQuery('');
                    setDrawer({
                      title: `${item.kind} · ${item.title}`,
                      body: <div><p>{item.desc || '-'}</p></div>,
                    });
                  },
                })),
              }}
            >
              <Input
                allowClear
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="搜索项目中的页面、功能、API、文件、函数……"
              />
            </Dropdown>
          </div>
          <div className="uw-actions">
            <Dropdown
              menu={{
                items: [
                  { key: 'incremental', label: '增量分析', onClick: () => void runAnalyze('incremental') },
                  { key: 'full', label: '全量分析', danger: true, onClick: () => void runAnalyze('full') },
                ],
              }}
            >
              <Button type="primary" loading={loading}>重新分析</Button>
            </Dropdown>
            <Dropdown
              menu={{
                items: [
                  { key: 'import', label: '导入项目', onClick: () => setImportOpen(true) },
                  { key: 'sample', label: '导入示例项目', onClick: () => {
                    const projectId = getCurrentProjectId();
                    if (!projectId) return;
                    setLoading(true);
                    importSampleRepo(projectId).then(() => reload()).catch((err) => message.error(apiError(err, '导入失败'))).finally(() => setLoading(false));
                  } },
                ],
              }}
            >
              <Button>导入项目</Button>
            </Dropdown>
          </div>
        </header>
        <div className="uw-main">
          <Outlet />
        </div>
      </div>

      <Modal title="导入项目" open={importOpen} onCancel={() => setImportOpen(false)} footer={null} destroyOnClose>
        <Input value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} placeholder="GitHub / GitLab / Gitee 仓库地址" style={{ marginBottom: 8 }} />
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <Button type="primary" loading={loading} onClick={async () => {
            const projectId = getCurrentProjectId();
            if (!projectId) return;
            if (!repoUrl.trim()) { message.error('请输入 Git 仓库地址'); return; }
            setLoading(true);
            try {
              await importGitRepo(projectId, repoUrl);
              message.success('已导入并完成分析');
              setImportOpen(false);
              await reload();
            } catch (err: any) {
              message.error(apiError(err, '导入失败'));
            } finally {
              setLoading(false);
            }
          }}>导入 Git 仓库</Button>
          <Space>
            <Button onClick={() => folderRef.current?.click()}>上传本地文件夹</Button>
            <Upload accept=".zip" maxCount={1} showUploadList={false} beforeUpload={async (file) => {
              const projectId = getCurrentProjectId();
              if (!projectId) return false;
              setLoading(true);
              try {
                await importProjectArchive(projectId, file);
                message.success('已上传并完成分析');
                setImportOpen(false);
                await reload();
              } catch (err: any) {
                message.error(apiError(err, '上传失败'));
              } finally {
                setLoading(false);
              }
              return false;
            }}>
              <Button>上传 ZIP</Button>
            </Upload>
          </Space>
          <input
            ref={(el) => {
              folderRef.current = el;
              if (el) {
                el.setAttribute('webkitdirectory', '');
                el.setAttribute('directory', '');
              }
            }}
            type="file"
            multiple
            hidden
            onChange={async (event) => {
              const files = event.target.files;
              event.target.value = '';
              const projectId = getCurrentProjectId();
              if (!files?.length || !projectId) return;
              setLoading(true);
              try {
                await importProjectArchive(projectId, await zipPickedFolder(files));
                message.success('已上传并完成分析');
                setImportOpen(false);
                await reload();
              } catch (err: any) {
                message.error(apiError(err, '上传失败'));
              } finally {
                setLoading(false);
              }
            }}
          />
        </div>
      </Modal>

      <Drawer title={drawer?.title} open={!!drawer} onClose={() => setDrawer(null)} width={360}>
        {drawer?.body}
      </Drawer>
    </UnderstandingContext.Provider>
  );
}
