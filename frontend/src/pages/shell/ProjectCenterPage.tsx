import { useEffect, useMemo, useState } from 'react';
import { Button, Drawer, Dropdown, Empty, Input, Modal, Space, message } from 'antd';
import { deleteProject, fetchWorkspace, updateProject, type Project } from '@/services/workspace';
import { fetchProjectUnderstanding } from '@/services/projectExplorer';
import { useNavigate } from 'react-router-dom';
import { getCurrentProjectId, setCurrentProjectId } from '@/pages/product/projectStore';
import { formatAgo } from './nav';
import ProjectCreateDrawer from './ProjectCreateDrawer';
import './shell.css';

type Extra = { pages?: number | null; cases?: number | null; updated?: string | null; type: string };

export default function ProjectCenterPage() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [extras, setExtras] = useState<Record<number, Extra>>({});
  const [loaded, setLoaded] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [importTarget, setImportTarget] = useState<Project | null>(null);
  const [selectedId, setSelectedId] = useState(getCurrentProjectId());
  const [settings, setSettings] = useState<Project | null>(null);
  const [settingsName, setSettingsName] = useState('');
  const [settingsDesc, setSettingsDesc] = useState('');

  const load = async () => {
    const data = await fetchWorkspace();
    const rows: Project[] = data?.projects || [];
    setProjects(rows);
    setLoaded(true);
    rows.slice(0, 20).forEach((item) => {
      fetchProjectUnderstanding(item.id).then((understanding) => {
        setExtras((prev) => ({
          ...prev,
          [item.id]: {
            pages: understanding?.scale?.pages ?? null,
            cases: understanding?.scale?.cases ?? null,
            updated: understanding?.updated_at || item.last_test_at,
            type: item.description || (understanding?.project?.frontend ? 'Web 应用' : '项目'),
          },
        }));
      }).catch(() => {
        setExtras((prev) => ({
          ...prev,
          [item.id]: { pages: null, cases: null, updated: item.last_test_at, type: item.description || '项目' },
        }));
      });
    });
  };

  useEffect(() => {
    load().catch(() => message.error('加载项目失败'));
  }, []);

  const select = (project: Project) => {
    setSelectedId(project.id);
    setCurrentProjectId(project.id, project.name);
    navigate('/understand');
  };

  const visible = useMemo(
    () => projects.filter((item) => !keyword.trim() || item.name.toLowerCase().includes(keyword.trim().toLowerCase())),
    [projects, keyword],
  );

  return (
    <div className="pw-page">
      <div className="pc-head">
        <div>
          <h1>项目管理</h1>
          <p>选择一个项目后进入该项目的工作台。项目之间的理解、设计、任务和执行互相隔离。</p>
        </div>
        <Space>
          <Input allowClear placeholder="搜索项目" value={keyword} onChange={(e) => setKeyword(e.target.value)} style={{ width: 220 }} />
          <Button onClick={() => { setImportTarget(null); setImportOpen(true); }}>导入项目</Button>
          <Button type="primary" onClick={() => setCreateOpen(true)}>＋ 新建项目</Button>
        </Space>
      </div>
      {!loaded ? <Empty description="正在加载项目…" /> : visible.length === 0 ? <Empty description="还没有项目" /> : (
        <div className="pc-list">
          {visible.map((project) => {
            const extra = extras[project.id] || { type: project.description || '项目', pages: null, cases: null, updated: project.last_test_at };
            return (
              <div key={project.id} className={`pc-item ${selectedId === project.id ? 'is-on' : ''}`}>
                <button type="button" className="pc-item-main" onClick={() => select(project)}>
                  <span className="pc-mark">{project.name.slice(0, 1)}</span>
                  <span className="pc-item-id">
                    <b>{project.name}</b>
                    <span className="muted">{extra.type}{project.organization_name ? ` · ${project.organization_name}` : ''}</span>
                  </span>
                  <span className="pc-item-meta">
                    <span>{extra.pages == null ? '-' : extra.pages} 页面</span>
                    <span>{extra.cases == null ? '-' : extra.cases} 用例</span>
                    <span>更新 {formatAgo(extra.updated)}</span>
                  </span>
                </button>
                <Dropdown
                  menu={{
                    items: [
                      { key: 'settings', label: '项目设置', onClick: () => {
                        setSettings(project);
                        setSettingsName(project.name);
                        setSettingsDesc(project.description || '');
                      } },
                      { key: 'import', label: '导入代码', onClick: () => { setImportTarget(project); setImportOpen(true); } },
                      { key: 'delete', label: '删除', danger: true, onClick: () => {
                        Modal.confirm({
                          title: `删除「${project.name}」？`,
                          content: '删除后不能恢复。',
                          okButtonProps: { danger: true },
                          onOk: async () => {
                            await deleteProject(project.id);
                            message.success('已删除');
                            await load();
                          },
                        });
                      } },
                    ],
                  }}
                >
                  <button className="pc-item-more" type="button" aria-label={`${project.name} 更多`}>···</button>
                </Dropdown>
              </div>
            );
          })}
        </div>
      )}
      <ProjectCreateDrawer
        open={createOpen}
        mode="create"
        onClose={() => setCreateOpen(false)}
        onCreated={(id, name) => {
          setCreateOpen(false);
          setSelectedId(id);
          setCurrentProjectId(id, name);
          void load();
        }}
      />
      <ProjectCreateDrawer
        open={importOpen}
        mode="import"
        project={importTarget}
        onClose={() => { setImportOpen(false); setImportTarget(null); }}
        onCreated={(id, name) => {
          setImportOpen(false);
          setImportTarget(null);
          setSelectedId(id);
          setCurrentProjectId(id, name);
          void load();
        }}
      />
      <Drawer
        title={settings ? `项目设置 · ${settings.name}` : '项目设置'}
        open={!!settings}
        onClose={() => setSettings(null)}
        width={420}
        extra={
          <Button
            type="primary"
            onClick={async () => {
              if (!settings || !settingsName.trim()) return;
              await updateProject(settings.id, settingsName.trim(), settingsDesc.trim() || undefined);
              message.success('已保存');
              setSettings(null);
              await load();
            }}
          >
            保存
          </Button>
        }
      >
        <div style={{ display: 'grid', gap: 12 }}>
          <label>
            项目名称
            <Input value={settingsName} onChange={(e) => setSettingsName(e.target.value)} />
          </label>
          <label>
            描述
            <Input.TextArea rows={4} value={settingsDesc} onChange={(e) => setSettingsDesc(e.target.value)} />
          </label>
        </div>
      </Drawer>
    </div>
  );
}
